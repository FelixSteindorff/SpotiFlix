"""
Gemeinsame UI-Helfer für Listenpanels.

Enthält neben Status-/Ansage-Helfern drei Bausteine, die für Barrierefreiheit
und sauberes Beenden in allen Panels gleich funktionieren müssen:

  * ``call_after`` – wie ``wx.CallAfter``, feuert aber nicht mehr, nachdem das
    Hauptfenster geschlossen wurde (Worker-Threads laufen als Daemons weiter).
  * ``restore_focus`` – setzt den Fokus nach einem Ladevorgang nur dann, wenn
    der Nutzer inzwischen nicht woanders hingewechselt ist.
  * ``context_menu_position`` – öffnet Kontextmenüs am markierten Eintrag statt
    an der zufälligen Mausposition.
"""
import os
import subprocess
import threading

import wx

import applog
import config as cfg
from applog import short_error  # bequem für die Panels
from download_manager import downloads
from spotify_client import client

from i18n import N_, _

#: Sortiermodi für alle Listenansichten (Schlüssel, Beschriftung).
SORT_MODES = [
    ("default", N_("Standard (wie geladen)")),
    ("name", N_("Name A–Z")),
    ("artist", N_("Künstler A–Z")),
    ("album", N_("Album A–Z")),
    ("duration", N_("Dauer (kurz zuerst)")),
    ("date", N_("Datum (neueste zuerst)")),
]

# Wird beim Schließen des Hauptfensters gesetzt. Hintergrund-Threads (Downloads,
# Wiedergabe, Now-Playing) laufen als Daemons weiter und würden sonst
# wx.CallAfter auf bereits zerstörte Widgets feuern ("wrapped C/C++ object has
# been deleted").
_shutting_down = False


def mark_shutting_down():
    """Meldet, dass das Hauptfenster schließt – danach feuert call_after nicht mehr."""
    global _shutting_down
    _shutting_down = True


def is_shutting_down() -> bool:
    return _shutting_down


def call_after(func, *args, **kwargs):
    """``wx.CallAfter``, das beim Beenden der App nichts mehr auslöst."""
    if _shutting_down:
        return

    def guarded():
        if _shutting_down:
            return
        try:
            func(*args, **kwargs)
        except RuntimeError:
            # Zielwidget wurde inzwischen zerstört – beim Beenden normal.
            pass

    wx.CallAfter(guarded)


def is_active_page(window: wx.Window) -> bool:
    """Prüft, ob ``window`` auf der aktuell sichtbaren Notebook-Seite liegt."""
    frame = window.GetTopLevelParent()
    notebook = getattr(frame, "notebook", None)
    if notebook is None:
        return True
    page = notebook.GetCurrentPage()
    current = window
    while current is not None:
        if current is page:
            return True
        current = current.GetParent()
    return False


def focus_origin() -> wx.Window | None:
    """Merkt sich das Fenster, das beim Start eines Ladevorgangs den Fokus hat."""
    return wx.Window.FindFocus()


def restore_focus(target: wx.Window, origin: wx.Window | None):
    """Setzt den Fokus nach einem Ladevorgang auf ``target`` – ohne ihn zu stehlen.

    ``origin`` ist der Fokus vom Start des Ladevorgangs. Hat der Nutzer
    inzwischen den Tab gewechselt oder tippt er in einem anderen Feld, bleibt
    der Fokus dort: Sonst schaltet NVDA mitten im Satz auf die neue Liste um.
    """
    if origin is None:
        return
    if wx.Window.FindFocus() is not origin:
        return
    if not is_active_page(target):
        return
    target.SetFocus()


def context_menu_position(list_ctrl: wx.ListCtrl, event, index: int | None = None) -> wx.Point:
    """Liefert die Menüposition in Client-Koordinaten von ``list_ctrl``.

    Bei Aufruf über die Kontextmenü-Taste bzw. Umschalt+F10 meldet wx die
    Position (-1, -1); dann wird das Menü am markierten Eintrag geöffnet statt
    dort, wo zufällig der Mauszeiger steht.
    """
    position = event.GetPosition()
    if position.x >= 0 and position.y >= 0:
        return list_ctrl.ScreenToClient(position)
    if index is not None and index >= 0:
        try:
            rect = list_ctrl.GetItemRect(index)
            return wx.Point(rect.x + 12, rect.y + rect.height)
        except Exception:
            pass
    return wx.Point(0, 0)


