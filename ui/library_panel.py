"""
Mediathek-Panel mit tastaturfreundlicher Listen-Navigation.

Navigation, Ansagen und Kontextmenü stecken in ``BrowsePanel`` – hier stehen nur
die Einstiegskategorien, die zugehörigen Ladefunktionen und die Sortierung.
"""
import wx

from ui.browse_common import album_row, artist_row, playlist_row, track_row
from ui.browse_panel import BrowsePanel
from ui.panel_helpers import announce, collect_page_items


class LibraryPanel(BrowsePanel):
    """Zeigt Playlists, Künstler, Alben und Titel als navigierbare Listen."""

    ROOT_TITLE = "Mediathek"

    CATEGORIES = [
        ("playlists", "Playlists", "Ihre gespeicherten und abonnierten Playlists"),
        ("artists", "Künstler", "Von Ihnen gefolgte Künstler"),
        ("albums", "Alben", "Gespeicherte Alben"),
        ("tracks", "Titel", "Gespeicherte Titel"),
    ]

    # Sortiermodi für die Listenansichten.
    SORT_CHOICES = [
        ("added", "Hinzugefügt (Datum)"),
        ("alpha", "Alphabetisch (A–Z)"),
    ]

    def __init__(self, parent):
        self.sort_mode = "added"
        super().__init__(parent)

    def build_controls(self, sizer):
        sort_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sort_sizer.Add(
            wx.StaticText(self, label="Sortierung:"), 0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8,
        )
        self.sort_choice = wx.Choice(self, choices=[label for _, label in self.SORT_CHOICES])
        self.sort_choice.SetName("Sortierung")
        self.sort_choice.SetSelection(0)
        self.sort_choice.Bind(wx.EVT_CHOICE, self._on_sort_choice)
        sort_sizer.Add(self.sort_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(sort_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

    # -- Übersicht und Sortierung -------------------------------------------

    def overview_rows(self) -> list[dict]:
        return [
            {"type": "category", "category": key, "name": name, "details": details}
            for key, name, details in self.CATEGORIES
        ]

    def sort_rows(self, items: list[dict]) -> list[dict]:
        """Wendet den gewählten Sortiermodus an (Datum = API-Reihenfolge)."""
        if self.view_key == "overview" or self.sort_mode != "alpha":
            return list(items)
        return sorted(items, key=lambda item: item.get("name", "").casefold())

    def update_controls(self):
        # In der Übersicht ist die Reihenfolge fest – Sortierung nur in Listen.
        self.sort_choice.Enable(self.view_key != "overview")

    def _on_sort_choice(self, event):
        index = self.sort_choice.GetSelection()
        self.sort_mode, label = self.SORT_CHOICES[index]
        # Fokus bleibt bewusst auf der Auswahl – sonst würde NVDA mitten in der
        # Auswahl auf die Liste umschalten.
        self._set_rows(self._raw_items)
        announce(self, f"Sortierung: {label}")

    # -- Kategorien laden ----------------------------------------------------

    def activate_row(self, item: dict) -> bool:
        if item.get("type") != "category":
            return False
        loaders = {
            "playlists": ("Playlists", self._load_playlists),
            "artists": ("Künstler", self._load_artists),
            "albums": ("Alben", self._load_albums),
            "tracks": ("Titel", self._load_tracks),
        }
        category = item["category"]
        title, worker = loaders[category]
        self._push_and_load(category, title, worker)
        return True

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
