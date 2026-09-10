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

import config as cfg
from download_manager import DownloadCancelled, download_item
from spotify_client import client

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
        return f"{title}: keine Einträge"
    if count == 1:
        return f"{title}: 1 Eintrag"
    return f"{title}: {count} Einträge"


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
        wx.MessageBox("Kein Spotify-URI für dieses Element verfügbar.", "Fehler", wx.ICON_ERROR)
        return

    artist = item.get("artist_name", "")
    now_playing_label = f"{artist} - {name}" if artist else name
    resume_ms = int(item.get("resume_ms") or 0)
    start_message = f"Starte Wiedergabe: {name}"
    if resume_ms:
        start_message += f", weiter ab {format_position(resume_ms)}"
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
            call_after(announce, parent, f"Wiedergabe gestartet: {name}")
        except Exception as e:
            call_after(wx.MessageBox, str(e), "Wiedergabefehler", wx.ICON_WARNING)

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


def start_download(parent: wx.Window, item: dict):
    """Startet einen Download im Hintergrund.

    Der Fortschritt erscheint in der Statusleiste, statt die UI mit einem modalen
    Dialog zu blockieren – so kann während des Downloads weiter gebrowst werden.
    """
    frame = parent.GetTopLevelParent()
    name = item.get("name") or "Auswahl"

    register = getattr(frame, "download_register", None)
    update = getattr(frame, "download_update", None)
    unregister = getattr(frame, "download_unregister", None)
    # Über das Event kann das Hauptfenster den Download abbrechen.
    cancel_event = threading.Event()
    dl_id = register(name, cancel_event) if register else None

    def progress(done: int, total: int):
        if dl_id is not None and update:
            call_after(update, dl_id, done, total)

    def finish(error: Exception | None):
        if dl_id is not None and unregister:
            unregister(dl_id)
        if isinstance(error, DownloadCancelled):
            announce(parent, f"Download abgebrochen: {name} – {error}")
        elif error:
            announce(parent, f"Download fehlgeschlagen: {name}")
            wx.MessageBox(str(error), "Download-Fehler", wx.ICON_ERROR)
        else:
            announce(parent, f"Download abgeschlossen: {name}")

    def worker():
        try:
            download_item(
                item,
                cfg.get_download_dir(),
                progress_callback=progress,
                cancel_event=cancel_event,
            )
            call_after(finish, None)
        except Exception as e:
            call_after(finish, e)

    announce(parent, f"Download gestartet: {name}")
    threading.Thread(target=worker, daemon=True).start()
