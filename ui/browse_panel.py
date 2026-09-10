"""
Gemeinsame Basis der Browser-Panels (Mediathek und Entdecken).

Beide Panels sind dieselbe Mechanik mit unterschiedlichem Einstieg: eine
Übersichtsliste, aus der man sich per Enter in Unterlisten bewegt, ein
Navigationsstapel für den Weg zurück und Hintergrund-Threads für alle
API-Aufrufe. Diese Basisklasse hält das an einer Stelle – so gelten die
Barrierefreiheits-Regeln (Ansagen, Listennamen, Fokus, Kontextmenü-Position)
automatisch für beide Panels.

Barrierefreiheit an dieser Stelle im Überblick:
  * Lade- und Ergebnismeldungen laufen über ``announce`` (Sprache + Braille),
    nicht nur über die Statusleiste – die liest NVDA nicht von selbst vor.
  * Die Liste bekommt den Namen der aktuellen Ansicht (``SetName``), damit NVDA
    beim Betreten „Alben" statt nur „Liste" meldet.
  * Der Fokus springt nach einem Ladevorgang nur dann in die Liste, wenn der
    Nutzer inzwischen nicht woanders hingewechselt ist.
  * Zurück geht mit Rücktaste, Alt+Pfeil links und Escape.
  * Strg+F filtert die aktuelle Liste; Escape hebt den Filter wieder auf.
"""
import threading

import wx