def sort_rows(rows: list[dict], mode: str) -> list[dict]:
    """Sortiert Zeilen nach dem gewählten Modus (stabil, fehlende Felder egal)."""
    if mode == "name":
        return sorted(rows, key=lambda row: row.get("name", "").casefold())
    if mode == "artist":
        return sorted(rows, key=lambda row: (row.get("artist_name", "").casefold(),
                                             row.get("name", "").casefold()))
    if mode == "album":
        return sorted(rows, key=lambda row: (row.get("album_name", "").casefold(),
                                             row.get("name", "").casefold()))
    if mode == "duration":
        return sorted(rows, key=lambda row: row.get("duration_ms") or 0)
    if mode == "date":
        return sorted(rows, key=lambda row: row.get("sort_date", ""), reverse=True)
    return list(rows)


def selected_indices(list_ctrl: wx.ListCtrl) -> list[int]:
    """Liefert alle markierten Zeilennummern einer Liste."""
    indices = []
    index = list_ctrl.GetFirstSelected()
    while index != wx.NOT_FOUND:
        indices.append(index)
        index = list_ctrl.GetNextSelected(index)
    return indices


def selected_rows(list_ctrl: wx.ListCtrl, rows: list[dict]) -> list[dict]:
    """Liefert die markierten Zeilen (in Anzeigereihenfolge)."""
    return [rows[index] for index in selected_indices(list_ctrl) if index < len(rows)]


def select_only(list_ctrl: wx.ListCtrl, index: int):
    """Markiert genau eine Zeile – vorhandene Mehrfachauswahl wird aufgehoben."""
    for other in selected_indices(list_ctrl):
        list_ctrl.SetItemState(other, 0, wx.LIST_STATE_SELECTED)
    if 0 <= index < list_ctrl.GetItemCount():
        list_ctrl.Select(index)
        list_ctrl.Focus(index)
        list_ctrl.EnsureVisible(index)


def filter_rows(rows: list[dict], needle: str) -> list[dict]:
    """Filtert Zeilen nach Name und Details (Groß-/Kleinschreibung egal)."""
    needle = (needle or "").strip().casefold()
    if not needle:
        return list(rows)
    return [
        row for row in rows
        if needle in row.get("name", "").casefold() or needle in row.get("details", "").casefold()
    ]


def count_message(title: str, count: int) -> str:
    """Formuliert die Abschlussmeldung eines Ladevorgangs (auch für 0 Einträge)."""
    if count == 0:
        return _("{title}: keine Einträge").format(title=title)
    if count == 1:
        return _("{title}: 1 Eintrag").format(title=title)
    return _("{title}: {count} Einträge").format(title=title, count=count)


def set_status(window: wx.Window, message: str):
    """Schreibt eine Meldung in die Statusleiste des Hauptfensters."""
    frame = window.GetTopLevelParent()
    if hasattr(frame, "SetStatusText"):
        frame.SetStatusText(message)


def mark_local_player_running(window: wx.Window):
    """Informiert das Hauptfenster, dass der lokale Player läuft."""
    frame = window.GetTopLevelParent()
    if hasattr(frame, "mark_local_player_running"):
        frame.mark_local_player_running()


def announce(window: wx.Window, message: str, interrupt: bool = False, verbose: bool = False):
    """Sagt eine kurze Statusmeldung an (Statusleiste + Sprache/Braille).

    ``interrupt=True`` bricht eine laufende Ansage ab – nur für schnell
    wiederholte Werte wie die Lautstärke sinnvoll.
    ``verbose=True`` kennzeichnet Zwischenmeldungen („Lade …"); sie werden in
    der Einstellung „Kurz" nur in die Statusleiste geschrieben, nicht gesprochen.
    """
    set_status(window, message)
    if verbose and cfg.get_verbosity() == "short":
        return
    frame = window.GetTopLevelParent()
    if hasattr(frame, "announce"):
        frame.announce(message, interrupt=interrupt)


def set_now_playing(window: wx.Window, name: str):
    """Setzt den Fenstertitel auf den laufenden Titel."""
    frame = window.GetTopLevelParent()
    if hasattr(frame, "set_now_playing"):
        frame.set_now_playing(name)


