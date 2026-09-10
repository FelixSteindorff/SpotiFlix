"""
Entdecken-Panel für neue Inhalte.

Navigation, Ansagen und Kontextmenü stecken in ``BrowsePanel`` – hier stehen nur
die Einstiegsabschnitte und ihre Ladefunktionen.
"""
from spotify_client import client
from i18n import N_, _
from ui.browse_common import album_row, artist_row, track_row
from ui.browse_panel import BrowsePanel
from ui.panel_helpers import collect_page_items


class DiscoverPanel(BrowsePanel):
    """Bietet stabile Einstiegspunkte für neue und persönliche Inhalte."""

    ROOT_TITLE = N_("Entdecken")

    SECTIONS = [
        ("new_releases", N_("Neue Alben"), N_("Aktuelle Neuerscheinungen")),
        ("top_artists", N_("Ihre Top-Künstler"), N_("Künstler passend zu Ihrem Hörverlauf")),
        ("top_tracks", N_("Ihre Top-Titel"), N_("Titel passend zu Ihrem Hörverlauf")),
        ("top_artist_releases", N_("Neues von Top-Künstlern"), N_("Aktuelle Alben und Singles Ihrer Top-Künstler")),
        ("recent", N_("Zuletzt gehört"), N_("Ihre zuletzt gespielten Titel")),
    ]

    def overview_rows(self) -> list[dict]:
        return [
            {"type": "section", "section": key, "name": _(name), "details": _(details)}
            for key, name, details in self.SECTIONS
        ]

    def activate_row(self, item: dict) -> bool:
        if item.get("type") != "section":
            return False
        loaders = {
            "new_releases": self._load_new_releases,
            "top_artists": self._load_top_artists,
            "top_tracks": self._load_top_tracks,
            "top_artist_releases": self._load_top_artist_releases,
            "recent": self._load_recently_played,
        }
        section = item["section"]
        # Der Titel der Unteransicht ist der Name der Abschnittszeile.
        title, worker = item.get("name", section), loaders[section]
        self._push_and_load(section, title, worker)
        return True

    def _load_new_releases(self):
        sp = self._require_client()
        results = sp.new_releases(limit=50)
        return [album_row(item) for item in collect_page_items(sp, (results or {}).get("albums")) if item]

    def _load_top_artists(self):
        sp = self._require_client()
        results = sp.current_user_top_artists(limit=50, time_range="medium_term")
        return [artist_row(item) for item in collect_page_items(sp, results) if item]

    def _load_top_tracks(self):
        sp = self._require_client()
        results = sp.current_user_top_tracks(limit=50, time_range="medium_term")
        return [track_row(item) for item in collect_page_items(sp, results) if item]

    def _load_recently_played(self):
        self._require_client()
        return [track_row(track) for track in client.recently_played(limit=50)]

    def _load_top_artist_releases(self):
        sp = self._require_client()
        top_artists = collect_page_items(
            sp,
            sp.current_user_top_artists(limit=20, time_range="medium_term"),
        )
        rows = []
        seen = set()
        for artist in top_artists[:12]:
            if not artist or not artist.get("id"):
                continue
            albums = collect_page_items(
                sp,
                sp.artist_albums(
                    artist["id"],
                    album_type="album,single",
                    limit=20,
                ),
            )
            for album in albums:
                album_id = (album or {}).get("id")
                if not album_id or album_id in seen:
                    continue
                seen.add(album_id)
                rows.append(album_row(album))
        rows.sort(key=lambda item: item.get("sort_date", ""), reverse=True)
        return rows