from spotify_client import client
from ui.browse_common import (
    ARTIST_SECTION_TITLES,
    artist_overview_rows,
    load_album_tracks,
    load_artist_section,
    load_playlist_tracks,
    load_show_episodes,
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


class BrowsePanel(wx.Panel):
    """Listen-Panel mit Navigationsstapel, Hintergrundladen und Ansagen."""

    #: Überschrift und Listenname der Einstiegsansicht.
    ROOT_TITLE = "Übersicht"
    #: Elementtypen, für die ein Kontextmenü angeboten wird.
    CONTEXT_TYPES = {"track", "episode", "album", "artist", "playlist", "show"}

    def __init__(self, parent):
        super().__init__(parent)
        # Stapeleintrag: (view_key, Titel, Zeilen, zuletzt markierter Eintrag)
        self.stack: list[tuple[str, str, list[dict], dict | None]] = []
        self.view_key = "overview"
        self.items: list[dict] = []
        # Zeilen in Original-Reihenfolge – Basis fürs Umsortieren und Filtern.
        self._raw_items: list[dict] = []
        self._filter = ""
        self._busy = False

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.heading = wx.StaticText(self, label=self.ROOT_TITLE)
        sizer.Add(self.heading, 0, wx.ALL | wx.EXPAND, 10)

        self.build_controls(sizer)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.InsertColumn(0, "Name", width=360)
        self.list.InsertColumn(1, "Details", width=320)
        # Zugänglicher Name: NVDA meldet sonst nur „Liste".
        self.list.SetName(self.ROOT_TITLE)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        sizer.Add(self.list, 1, wx.ALL | wx.EXPAND, 10)

        self.SetSizer(sizer)
        self._show_overview()

    # -- Von den Unterklassen zu füllen --------------------------------------

    def overview_rows(self) -> list[dict]:
        """Liefert die Zeilen der Einstiegsansicht."""
        raise NotImplementedError

    def activate_row(self, item: dict) -> bool:
        """Behandelt panel-eigene Zeilentypen; True, wenn zuständig."""
        return False

    def build_controls(self, sizer: wx.Sizer):
        """Hook für zusätzliche Bedienelemente über der Liste."""

    def sort_rows(self, items: list[dict]) -> list[dict]:
        """Hook für die Sortierung der angezeigten Zeilen."""
        return list(items)

    def update_controls(self):
        """Hook, um Bedienelemente an die aktuelle Ansicht anzupassen."""

    # -- Anzeige -------------------------------------------------------------

    def focus_default(self):
        self.list.SetFocus()

    def _require_client(self):
        sp = client.get()
        if not sp:
            raise RuntimeError("Zuerst autorisieren!")
        return sp

    def _set_busy(self, busy: bool):
        """Schaltet den Wartecursor (mehrfaches Ein/Aus wird abgefangen)."""
        if busy == self._busy:
            return
        self._busy = busy
        if busy:
            wx.BeginBusyCursor()
        else:
            wx.EndBusyCursor()

    def _show_overview(self):
        self.stack.clear()
        self.view_key = "overview"
        self._set_title(self.ROOT_TITLE)
        self._set_rows(self.overview_rows())

    def _set_title(self, title: str):
        """Setzt Überschrift und zugänglichen Listennamen der Ansicht."""
        self._title = title
        self.heading.SetLabel(title)
        self.list.SetName(f"{title} (Filter: {self._filter})" if self._filter else title)

    # -- Filtern -------------------------------------------------------------

    def _prompt_filter(self):
        """Fragt einen Filtertext ab und wendet ihn auf die aktuelle Liste an."""
        dialog = wx.TextEntryDialog(
            self, "Liste filtern (leer = alle anzeigen):", "Filter", self._filter
        )
        if dialog.ShowModal() == wx.ID_OK:
            self._apply_filter(dialog.GetValue().strip())
        dialog.Destroy()
        self.list.SetFocus()

    def _apply_filter(self, text: str):
        self._filter = text
        selected = self.get_selected_item()
        self._set_rows(self._raw_items, select_item=selected)
        self._set_title(self.heading.GetLabel())
        if text:
            announce(self, f"Filter „{text}“: {len(self.items)} von {len(self._raw_items)} Einträgen")
        else:
            announce(self, count_message(self.heading.GetLabel(), len(self.items)))

    def _set_rows(self, items: list[dict], select_item: dict | None = None):
        self._raw_items = list(items)
        self.items = self.sort_rows(filter_rows(self._raw_items, self._filter))
        self.update_controls()
        self.list.DeleteAllItems()
        for item in self.items:
            row = self.list.InsertItem(self.list.GetItemCount(), item.get("name", ""))
            self.list.SetItem(row, 1, item.get("details", ""))
        if not self.items:
            return
        # Beim Zurückgehen den zuvor gewählten Eintrag wieder fokussieren.
        index = 0
        if select_item is not None:
            for position, row in enumerate(self.items):
                if row is select_item:
                    index = position
                    break
        self.list.Select(index)
        self.list.Focus(index)
        self.list.EnsureVisible(index)

    def get_selected_item(self) -> dict | None:
        index = self.list.GetFirstSelected()
        if index == wx.NOT_FOUND or index >= len(self.items):
            return None
        return self.items[index]

    # -- Laden ---------------------------------------------------------------

    def _push_and_load(self, view_key: str, title: str, worker, *args):
        """Öffnet eine Unteransicht und lädt ihre Zeilen im Hintergrund."""
        self.stack.append((self.view_key, self.heading.GetLabel(), self._raw_items, self.get_selected_item()))
        self.view_key = view_key
        self._filter = ""
        self._set_title(title)
        self.list.DeleteAllItems()
        self.items = []
        self._raw_items = []
        announce(self, f"Lade {title} …")
        self._set_busy(True)
        origin = focus_origin()
        threading.Thread(target=self._run_worker, args=(worker, args, title, origin), daemon=True).start()

    def _run_worker(self, worker, args, title: str, origin):
        try:
            rows = worker(*args)
            call_after(self._apply_rows, rows, title, origin)
        except Exception as e:
            call_after(self._load_failed, e)
        finally:
            call_after(self._set_busy, False)

    def _apply_rows(self, rows: list[dict], title: str, origin):
        """Zeigt geladene Zeilen an, sagt das Ergebnis an und setzt den Fokus."""
        self._set_rows(rows)
        announce(self, count_message(title, len(rows)))
        restore_focus(self.list, origin)

    def _load_failed(self, error: Exception):
        announce(self, f"Fehler: {error}")
        self._go_back()
        wx.MessageBox(f"Fehler: {error}", "Fehler", wx.ICON_ERROR)

    def _go_back(self):
        if not self.stack:
            self._show_overview()
            return
        self.view_key, title, items, selected = self.stack.pop()
        self._filter = ""
        self._set_title(title)
        self._set_rows(items, select_item=selected)
        announce(self, count_message(title, len(items)))
        self.list.SetFocus()

    # -- Tastatur / Maus -----------------------------------------------------

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

    def _on_activate(self, event):
        index = event.GetIndex()
        if 0 <= index < len(self.items):
            self._activate_item(self.items[index])

    def _activate_item(self, item: dict):
        if self.activate_row(item):
            return
        item_type = item.get("type")
        if item_type == "playlist":
            self.goto_playlist(item)
        elif item_type == "album":
            self.goto_album(item)
        elif item_type == "artist":
            self.goto_artist(item)
        elif item_type == "show":
            self.goto_show(item)
        elif item_type == "artist_section":
            self._open_artist_section(item)
        elif item_type in {"track", "episode"}:
            self._play_item(item)

    def _play_item(self, item: dict):
        context_uri, track_uris, position = playback_args(self.items, item)
        start_playback(self, item, context_uri=context_uri, track_uris=track_uris, position=position)

    def _on_context_menu(self, event):
        item = self.get_selected_item()
        if not item or item.get("type") not in self.CONTEXT_TYPES:
            return
        menu = wx.Menu()
        populate_item_menu(self, menu, item)
        position = context_menu_position(self.list, event, self.list.GetFirstSelected())
        self.list.PopupMenu(menu, position)
        menu.Destroy()

    # -- Navigation ----------------------------------------------------------

    def goto_artist(self, item: dict):
        artist_id, name = get_artist_ref(item)
        if not artist_id:
            return
        title = name or "Künstler"
        # Die Übersicht selbst braucht keinen API-Aufruf.
        self._push_and_load("artist", title, artist_overview_rows, artist_id, title)

    def _open_artist_section(self, item: dict):
        section = item["section"]
        artist_name = item.get("artist_name", "")
        title = f"{artist_name} – {ARTIST_SECTION_TITLES.get(section, item.get('name', ''))}".strip(" –")
        self._push_and_load(
            "artist_section", title, self._load_artist_section,
            section, item["artist_id"], artist_name,
        )

    def _load_artist_section(self, section: str, artist_id: str, artist_name: str):
        return load_artist_section(self._require_client(), section, artist_id, artist_name)

    def goto_album(self, item: dict):
        album_id, name = get_album_ref(item)
        if album_id:
            self._push_and_load("album_tracks", name or "Album", self._load_album_tracks, album_id)

    def _load_album_tracks(self, album_id: str):
        return load_album_tracks(self._require_client(), album_id)

    def goto_playlist(self, item: dict):
        playlist_id = item.get("id")
        if playlist_id:
            self._push_and_load(
                "playlist_tracks", item.get("name", "Playlist"), self._load_playlist_tracks, playlist_id
            )

    def _load_playlist_tracks(self, playlist_id: str):
        return load_playlist_tracks(self._require_client(), playlist_id)

    def goto_show(self, item: dict):
        """Öffnet die Episoden eines Podcasts (Shows sind nicht direkt abspielbar)."""
        show_id = item.get("id") or item.get("show_id")
        if show_id:
            name = item.get("name") or item.get("show_name") or "Podcast"
            self._push_and_load("show_episodes", name, self._load_show_episodes, show_id, name)

    def _load_show_episodes(self, show_id: str, show_name: str):
        return load_show_episodes(self._require_client(), show_id, show_name)
