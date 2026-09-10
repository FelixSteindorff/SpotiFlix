"""
Gemeinsame Kontextmenü-Aktionen für die Listenpanels.

Stellt das Aufbauen des Kontextmenüs sowie die Aktionen „Zur Warteschlange
hinzufügen", „Zu Playlist hinzufügen", „In Mediathek speichern", „Öffnen",
„Zum Künstler" und „Zum Album" bereit – einmal zentral, damit Mediathek, Suche,
Entdecken und Warteschlange identisch funktionieren.

Alle Aktionen arbeiten auf einer **Liste** von Einträgen: Die Panels erlauben
Mehrfachauswahl, und was für einen Titel gilt, soll auch für zwanzig gelten.
Ein einzelnes Element darf weiterhin direkt übergeben werden.
"""
import threading

import wx

import applog
import config as cfg
import nvda
from spotify_client import LIBRARY_TYPES, client
from ui.panel_helpers import announce, call_after, set_status, start_download
from ui.browse_common import load_album_tracks, load_playlist_tracks

# Elementtypen, die in die Warteschlange bzw. zu einer Playlist können.
QUEUEABLE = {"track", "episode", "album", "playlist"}
PLAYLISTABLE = {"track", "episode", "album", "playlist"}
# Elementtypen, die heruntergeladen werden können (Episoden unterstützt
# librespot_download vollständig).
DOWNLOADABLE = {"track", "episode", "album", "artist", "playlist"}
# Elementtypen, die sich als Schnellzugriff merken lassen.
BOOKMARKABLE = {"album", "artist", "playlist", "show"}

# Menübeschriftung fürs Speichern/Folgen je Elementtyp.
_LIBRARY_LABELS = {
    "artist": "Künstler folgen / nicht mehr folgen",
    "playlist": "Playlist speichern / entfernen",
    "show": "Podcast abonnieren / abbestellen",
}
_LIBRARY_DEFAULT_LABEL = "In Mediathek speichern / entfernen"


def as_items(items) -> list[dict]:
    """Nimmt einen Eintrag oder eine Liste und liefert immer eine Liste."""
    if isinstance(items, dict):
        items = [items]
    return [item for item in (items or []) if item]


def get_artist_ref(item: dict) -> tuple[str | None, str]:
    """Liefert (Künstler-ID, Künstlername) – egal ob Künstler selbst oder Titelzeile."""
    if item.get("type") == "artist" and item.get("id"):
        return item["id"], item.get("name", "")
    if item.get("artist_id"):
        return item["artist_id"], item.get("artist_name", "")
    artists = item.get("artists")
    if isinstance(artists, list) and artists:
        first = artists[0] or {}
        return first.get("id"), first.get("name", "")
    return None, ""


def get_album_ref(item: dict) -> tuple[str | None, str]:
    """Liefert (Album-ID, Albumname) – egal ob Album selbst oder Titelzeile."""
    if item.get("type") == "album" and item.get("id"):
        return item["id"], item.get("name", "")
    if item.get("album_id"):
        return item["album_id"], item.get("album_name", "")
    album = item.get("album")
    if isinstance(album, dict) and album.get("id"):
        return album["id"], album.get("name", "")
    return None, ""


