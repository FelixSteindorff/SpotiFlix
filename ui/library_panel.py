# SpotiFlix – ein barrierefreier Spotify-Player für Windows.
# Copyright (C) 2026 Felix Steindorff
#
# Dieses Programm ist freie Software: Sie können es unter den Bedingungen
# der GNU General Public License, Version 3 oder (nach Ihrer Wahl) einer
# neueren Version, weitergeben und/oder verändern. Es wird ohne jede
# Gewährleistung bereitgestellt; siehe LICENSE für den vollen Text.

"""
Mediathek-Panel mit tastaturfreundlicher Listen-Navigation.

Navigation, Sortierung, Filter, Ansagen und Kontextmenü stecken in
``BrowsePanel`` – hier stehen nur die Einstiegskategorien und ihre
Ladefunktionen.
"""
from ui.browse_common import album_row, artist_row, playlist_row, track_row
from ui.browse_panel import BrowsePanel
from i18n import N_, _
from ui.panel_helpers import collect_page_items


class LibraryPanel(BrowsePanel):
    """Zeigt Playlists, Künstler, Alben und Titel als navigierbare Listen."""

    ROOT_TITLE = N_("Mediathek")

    CATEGORIES = [
        ("playlists", N_("Playlists"), N_("Ihre gespeicherten und abonnierten Playlists")),
        ("artists", N_("Künstler"), N_("Von Ihnen gefolgte Künstler")),
        ("albums", N_("Alben"), N_("Gespeicherte Alben")),
        ("tracks", N_("Titel"), N_("Gespeicherte Titel")),
    ]

    def overview_rows(self) -> list[dict]:
        return [
            {"type": "category", "category": key, "name": _(name), "details": _(details)}
            for key, name, details in self.CATEGORIES
        ]

    def activate_row(self, item: dict) -> bool:
        if item.get("type") != "category":
            return False
        loaders = {
            "playlists": self._load_playlists,
            "artists": self._load_artists,
            "albums": self._load_albums,
            "tracks": self._load_tracks,
        }
        category = item["category"]
        # Der Titel der Unteransicht ist der Name der Kategoriezeile.
        title, worker = item.get("name", category), loaders[category]
        self._push_and_load(category, title, worker)
        return True

    def update_controls(self):
        # In der Übersicht ist die Reihenfolge fest – Sortierung nur in Listen.
        self.sort_choice.Enable(self.view_key != "overview")

    def _load_playlists(self):
        sp = self._require_client()
        results = sp.current_user_playlists(limit=50)
        return [playlist_row(item) for item in collect_page_items(sp, results) if item]

    def _load_artists(self):
        sp = self._require_client()
        results = sp.current_user_followed_artists(limit=50)
        artists = collect_page_items(sp, (results or {}).get("artists"))
        return [artist_row(item) for item in artists if item]

    def _load_albums(self):
        sp = self._require_client()
        results = sp.current_user_saved_albums(limit=50)
        return [album_row(item["album"]) for item in collect_page_items(sp, results) if item and item.get("album")]

    def _load_tracks(self):
        sp = self._require_client()
        results = sp.current_user_saved_tracks(limit=50)
        return [track_row(item["track"]) for item in collect_page_items(sp, results) if item and item.get("track")]
