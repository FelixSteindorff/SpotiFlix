"""
Panel für die Spotify-Suche.

Alle API-Aufrufe laufen in Hintergrund-Threads: Der Worker holt die Daten und
liefert fertige Zeilen; angezeigt wird erst im Hauptthread. Die Ergebnisliste
dient zugleich als Browser – „Album öffnen", „Zum Künstler" usw. ersetzen ihren
Inhalt und die Rücktaste (bzw. Alt+Pfeil links/Escape) führt zurück.

Komfort in der Liste:
  * `Strg+F` filtert die angezeigten Treffer, Escape hebt den Filter auf.
  * „Mehr laden" holt die nächsten 20 Treffer, solange Spotify welche hat.
  * Das Suchfeld merkt sich die letzten Suchbegriffe (Pfeiltasten im Feld).
"""
import threading

import wx

import config as cfg
from spotify_client import client
from ui.browse_common import (
    ARTIST_SECTION_TITLES,
    album_row,
    artist_overview_rows,
    artist_row,
    episode_row,
    load_album_tracks,
    load_artist_section,
    load_playlist_tracks,
    load_show_episodes,
    playlist_row,
    section_items,
    show_row,
    track_row,
)
from ui.context_actions import get_album_ref, get_artist_ref, populate_item_menu
from ui.panel_helpers import (
    announce,
    call_after,
    context_menu_position,
    count_message,
    filter_rows,
    focus_origin,
    playback_args,
    restore_focus,
    start_playback,
)

#: Wie viele Treffer je Abschnitt und Ladevorgang geholt werden.
SEARCH_PAGE_SIZE = 20