def populate_item_menu(panel: wx.Window, menu: wx.Menu, items):
    """Füllt ein Kontextmenü passend zur Auswahl und verknüpft die Aktionen."""
    items = as_items(items)
    if not items:
        return
    primary = items[0]
    item_type = primary.get("type")
    single = len(items) == 1
    count = f" ({len(items)})" if not single else ""
    types = {entry.get("type") for entry in items}

    # „Öffnen" ergibt nur für genau einen Eintrag Sinn.
    if single:
        if item_type == "album" and hasattr(panel, "goto_album"):
            _add(menu, "Album öffnen", lambda: panel.goto_album(primary))
        elif item_type == "artist" and hasattr(panel, "goto_artist"):
            _add(menu, "Künstler öffnen", lambda: panel.goto_artist(primary))
        elif item_type == "playlist" and hasattr(panel, "goto_playlist"):
            _add(menu, "Playlist öffnen", lambda: panel.goto_playlist(primary))
        elif item_type == "show" and hasattr(panel, "goto_show"):
            _add(menu, "Podcast öffnen", lambda: panel.goto_show(primary))

    if types & DOWNLOADABLE:
        downloadable = [entry for entry in items if entry.get("type") in DOWNLOADABLE]
        _add(menu, f"Herunterladen{count}", lambda: start_download(panel, downloadable))

    if types & QUEUEABLE:
        _add(menu, f"Zur Warteschlange hinzufügen{count}\tStrg+Q",
             lambda: add_to_queue(panel, items))

    if types & PLAYLISTABLE:
        _add(menu, f"Zu Playlist hinzufügen …{count}\tStrg+Umschalt+P",
             lambda: add_to_playlist(panel, items))

    if types & LIBRARY_TYPES:
        label = _LIBRARY_LABELS.get(item_type, _LIBRARY_DEFAULT_LABEL) if single else "In Mediathek speichern / entfernen"
        _add(menu, f"{label}{count}\tStrg+S", lambda: toggle_library(panel, items))

    if single and item_type in BOOKMARKABLE and primary.get("id"):
        _add(menu, "Als Schnellzugriff merken", lambda: add_bookmark(panel, primary))

    # Beziehungs-Navigation für Titel/Episoden: zu deren Künstler bzw. Album.
    if single and item_type in {"track", "episode"}:
        artist_id, _name = get_artist_ref(primary)
        if artist_id and hasattr(panel, "goto_artist"):
            _add(menu, "Zum Künstler", lambda: panel.goto_artist(primary))
        album_id, _name = get_album_ref(primary)
        if album_id and hasattr(panel, "goto_album"):
            _add(menu, "Zum Album", lambda: panel.goto_album(primary))

    if hasattr(panel, "_export_view"):
        menu.AppendSeparator()
        _add(menu, "Angezeigte Liste exportieren …\tStrg+E", panel._export_view)


def _add(menu: wx.Menu, label: str, handler):
    """Hängt einen Menüpunkt mit Aktion an."""
    ref = wx.NewIdRef()
    menu.Append(ref, label)
    menu.Bind(wx.EVT_MENU, lambda evt: handler(), id=ref)


def _resolve_rows(sp, item: dict) -> list[dict]:
    """Löst ein Element in einzelne Titelzeilen auf (Album/Playlist → deren Titel)."""
    item_type = item.get("type")
    if item_type in {"track", "episode"}:
        return [item] if item.get("uri") else []
    if item_type == "album" and item.get("id"):
        return load_album_tracks(sp, item["id"])
    if item_type == "playlist" and item.get("id"):
        return load_playlist_tracks(sp, item["id"])
    return []


def _resolve_many(sp, items: list[dict]) -> list[dict]:
    """Löst mehrere Elemente auf und entfernt Doppelte (URI-gleich)."""
    rows = []
    seen = set()
    for item in items:
        for row in _resolve_rows(sp, item):
            uri = row.get("uri")
            if not uri or uri in seen:
                continue
            seen.add(uri)
            rows.append(row)
    return rows


def _selection_name(items: list[dict]) -> str:
    """Beschreibt die Auswahl für Ansagen."""
    if len(items) == 1:
        return items[0].get("name", "")
    return f"{len(items)} Einträge"


def _enqueue_in_panel(panel: wx.Window, rows: list[dict]):
    """Trägt Titel in die sichtbare Warteschlange (Tab) ein, falls vorhanden."""
    frame = panel.GetTopLevelParent()
    if hasattr(frame, "enqueue"):
        frame.enqueue(rows)