def start_playback(
    parent: wx.Window,
    item: dict,
    context_uri: str | None = None,
    track_uris: list[str] | None = None,
    position: int = 0,
):
    # ``resume_ms`` setzt eine angefangene Podcast-Episode fort.
    """Startet Wiedergabe im Hintergrund, damit die UI nicht blockiert.

    ``context_uri`` markiert, dass der Titel aus einem Album/einer Playlist
    stammt; ``track_uris`` ist die geordnete Titelliste der Ansicht und
    ``position`` der Index des gewählten Titels. So navigieren Vor/Zurück
    zuverlässig innerhalb der Liste.
    """
    uri = item.get("uri")
    name = item.get("name", "")
    if not uri:
        wx.MessageBox(_("Kein Spotify-URI für dieses Element verfügbar."), _("Fehler"), wx.ICON_ERROR)
        return

    artist = item.get("artist_name", "")
    now_playing_label = f"{artist} - {name}" if artist else name
    resume_ms = int(item.get("resume_ms") or 0)
    start_message = _("Starte Wiedergabe: {name}").format(name=name)
    if resume_ms:
        start_message += _(", weiter ab {position}").format(
            position=format_position(resume_ms))
    announce(parent, start_message)

    def worker():
        try:
            client.start_playback(
                uri,
                context_uri=context_uri,
                track_uris=track_uris,
                position=position,
                position_ms=resume_ms,
            )
            call_after(mark_local_player_running, parent)
            call_after(set_now_playing, parent, now_playing_label)
            call_after(announce, parent, _("Wiedergabe gestartet: {name}").format(name=name))
        except Exception as e:
            call_after(wx.MessageBox, str(e), _("Wiedergabefehler"), wx.ICON_WARNING)

    threading.Thread(target=worker, daemon=True).start()


def format_position(ms: int) -> str:
    """Formatiert eine Position/Dauer als m:ss."""
    seconds = max(0, int(ms) // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def open_folder(path: str) -> bool:
    """Öffnet einen Ordner im Datei-Explorer (legt ihn bei Bedarf an)."""
    path = os.path.expanduser(path or "")
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)  # noqa: S606 - gewollter Explorer-Aufruf
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def playback_args(items: list[dict], item: dict) -> tuple[str | None, list[str], int]:
    """Ermittelt (context_uri, geordnete Titelliste, Position) für die Wiedergabe.

    ``items`` ist die aktuell angezeigte Liste; ``item`` der gewählte Eintrag.
    Vor/Zurück navigieren später innerhalb dieser Titelliste.
    """
    playable = [row for row in items if row.get("type") in {"track", "episode"} and row.get("uri")]
    uris = [row["uri"] for row in playable]
    position = 0
    for index, row in enumerate(playable):
        if row is item:
            position = index
            break
    return item.get("context_uri"), uris, position


def collect_page_items(sp, page: dict | None) -> list:
    """Sammelt alle Items einer Spotify-Paging-Antwort ein."""
    items = []
    while page:
        items.extend(page.get("items", []) or [])
        next_url = page.get("next")
        if not next_url:
            break
        page = sp.next(page)
        # Endpunkte wie "gefolgte Künstler" oder "neue Alben" liefern
        # Folgeseiten in einem Wrapper-Objekt (z. B. {"artists": {...}}).
        if page and "items" not in page:
            page = next(
                (value for value in page.values() if isinstance(value, dict) and "items" in value),
                None,
            )
    return items


def start_download(parent: wx.Window, items):
    """Reiht ein Element (oder mehrere) in die Download-Warteschlange ein.

    Die Warteschlange arbeitet nur so viele Aufträge gleichzeitig ab, wie in
    den Einstellungen erlaubt sind; Fortschritt, Abschluss und Fehler meldet
    das Hauptfenster über den Rückruf der Warteschlange.
    """
    if isinstance(items, dict):
        items = [items]
    items = [item for item in items if item]
    if not items:
        return
    for item in items:
        downloads.submit(item)
    if len(items) == 1:
        announce(parent, _("Download eingereiht: {name}").format(
            name=items[0].get("name") or _("Auswahl")))
    else:
        announce(parent, _("{count} Downloads eingereiht").format(count=len(items)))
    applog.info("Download", f"{len(items)} Auftrag/Aufträge eingereiht")