class SearchPanel(wx.Panel):
    """Suchpanel – API-Calls laufen in Hintergrund-Threads."""

    SEARCH_TYPES = {
        "Top-Ergebnisse": "track,playlist,album,artist,show,episode",
        "Titel": "track",
        "Playlists": "playlist",
        "Alben": "album",
        "Künstler": "artist",
        "Podcasts": "show,episode",
    }

    # Welche Abschnitte der Suchantwort zu welcher Ergebnisart gehören.
    SECTION_KEYS = {
        "Top-Ergebnisse": ["tracks", "playlists", "albums", "artists", "shows", "episodes"],
        "Titel": ["tracks"],
        "Playlists": ["playlists"],
        "Alben": ["albums"],
        "Künstler": ["artists"],
        "Podcasts": ["shows", "episodes"],
    }

    # Zeilenbauer je Abschnitt.
    SECTION_BUILDERS = {
        "tracks": track_row,
        "playlists": playlist_row,
        "albums": album_row,
        "artists": artist_row,
        "shows": show_row,
        "episodes": episode_row,
    }

    # Präfix je Elementtyp, damit die Art des Treffers mitgesprochen wird.
    _LABEL_PREFIX = {
        "track": "Titel: ",
        "episode": "Episode: ",
        "album": "Album: ",
        "artist": "Künstler: ",
        "playlist": "Playlist: ",
        "show": "Podcast: ",
    }

    #: Elementtypen, für die ein Kontextmenü angeboten wird.
    CONTEXT_TYPES = {"track", "episode", "album", "artist", "playlist", "show"}

    def __init__(self, parent):
        super().__init__(parent)

        sizer = wx.BoxSizer(wx.VERTICAL)

        search_label = wx.StaticText(self, label="Suche:")
        # Kombinationsfeld statt Textfeld: Die zuletzt genutzten Suchbegriffe
        # lassen sich mit den Pfeiltasten zurückholen.
        self.search_input = wx.ComboBox(
            self, choices=cfg.get_search_history(), style=wx.TE_PROCESS_ENTER
        )
        self.search_input.SetName("Suchbegriff")
        self.search_input.SetToolTip("Suchbegriff eingeben; Pfeiltasten holen frühere Suchen zurück")
        self.search_input.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        sizer.Add(search_label, 0, wx.TOP, 5)
        sizer.Add(self.search_input, 1, wx.ALL | wx.EXPAND, 10)

        type_label = wx.StaticText(self, label="Suchtyp:")
        self.type_combo = wx.ComboBox(
            self,
            choices=list(self.SEARCH_TYPES.keys()),
            style=wx.CB_READONLY,
        )
        self.type_combo.SetName("Suchtyp")
        self.type_combo.SetSelection(0)
        sizer.Add(type_label, 0, wx.TOP, 5)
        sizer.Add(self.type_combo, 1, wx.ALL | wx.EXPAND, 10)

        button_box = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_search = wx.Button(self, label="Suchen")
        self.btn_search.Bind(wx.EVT_BUTTON, self._on_search)
        self.btn_search.SetToolTip("Startet die Suche bei Spotify")
        button_box.Add(self.btn_search, 1, wx.ALL | wx.EXPAND, 5)
        self.btn_more = wx.Button(self, label="Mehr laden")
        self.btn_more.Enable(False)
        self.btn_more.Bind(wx.EVT_BUTTON, lambda event: self._load_more())
        self.btn_more.SetToolTip("Holt die nächsten Treffer zur laufenden Suche")
        button_box.Add(self.btn_more, 1, wx.ALL | wx.EXPAND, 5)
        sizer.Add(button_box, 0, wx.ALL | wx.EXPAND, 5)

        result_label = wx.StaticText(self, label="Suchergebnisse:")
        self.result_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.result_list.InsertColumn(0, "Name", width=400)
        self.result_list.InsertColumn(1, "Details", width=300)
        # Zugänglicher Name: NVDA meldet sonst nur „Liste". Er wechselt mit der
        # geöffneten Ansicht (Album, Künstler, Podcast …).
        self.result_list.SetName("Suchergebnisse")
        self.result_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_play)
        self.result_list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.result_list.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        sizer.Add(result_label, 0, wx.TOP, 5)
        sizer.Add(self.result_list, 3, wx.ALL | wx.EXPAND, 10)

        self.btn_play = wx.Button(self, label="Abspielen")
        self.btn_play.Enable(False)
        self.btn_play.Bind(wx.EVT_BUTTON, self._on_play)
        self.btn_play.SetToolTip("Spielt den ausgewählten Eintrag direkt ab")
        sizer.Add(self.btn_play, 0, wx.ALL | wx.EXPAND, 10)

        self.SetSizer(sizer)
        # Alle geladenen Zeilen der aktuellen Ansicht; ``results_data`` ist der
        # sichtbare (ggf. gefilterte) Ausschnitt davon.
        self._all_rows: list[dict] = []
        self.results_data: list[dict] = []
        self._filter = ""
        self._current_title = "Suchergebnisse"
        # Laufende Suche für „Mehr laden".
        self._query = ""
        self._display_type = ""
        self._offset = 0
        # Navigations-Verlauf, damit „Zum Künstler/Album/Playlist" mit
        # Rücktaste wieder zu den Suchergebnissen zurückführt.
        self._nav_stack: list[tuple[list[dict], str, int]] = []

    def focus_default(self):
        self.search_input.SetFocus()

    # -- Suche ---------------------------------------------------------------

    def _on_search(self, event):
        query = self.search_input.GetValue().strip()
        if not query:
            wx.MessageBox("Geben Sie einen Suchbegriff ein", "Info", wx.ICON_INFORMATION)
            return
        sp = client.get()
        if not sp:
            wx.MessageBox("Zuerst autorisieren!", "Fehler", wx.ICON_ERROR)
            return
        self._query = query
        self._display_type = self.type_combo.GetValue()
        self._offset = 0
        self._run_search(sp, append=False)

    def _load_more(self):
        """Holt die nächste Trefferseite zur laufenden Suche."""
        sp = client.get()
        if not sp or not self._query:
            return
        self._offset += SEARCH_PAGE_SIZE
        self._run_search(sp, append=True)

    def _run_search(self, sp, append: bool):
        self.btn_search.Enable(False)
        self.btn_more.Enable(False)
        message = "Lade weitere Treffer …" if append else f"Suche nach: {self._query}"
        announce(self, message, verbose=append)
        wx.BeginBusyCursor()
        origin = focus_origin()
        threading.Thread(
            target=self._search_worker,
            args=(sp, self._query, self._display_type, self._offset, append, origin),
            daemon=True,
        ).start()

    def _search_worker(self, sp, query: str, display_type: str, offset: int, append: bool, origin):
        try:
            results = sp.search(
                q=query,
                limit=SEARCH_PAGE_SIZE,
                offset=offset,
                type=self.SEARCH_TYPES[display_type],
            )
            rows = self._search_rows(results, display_type)
            has_more = self._has_more(results, display_type)
            call_after(self._show_search_results, rows, query, append, has_more, origin)
        except Exception as e:
            call_after(wx.MessageBox, f"Fehler: {e}", "Fehler", wx.ICON_ERROR)
            call_after(announce, self, f"Suche fehlgeschlagen: {e}")
        finally:
            call_after(wx.EndBusyCursor)
            call_after(self.btn_search.Enable, True)

    def _search_rows(self, results: dict, display_type: str) -> list[dict]:
        """Wandelt die Suchantwort in einheitliche Zeilen um.

        ``section_items`` ist bewusst null-sicher: Spotify liefert einzelne
        Abschnitte gelegentlich als ``null``, statt sie wegzulassen.
        """
        rows: list[dict] = []
        for key in self.SECTION_KEYS.get(display_type, []):
            builder = self.SECTION_BUILDERS[key]
            rows += [builder(item) for item in section_items(results, key) if item]
        return rows

    def _has_more(self, results: dict, display_type: str) -> bool:
        """Prüft, ob Spotify zu mindestens einem Abschnitt weitere Treffer hat."""
        for key in self.SECTION_KEYS.get(display_type, []):
            section = (results or {}).get(key) or {}
            if section.get("next"):
                return True
        return False

    def _show_search_results(self, rows: list[dict], query: str, append: bool, has_more: bool, origin):
        """Zeigt Suchtreffer an – frisch oder als Anhang von „Mehr laden"."""
        title = f"Suchergebnisse: {query}"
        if append:
            new_rows = self._all_rows + rows
            selected = self.result_list.GetFirstSelected()
            self._set_rows(new_rows, title, select=max(0, selected))
            announce(self, f"{len(rows)} weitere Treffer, insgesamt {len(new_rows)}")
        else:
            self._nav_stack = []
            self._filter = ""
            self._set_rows(rows, title)
            cfg.add_search_history(query)
            self._refresh_history()
            announce(self, count_message(title, len(rows)))
            restore_focus(self.result_list, origin)
        self.btn_more.Enable(has_more and bool(rows))

    def _refresh_history(self):
        """Übernimmt den gespeicherten Suchverlauf in das Kombinationsfeld."""
        value = self.search_input.GetValue()
        self.search_input.Set(cfg.get_search_history())
        self.search_input.SetValue(value)

    # -- Anzeige -------------------------------------------------------------

    def _set_rows(self, rows: list[dict], title: str, select: int = 0):
        self._all_rows = list(rows)
        self._current_title = title
        self._render(select)

    def _render(self, select: int = 0):
        """Zeichnet die (ggf. gefilterten) Zeilen und aktualisiert den Listennamen."""
        self.results_data = filter_rows(self._all_rows, self._filter)
        self.result_list.DeleteAllItems()
        for row in self.results_data:
            prefix = self._LABEL_PREFIX.get(row.get("type"), "")
            index = self.result_list.InsertItem(
                self.result_list.GetItemCount(), f"{prefix}{row.get('name', '')}"
            )
            self.result_list.SetItem(index, 1, row.get("details", ""))
        name = self._current_title
        if self._filter:
            name = f"{name} (Filter: {self._filter})"
        self.result_list.SetName(name)
        self.btn_play.Enable(bool(self.results_data))
        if self.results_data:
            target = max(0, min(select, len(self.results_data) - 1))
            self.result_list.Select(target)
            self.result_list.Focus(target)
            self.result_list.EnsureVisible(target)

    def get_selected_item(self) -> dict | None:
        selected = self.result_list.GetFirstSelected()
        if selected == wx.NOT_FOUND or selected >= len(self.results_data):
            return None
        return self.results_data[selected]

    # -- Filtern -------------------------------------------------------------

    def _prompt_filter(self):
        dialog = wx.TextEntryDialog(
            self, "Trefferliste filtern (leer = alle anzeigen):", "Filter", self._filter
        )
        if dialog.ShowModal() == wx.ID_OK:
            self._apply_filter(dialog.GetValue().strip())
        dialog.Destroy()
        self.result_list.SetFocus()

    def _apply_filter(self, text: str):
        self._filter = text
        self._render()
        if text:
            announce(self, f"Filter „{text}“: {len(self.results_data)} von {len(self._all_rows)} Treffern")
        else:
            announce(self, count_message(self._current_title, len(self.results_data)))

    # -- Aktivieren / Tastatur ----------------------------------------------

    def _on_play(self, event):
        """Enter: Titel abspielen, Container (Album/Künstler/Playlist) öffnen."""
        item = self.get_selected_item()
        if not item:
            return
        item_type = item.get("type")
        if item_type == "artist":
            self.goto_artist(item)
        elif item_type == "artist_section":
            self._open_artist_section(item)
        elif item_type == "album":
            self.goto_album(item)
        elif item_type == "playlist":
            self.goto_playlist(item)
        elif item_type == "show":
            self.goto_show(item)
        else:
            context_uri, track_uris, position = playback_args(self.results_data, item)
            start_playback(self, item, context_uri=context_uri, track_uris=track_uris, position=position)

    def _on_key_down(self, event):
        key = event.GetKeyCode()
        if event.ControlDown() and key in (ord("F"), ord("f")):
            self._prompt_filter()
            return
        # Escape hebt zuerst einen aktiven Filter auf, erst dann geht es zurück.
        if key == wx.WXK_ESCAPE and self._filter:
            self._apply_filter("")
            return
        # Rücktaste ist in Listen eigentlich für die Tippsuche belegt – darum
        # zusätzlich Alt+Pfeil links (Windows-Standard) und Escape anbieten.
        if key in (wx.WXK_BACK, wx.WXK_ESCAPE) or (key == wx.WXK_LEFT and event.AltDown()):
            self._go_back()
            return
        event.Skip()

    def _on_context_menu(self, event):
        item = self.get_selected_item()
        if not item or item.get("type") not in self.CONTEXT_TYPES:
            return
        menu = wx.Menu()
        populate_item_menu(self, menu, item)
        position = context_menu_position(self.result_list, event, self.result_list.GetFirstSelected())
        self.result_list.PopupMenu(menu, position)
        menu.Destroy()

    # -- Navigation in der Ergebnisliste -------------------------------------

    def goto_artist(self, item: dict):
        artist_id, name = get_artist_ref(item)
        if not artist_id:
            return
        title = name or "Künstler"
        # Die Künstlerübersicht braucht keinen API-Aufruf.
        self._load_into_results(f"Künstler: {title}", lambda sp: artist_overview_rows(artist_id, title))

    def _open_artist_section(self, item: dict):
        section = item["section"]
        artist_id = item["artist_id"]
        artist_name = item.get("artist_name", "")
        title = f"{artist_name} – {ARTIST_SECTION_TITLES.get(section, item.get('name', ''))}".strip(" –")
        self._load_into_results(
            title, lambda sp: load_artist_section(sp, section, artist_id, artist_name)
        )

    def goto_album(self, item: dict):
        album_id, name = get_album_ref(item)
        if not album_id:
            return
        self._load_into_results(f"Album: {name}", lambda sp: load_album_tracks(sp, album_id))

    def goto_playlist(self, item: dict):
        playlist_id = item.get("id")
        if not playlist_id:
            return
        name = item.get("name", "Playlist")
        self._load_into_results(f"Playlist: {name}", lambda sp: load_playlist_tracks(sp, playlist_id))

    def goto_show(self, item: dict):
        """Öffnet die Episoden eines Podcasts (Shows sind nicht direkt abspielbar)."""
        show_id = item.get("id") or item.get("show_id")
        if not show_id:
            return
        name = item.get("name") or item.get("show_name") or "Podcast"
        self._load_into_results(f"Podcast: {name}", lambda sp: load_show_episodes(sp, show_id, name))

    def _load_into_results(self, title: str, fetch):
        """Lädt Inhalte im Hintergrund in die Ergebnisliste (mit Verlauf für Rücktaste).

        ``fetch(sp)`` läuft vollständig im Worker-Thread und liefert fertige
        Zeilen – im Hauptthread wird nur noch angezeigt.
        """
        sp = client.get()
        if not sp:
            wx.MessageBox("Zuerst autorisieren!", "Fehler", wx.ICON_ERROR)
            return
        self._nav_stack.append(self._snapshot())
        self.btn_search.Enable(False)
        self.btn_more.Enable(False)
        announce(self, f"Lade {title} …", verbose=True)
        wx.BeginBusyCursor()
        origin = focus_origin()

        def worker():
            try:
                rows = fetch(sp)
                call_after(self._show_results, rows, title, origin)
            except Exception as e:
                call_after(self._load_failed, e)
            finally:
                call_after(wx.EndBusyCursor)
                call_after(self.btn_search.Enable, True)

        threading.Thread(target=worker, daemon=True).start()

    def _show_results(self, rows: list[dict], title: str, origin):
        # In einer geöffneten Ansicht gibt es kein „Mehr laden" – sie ist immer
        # vollständig geladen.
        self._filter = ""
        self._set_rows(rows, title)
        announce(self, count_message(title, len(rows)))
        restore_focus(self.result_list, origin)

    def _load_failed(self, error: Exception):
        if self._nav_stack:
            self._nav_stack.pop()
        announce(self, f"Fehler: {error}")
        wx.MessageBox(f"Fehler: {error}", "Fehler", wx.ICON_ERROR)

    def _snapshot(self) -> tuple[list[dict], str, int]:
        """Sichert die aktuelle Ansicht (Zeilen, Titel, markierter Eintrag)."""
        selected = self.result_list.GetFirstSelected()
        return (list(self._all_rows), self._current_title, max(0, selected))

    def _go_back(self):
        if not self._nav_stack:
            announce(self, "Keine vorherige Ansicht")
            return
        rows, title, selected = self._nav_stack.pop()
        self._filter = ""
        self._set_rows(rows, title, select=selected)
        announce(self, count_message(title, len(rows)))
        self.result_list.SetFocus()