def add_to_queue(panel: wx.Window, items):
    """Reiht Titel (oder alle Titel von Alben/Playlists) im Hintergrund ein."""
    items = [item for item in as_items(items) if item.get("type") in QUEUEABLE]
    if not items:
        announce(panel, "Dieses Element kann nicht in die Warteschlange.")
        return
    name = _selection_name(items)

    def worker():
        try:
            sp = client.get()
            if not sp:
                call_after(wx.MessageBox, "Zuerst autorisieren!", "Fehler", wx.ICON_ERROR)
                return
            rows = [row for row in _resolve_many(sp, items) if row.get("uri")]
            if not rows:
                call_after(announce, panel, "Keine Titel zum Hinzufügen gefunden.")
                return
            # Spotify kennt nur „ein Titel pro Aufruf" – die Titel darum einzeln
            # einreihen und dabei mitzählen. Ohne Zähler würde ein Abbruch bei
            # Titel 3 von 50 trotzdem als „50 hinzugefügt" gemeldet, und für
            # Screenreader-Nutzer gibt es keine visuelle Korrektur.
            added = 0
            failure = None
            for row in rows:
                try:
                    client.add_to_queue(row["uri"])
                except Exception as e:
                    failure = e
                    break
                added += 1
                if len(rows) > 20 and added % 20 == 0:
                    call_after(set_status, panel, f"{name}: {added} von {len(rows)} eingereiht …")
            call_after(_enqueue_in_panel, panel, rows[:added])
            if failure:
                applog.error("Warteschlange", failure)
            call_after(announce, panel, _queue_message(name, added, len(rows), failure))
        except Exception as e:
            applog.error("Warteschlange", e)
            call_after(wx.MessageBox, str(e), "Warteschlange-Fehler", wx.ICON_WARNING)

    announce(panel, f"Füge zur Warteschlange hinzu: {name}", verbose=True)
    threading.Thread(target=worker, daemon=True).start()


def _queue_message(name: str, added: int, total: int, failure: Exception | None) -> str:
    """Formuliert die Rückmeldung – sie ist die einzige, die ein Blinder bekommt."""
    if added == 0:
        return f"{name} konnte nicht zur Warteschlange hinzugefügt werden: {failure}"
    if added < total:
        return f"{name} – nur {added} von {total} Titeln eingereiht, dann Fehler: {failure}"
    if added == 1:
        return f"{name} zur Warteschlange hinzugefügt"
    return f"{name} – {added} Titel zur Warteschlange hinzugefügt"


def _library_message(item_type: str, name: str, saved: bool, count: int = 1) -> str:
    """Formuliert die Rückmeldung zum Speichern/Folgen."""
    if count > 1:
        return f"{count} Einträge {'gespeichert' if saved else 'entfernt'}"
    if item_type == "artist":
        return f"Sie folgen jetzt {name}" if saved else f"Sie folgen {name} nicht mehr"
    if item_type == "show":
        return f"Podcast {name} abonniert" if saved else f"Podcast {name} abbestellt"
    if saved:
        return f"{name} in der Mediathek gespeichert"
    return f"{name} aus der Mediathek entfernt"


def toggle_library(panel: wx.Window, items):
    """Speichert Elemente in der Mediathek – oder entfernt sie wieder.

    Der Zustand des ersten Eintrags gibt die Richtung vor; bei einer
    Mehrfachauswahl bekommen alle dieselbe Behandlung. Das ist vorhersagbar,
    auch wenn man die Liste nicht sieht.
    """
    items = [item for item in as_items(items)
             if item.get("type") in LIBRARY_TYPES and item.get("id")]
    if not items:
        announce(panel, "Dieses Element kann nicht in der Mediathek gespeichert werden.")
        return
    name = _selection_name(items)

    def worker():
        try:
            saved = client.is_in_library(items[0]["type"], items[0]["id"])
            if saved is None:
                call_after(announce, panel, "Zuerst autorisieren!")
                return
            target = not saved
            changed = 0
            for item in items:
                client.set_in_library(item["type"], item["id"], target)
                changed += 1
            call_after(announce, panel,
                       _library_message(items[0]["type"], name, target, changed))
        except Exception as e:
            applog.error("Mediathek", e)
            call_after(announce, panel, f"Mediathek-Fehler: {e}")
            call_after(wx.MessageBox, str(e), "Mediathek-Fehler", wx.ICON_WARNING)

    announce(panel, f"Mediathek wird aktualisiert: {name}", verbose=True)
    threading.Thread(target=worker, daemon=True).start()


def add_bookmark(panel: wx.Window, item: dict):
    """Merkt ein Album, einen Künstler, eine Playlist oder einen Podcast als Schnellzugriff."""
    if item.get("type") not in BOOKMARKABLE or not item.get("id"):
        announce(panel, "Dieses Element lässt sich nicht als Schnellzugriff merken.")
        return
    bookmarks = cfg.get_bookmarks()
    if any(entry["id"] == item["id"] for entry in bookmarks):
        announce(panel, f"{item.get('name', '')} ist bereits als Schnellzugriff gemerkt.")
        return
    if len(bookmarks) >= cfg.MAX_BOOKMARKS:
        announce(panel, f"Es sind schon {cfg.MAX_BOOKMARKS} Schnellzugriffe belegt – "
                        "bitte zuerst einen entfernen (Extras > Schnellzugriffe).")
        return
    bookmarks.append({"type": item["type"], "id": item["id"], "name": item.get("name", "")})
    cfg.save_bookmarks(bookmarks)
    frame = panel.GetTopLevelParent()
    if hasattr(frame, "refresh_bookmarks"):
        frame.refresh_bookmarks()
    announce(panel, f"Schnellzugriff {len(bookmarks)}: {item.get('name', '')} "
                    f"(Strg+Umschalt+{len(bookmarks)})")


