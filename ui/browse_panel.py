# SpotiFlix – ein barrierefreier Spotify-Player für Windows.
# Copyright (C) 2026 Felix Steindorff
#
# Dieses Programm ist freie Software: Sie können es unter den Bedingungen
# der GNU General Public License, Version 3 oder (nach Ihrer Wahl) einer
# neueren Version, weitergeben und/oder verändern. Es wird ohne jede
# Gewährleistung bereitgestellt; siehe LICENSE für den vollen Text.

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
  * Mehrere Einträge lassen sich markieren; alle Aktionen wirken dann auf die
    ganze Auswahl.

``LOCAL_SHORTCUTS`` beschreibt die Tasten, die dieses Panel selbst behandelt –
die Kürzelübersicht (F1) liest das aus, damit sie ohne Pflege aktuell bleibt.
"""
import threading

import wx

import applog
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
from ui.list_io import export_rows
from ui.panel_helpers import (
    SORT_MODES,
    announce,
    call_after,
    context_menu_position,
    count_message,
    filter_rows,
    focus_origin,
    playback_args,
    restore_focus,
    select_only,
    selected_rows,
    short_error,
    sort_rows,
    start_playback,
)
from ui.playlist_edit import edit_details, move_track, playlist_id_for, remove_tracks

from i18n import N_, _


class BrowsePanel(wx.Panel):
    """Listen-Panel mit Navigationsstapel, Hintergrundladen und Ansagen."""

    #: Überschrift und Listenname der Einstiegsansicht.
    ROOT_TITLE = N_("Übersicht")
    #: Elementtypen, für die ein Kontextmenü angeboten wird.
    CONTEXT_TYPES = {"track", "episode", "album", "artist", "playlist", "show"}
    #: Tasten, die dieses Panel selbst behandelt (für die Kürzelübersicht).
    LOCAL_SHORTCUTS = [
        (N_("Eingabe"), N_("Eintrag öffnen bzw. abspielen")),
        (N_("Rücktaste, Alt+Pfeil links, Esc"), N_("Eine Ebene zurück")),
        (N_("Strg+F"), N_("Liste filtern")),
        (N_("Esc"), N_("Filter aufheben")),
        (N_("F5"), N_("Ansicht neu laden")),
        (N_("Strg+A"), N_("Alles markieren")),
        (N_("Umschalt+Pfeiltasten"), N_("Mehrere Einträge markieren")),
        (N_("Anwendungstaste, Umschalt+F10"), N_("Kontextmenü zum markierten Eintrag")),
        (N_("Entf"), N_("Markierte Titel aus der geöffneten Playlist entfernen")),
        (N_("Strg+Pfeil hoch/runter"), N_("Titel in der geöffneten Playlist verschieben")),
        (N_("F2"), N_("Playlist umbenennen und Beschreibung bearbeiten")),
        (N_("Strg+E"), N_("Angezeigte Liste exportieren")),
    ]

    def __init__(self, parent):
        super().__init__(parent)
        # Stapeleintrag: (view_key, Titel, Zeilen, zuletzt markierter Eintrag)
        self.stack: list[tuple[str, str, list[dict], dict | None]] = []
        self.view_key = "overview"
        self.items: list[dict] = []
        # Zeilen in Original-Reihenfolge – Basis fürs Umsortieren und Filtern.
        self._raw_items: list[dict] = []
        self._filter = ""
        self.sort_mode = "default"
        self._busy = False
        # Merkt den letzten Ladevorgang, damit F5 ihn wiederholen kann.
        self._current_load: tuple | None = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.heading = wx.StaticText(self, label=self.ROOT_TITLE)
        sizer.Add(self.heading, 0, wx.ALL | wx.EXPAND, 10)

        self._build_sort_control(sizer)
        self.build_controls(sizer)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.list.InsertColumn(0, _("Name"), width=360)
        self.list.InsertColumn(1, _("Details"), width=320)
        # Zugänglicher Name: NVDA meldet sonst nur „Liste".
        self.list.SetName(_(self.ROOT_TITLE))
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

    def update_controls(self):
        """Hook, um Bedienelemente an die aktuelle Ansicht anzupassen."""

    # -- Sortierung ----------------------------------------------------------

    def _build_sort_control(self, sizer: wx.Sizer):
        box = wx.BoxSizer(wx.HORIZONTAL)
        box.Add(wx.StaticText(self, label=_("Sortierung:")), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.sort_choice = wx.Choice(self, choices=[_(label) for _key, label in SORT_MODES])
        self.sort_choice.SetName(_("Sortierung"))
        self.sort_choice.SetSelection(0)
        self.sort_choice.Bind(wx.EVT_CHOICE, self._on_sort_choice)
        box.Add(self.sort_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

    def _on_sort_choice(self, event):
        self.sort_mode, label = SORT_MODES[self.sort_choice.GetSelection()]
        label = _(label)
        selected = self.get_selected_item()
        # Der Fokus bleibt bewusst auf der Auswahl – sonst würde NVDA mitten in
        # der Auswahl auf die Liste umschalten.
        self._set_rows(self._raw_items, select_item=selected)
        announce(self, _("Sortierung: {label}").format(label=label))

    def sort_rows(self, items: list[dict]) -> list[dict]:
        """Sortiert die Zeilen; in der Übersicht bleibt die Reihenfolge fest."""
        if self.view_key == "overview":
            return list(items)
        return sort_rows(items, self.sort_mode)

    # -- Anzeige -------------------------------------------------------------

    def focus_default(self):
        self.list.SetFocus()

    def _require_client(self):
        sp = client.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
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
        self._current_load = None
        self._filter = ""
        self._set_title(_(self.ROOT_TITLE))
        self._set_rows(self.overview_rows())

    def _set_title(self, title: str):
        """Setzt Überschrift und zugänglichen Listennamen der Ansicht."""
        self.heading.SetLabel(title)
        self.list.SetName(f"{title} (Filter: {self._filter})" if self._filter else title)

    def _set_rows(self, items: list[dict], select_item: dict | None = None, select_index: int | None = None):
        self._raw_items = list(items)
        self.items = self.sort_rows(filter_rows(self._raw_items, self._filter))
        self.update_controls()
        self.list.DeleteAllItems()
        for item in self.items:
            row = self.list.InsertItem(self.list.GetItemCount(), item.get("name", ""))
            self.list.SetItem(row, 1, item.get("details", ""))
        if not self.items:
            return
        # Beim Zurückgehen bzw. Neuladen den zuvor gewählten Eintrag wieder
        # fokussieren.
        index = 0
        if select_item is not None:
            for position, row in enumerate(self.items):
                if row is select_item:
                    index = position
                    break
        elif select_index is not None:
            index = max(0, min(select_index, len(self.items) - 1))
        select_only(self.list, index)

    def get_selected_item(self) -> dict | None:
        index = self.list.GetFirstSelected()
        if index == wx.NOT_FOUND or index >= len(self.items):
            return None
        return self.items[index]

    def get_selected_items(self) -> list[dict]:
        """Alle markierten Einträge – Grundlage für Aktionen auf mehreren."""
        return selected_rows(self.list, self.items)

    # -- Laden ---------------------------------------------------------------

    def _push_and_load(self, view_key: str, title: str, worker, *args):
        """Öffnet eine Unteransicht und lädt ihre Zeilen im Hintergrund."""
        self.stack.append((self.view_key, self.heading.GetLabel(), self._raw_items, self.get_selected_item()))
        self.view_key = view_key
        self._filter = ""
        self._set_title(title)
        self._start_load(title, worker, args)

    def _start_load(self, title: str, worker, args, select_index: int | None = None):
        self._current_load = (self.view_key, title, worker, args)
        self.list.DeleteAllItems()
        self.items = []
        self._raw_items = []
        announce(self, _("Lade {title} …").format(title=title), verbose=True)
        self._set_busy(True)
        origin = focus_origin()
        threading.Thread(
            target=self._run_worker, args=(worker, args, title, origin, select_index), daemon=True
        ).start()

    def _reload_current(self):
        """Lädt die aktuelle Ansicht neu (F5) und behält die Position."""
        if not self._current_load:
            announce(self, _("Diese Ansicht lässt sich nicht neu laden."))
            return
        _view_key, title, worker, args = self._current_load
        index = self.list.GetFirstSelected()
        self._start_load(title, worker, args, select_index=max(0, index))

    def _run_worker(self, worker, args, title: str, origin, select_index=None):
        try:
            rows = worker(*args)
            call_after(self._apply_rows, rows, title, origin, select_index)
        except Exception as e:
            call_after(self._load_failed, e)
        finally:
            call_after(self._set_busy, False)

    def _apply_rows(self, rows: list[dict], title: str, origin, select_index=None):
        """Zeigt geladene Zeilen an, sagt das Ergebnis an und setzt den Fokus."""
        self._set_rows(rows, select_index=select_index)
        announce(self, count_message(title, len(rows)))
        restore_focus(self.list, origin)

    def _load_failed(self, error: Exception):
        applog.error("Laden", error)
        announce(self, _("Fehler: {error}").format(error=short_error(error)))
        self._go_back()
        wx.MessageBox(_("Fehler: {error}").format(error=error), _("Fehler"), wx.ICON_ERROR)

    def _go_back(self):
        if not self.stack:
            self._show_overview()
            return
        self.view_key, title, items, selected = self.stack.pop()
        self._filter = ""
        self._current_load = None
        self._set_title(title)
        self._set_rows(items, select_item=selected)
        announce(self, count_message(title, len(items)))
        self.list.SetFocus()

    # -- Filtern -------------------------------------------------------------

    def _prompt_filter(self):
        """Fragt einen Filtertext ab und wendet ihn auf die aktuelle Liste an."""
        dialog = wx.TextEntryDialog(
            self, _("Liste filtern (leer = alle anzeigen):"), _("Filter"), self._filter
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
            announce(self, _("Filter „{text}“: {count} von {count2} Einträgen").format(text=text, count=len(self.items), count2=len(self._raw_items)))
        else:
            announce(self, count_message(self.heading.GetLabel(), len(self.items)))

    # -- Playlist bearbeiten -------------------------------------------------

    def _playlist_id(self) -> str | None:
        """Liefert die Playlist der aktuellen Ansicht (sonst None)."""
        return playlist_id_for(self.items)

    def _remove_from_playlist(self):
        playlist_id = self._playlist_id()
        if not playlist_id:
            announce(self, _("Diese Ansicht ist keine bearbeitbare Playlist."))
            return
        remove_tracks(self, playlist_id, self.get_selected_items(), on_done=self._reload_current)

    def _move_in_playlist(self, direction: int):
        playlist_id = self._playlist_id()
        if not playlist_id:
            announce(self, _("Diese Ansicht ist keine bearbeitbare Playlist."))
            return
        item = self.get_selected_item()
        if item:
            move_track(self, playlist_id, item, direction, on_done=self._reload_current)

    def _edit_playlist(self):
        playlist_id = self._playlist_id()
        if not playlist_id:
            announce(self, _("Diese Ansicht ist keine bearbeitbare Playlist."))
            return
        edit_details(self, playlist_id, on_done=self._reload_current)

    def _export_view(self):
        export_rows(self, self.items, self.heading.GetLabel())

    # -- Tastatur / Maus -----------------------------------------------------

    def _on_key_down(self, event):
        key = event.GetKeyCode()
        control = event.ControlDown()
        if control and key in (ord("F"), ord("f")):
            self._prompt_filter()
            return
        if control and key in (ord("A"), ord("a")):
            self._select_all()
            return
        if control and key in (ord("E"), ord("e")):
            self._export_view()
            return
        if key == wx.WXK_F5:
            self._reload_current()
            return
        if key == wx.WXK_F2:
            self._edit_playlist()
            return
        if key == wx.WXK_DELETE:
            self._remove_from_playlist()
            return
        if control and key in (wx.WXK_UP, wx.WXK_DOWN):
            self._move_in_playlist(-1 if key == wx.WXK_UP else 1)
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

    def _select_all(self):
        for index in range(self.list.GetItemCount()):
            self.list.Select(index)
        announce(self, _("{count} Einträge markiert").format(
            count=self.list.GetSelectedItemCount()))

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
        items = self.get_selected_items()
        if not items:
            return
        types = {item.get("type") for item in items}
        if not types & self.CONTEXT_TYPES:
            return
        menu = wx.Menu()
        populate_item_menu(self, menu, items)
        position = context_menu_position(self.list, event, self.list.GetFirstSelected())
        self.list.PopupMenu(menu, position)
        menu.Destroy()

    # -- Navigation ----------------------------------------------------------

    def goto_artist(self, item: dict):
        artist_id, name = get_artist_ref(item)
        if not artist_id:
            return
        title = name or _("Künstler")
        # Die Übersicht selbst braucht keinen API-Aufruf.
        self._push_and_load("artist", title, artist_overview_rows, artist_id, title)

    def _open_artist_section(self, item: dict):
        section = item["section"]
        artist_name = item.get("artist_name", "")
        section_title = _(ARTIST_SECTION_TITLES.get(section, item.get("name", "")))
        title = f"{artist_name} – {section_title}".strip(" –")
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