def add_to_playlist(panel: wx.Window, items):
    """Öffnet die Playlist-Auswahl und fügt die Titel hinzu."""
    items = [item for item in as_items(items) if item.get("type") in PLAYLISTABLE]
    if not items:
        announce(panel, "Dieses Element kann nicht zu einer Playlist hinzugefügt werden.")
        return
    name = _selection_name(items)

    # editable_playlists() paginiert alle Playlists (50 pro Request) – bei 300
    # Playlists sind das 6 Requests. Das darf den UI-Thread nicht blockieren.
    announce(panel, "Lade Playlists …", verbose=True)

    def load_playlists():
        try:
            playlists = client.editable_playlists()
        except Exception as e:
            applog.error("Playlist", e)
            call_after(wx.MessageBox, str(e), "Fehler", wx.ICON_ERROR)
            call_after(announce, panel, f"Playlists konnten nicht geladen werden: {e}")
            return
        call_after(_choose_playlist, panel, items, name, playlists)

    threading.Thread(target=load_playlists, daemon=True).start()


def _choose_playlist(panel: wx.Window, items: list[dict], name: str, playlists: list[dict]):
    """Zeigt die Playlist-Auswahl und startet danach das Hinzufügen."""
    if not playlists:
        announce(panel, "Keine bearbeitbaren Playlists gefunden.")
        wx.MessageBox(
            "Es wurden keine bearbeitbaren Playlists gefunden.\n"
            "Legen Sie zuerst eine eigene Playlist in Spotify an.",
            "Keine Playlists",
            wx.ICON_INFORMATION,
        )
        return

    dialog = PlaylistChooserDialog(panel.GetTopLevelParent(), playlists)
    if dialog.ShowModal() != wx.ID_OK:
        dialog.Destroy()
        return
    playlist = dialog.get_selected()
    dialog.Destroy()
    if not playlist:
        return

    playlist_name = playlist["name"]
    playlist_id = playlist["id"]
    announce(panel, f"Füge zu Playlist hinzu: {playlist_name}")

    def worker():
        try:
            sp = client.get()
            if not sp:
                call_after(wx.MessageBox, "Zuerst autorisieren!", "Fehler", wx.ICON_ERROR)
                return
            uris = [row["uri"] for row in _resolve_many(sp, items) if row.get("uri")]
            if not uris:
                call_after(announce, panel, "Keine Titel zum Hinzufügen gefunden.")
                return
            added = client.add_tracks_to_playlist(playlist_id, uris)
            if added == 1:
                message = f"{name} zu Playlist {playlist_name} hinzugefügt"
            else:
                message = f"{name} – {added} Titel zu Playlist {playlist_name} hinzugefügt"
            call_after(announce, panel, message)
        except Exception as e:
            applog.error("Playlist", e)
            call_after(wx.MessageBox, str(e), "Playlist-Fehler", wx.ICON_WARNING)

    threading.Thread(target=worker, daemon=True).start()


class PlaylistChooserDialog(wx.Dialog):
    """Auswahldialog für Playlists mit Tippsuche (Buchstaben filtern die Liste)."""

    def __init__(self, parent, playlists: list[dict]):
        super().__init__(parent, title="Playlist auswählen", size=(420, 460))
        self._playlists = sorted(playlists, key=lambda p: p.get("name", "").lower())
        self._filtered = list(self._playlists)
        self._announced_empty = False

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label="Playlist (tippen zum Filtern):")
        sizer.Add(label, 0, wx.ALL, 8)

        self.search = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.search.SetToolTip("Buchstaben eingeben, um die Playlist zu finden")
        self.search.Bind(wx.EVT_TEXT, self._on_filter)
        self.search.Bind(wx.EVT_TEXT_ENTER, lambda e: self._accept())
        sizer.Add(self.search, 0, wx.ALL | wx.EXPAND, 8)

        # wx.ListBox bietet zusätzlich native Tippsuche, wenn der Fokus darauf liegt.
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        # Das Label über dem Textfeld gehört zum Textfeld – die Liste braucht
        # einen eigenen zugänglichen Namen.
        self.listbox.SetName("Playlists")
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._accept())
        sizer.Add(self.listbox, 1, wx.ALL | wx.EXPAND, 8)

        self.btn_new = wx.Button(panel, label="Neue Playlist …")
        self.btn_new.SetToolTip("Legt eine neue, private Playlist in Ihrem Spotify-Konto an")
        self.btn_new.Bind(wx.EVT_BUTTON, self._on_new_playlist)
        sizer.Add(self.btn_new, 0, wx.ALL | wx.EXPAND, 8)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(panel, id=wx.ID_OK, label="Hinzufügen")
        btn_ok.SetDefault()
        btn_cancel = wx.Button(panel, id=wx.ID_CANCEL, label="Abbrechen")
        btn_box.Add(btn_ok, 1, wx.ALL | wx.EXPAND, 5)
        btn_box.Add(btn_cancel, 1, wx.ALL | wx.EXPAND, 5)
        sizer.Add(btn_box, 0, wx.ALL | wx.EXPAND, 8)

        panel.SetSizer(sizer)
        self.Bind(wx.EVT_BUTTON, lambda e: self._accept(), id=wx.ID_OK)
        self._refresh_list()
        self.CenterOnParent()
        self.search.SetFocus()

    def _on_new_playlist(self, event):
        """Legt eine neue Playlist an und wählt sie direkt aus."""
        dialog = wx.TextEntryDialog(self, "Name der neuen Playlist:", "Neue Playlist")
        created = dialog.ShowModal() == wx.ID_OK
        name = dialog.GetValue().strip()
        dialog.Destroy()
        if not created or not name:
            return

        self.btn_new.Enable(False)
        nvda.announce(f"Playlist wird angelegt: {name}")

        def worker():
            try:
                playlist = client.create_playlist(name)
            except Exception as e:
                applog.error("Playlist", e)
                call_after(wx.MessageBox, str(e), "Playlist-Fehler", wx.ICON_ERROR)
                call_after(self.btn_new.Enable, True)
                return
            call_after(self._add_playlist, playlist)

        threading.Thread(target=worker, daemon=True).start()

    def _add_playlist(self, playlist: dict):
        """Übernimmt eine frisch angelegte Playlist in die Auswahl."""
        self.btn_new.Enable(True)
        if not playlist.get("id"):
            return
        self._playlists.append(playlist)
        self._playlists.sort(key=lambda p: p.get("name", "").lower())
        self.search.SetValue("")
        self._filtered = list(self._playlists)
        self._refresh_list()
        index = next(
            (i for i, entry in enumerate(self._filtered) if entry.get("id") == playlist["id"]), 0
        )
        self.listbox.SetSelection(index)
        self.listbox.SetFocus()
        nvda.announce(f"Playlist {playlist.get('name', '')} angelegt und ausgewählt")

    def _on_filter(self, event):
        needle = self.search.GetValue().strip().lower()
        if needle:
            self._filtered = [p for p in self._playlists if needle in p.get("name", "").lower()]
        else:
            self._filtered = list(self._playlists)
        self._refresh_list()

    def _refresh_list(self):
        self.listbox.Set([p.get("name", "") for p in self._filtered])
        if self._filtered:
            self.listbox.SetSelection(0)
            self._announced_empty = False
        elif not self._announced_empty:
            # Nur beim Übergang ansagen, nicht bei jedem weiteren Tastendruck.
            self._announced_empty = True
            nvda.announce("Keine passende Playlist")

    def _accept(self):
        """Übernimmt die Auswahl – oder sagt an, warum nichts passiert."""
        if self.listbox.GetSelection() == wx.NOT_FOUND:
            wx.Bell()
            nvda.announce("Keine Playlist ausgewählt – Filter anpassen")
            return
        self.EndModal(wx.ID_OK)

    def get_selected(self) -> dict | None:
        index = self.listbox.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._filtered):
            return None
        return self._filtered[index]
