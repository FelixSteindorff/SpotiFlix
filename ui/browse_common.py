"""
Gemeinsame Datenbausteine für die Browser-Panels (Mediathek, Suche, Entdecken).

Stellt einheitliche Zeilen-Builder (Titel/Album/Künstler/Playlist) sowie die
Lade-Funktionen für Künstler-, Album- und Playlist-Inhalte bereit – damit alle
Panels Inhalte identisch anzeigen und navigieren.

Die Künstleransicht ist als Übersicht mit eigenen Unterlisten aufgebaut:
Beliebte Titel, Alben, Singles & EPs und passende Playlists – jeweils zum
Durchgehen mit den Pfeiltasten.

Podcasts (Shows) werden genauso behandelt: Ein Podcast öffnet seine Episoden,
denn die Web API kann eine Show nicht als ``context_uri`` abspielen.
"""
from ui.panel_helpers import collect_page_items


def section_items(results: dict | None, key: str) -> list:
    """Holt ``results[key]["items"]`` – auch wenn Spotify ``null`` liefert.

    Spotify lässt einzelne Abschnitte einer Suchantwort gelegentlich als
    ``null`` stehen, statt sie wegzulassen; ``results.get(key, {})`` liefert
    dann None und der nächste ``.get`` wirft einen AttributeError.
    """
    section = (results or {}).get(key) or {}
    return section.get("items") or []


def format_duration(duration_ms: int | None) -> str:
    """Formatiert eine Spieldauer als m:ss (leer, wenn unbekannt)."""
    duration_ms = duration_ms or 0
    if not duration_ms:
        return ""
    return f"{duration_ms // 60000}:{(duration_ms % 60000) // 1000:02d}"


def track_row(track: dict, context_uri: str | None = None) -> dict:
    """Baut eine einheitliche Titel-/Episodenzeile."""
    artist_list = track.get("artists", []) or []
    artists = ", ".join(a.get("name", "") for a in artist_list)
    album_obj = track.get("album", {}) or {}
    album = album_obj.get("name", "")
    first_artist = artist_list[0] if artist_list else {}
    duration = format_duration(track.get("duration_ms"))
    row = {
        "type": track.get("type", "track"),
        "id": track.get("id"),
        "uri": track.get("uri"),
        "external_urls": track.get("external_urls"),
        "name": track.get("name", ""),
        "details": " - ".join(part for part in [artists, album, duration] if part),
        "artist_id": first_artist.get("id"),
        "artist_name": first_artist.get("name", ""),
        "album_id": album_obj.get("id"),
        "album_name": album,
        # Für die Sortierung nach Dauer bzw. Datum.
        "duration_ms": track.get("duration_ms") or 0,
        "sort_date": album_obj.get("release_date", ""),
    }
    if context_uri:
        row["context_uri"] = context_uri
    return row


def album_row(album: dict) -> dict:
    """Baut eine einheitliche Albumzeile."""
    artist_list = album.get("artists", []) or []
    artists = ", ".join(a.get("name", "") for a in artist_list)
    first_artist = artist_list[0] if artist_list else {}
    year = album.get("release_date", "")
    return {
        "type": "album",
        "id": album.get("id"),
        "uri": album.get("uri"),
        "external_urls": album.get("external_urls"),
        "name": album.get("name", ""),
        "details": " - ".join(part for part in [artists, year] if part),
        "sort_date": year,
        "artist_id": first_artist.get("id"),
        "artist_name": first_artist.get("name", ""),
    }


def artist_row(artist: dict) -> dict:
    """Baut eine einheitliche Künstlerzeile."""
    return {
        "type": "artist",
        "id": artist.get("id"),
        "uri": artist.get("uri"),
        "external_urls": artist.get("external_urls"),
        "name": artist.get("name", ""),
        "details": ", ".join(artist.get("genres", [])[:3]),
    }


def playlist_row(playlist: dict) -> dict:
    """Baut eine einheitliche Playlistzeile."""
    owner = playlist.get("owner") or {}
    return {
        "type": "playlist",
        "id": playlist.get("id"),
        "uri": playlist.get("uri"),
        "external_urls": playlist.get("external_urls"),
        "name": playlist.get("name", ""),
        "details": owner.get("display_name", ""),
        "owner_id": owner.get("id", ""),
        "collaborative": bool(playlist.get("collaborative")),
    }


def show_row(show: dict) -> dict:
    """Baut eine einheitliche Podcast-(Show-)Zeile."""
    return {
        "type": "show",
        "id": show.get("id"),
        "uri": show.get("uri"),
        "external_urls": show.get("external_urls"),
        "name": show.get("name", ""),
        "details": show.get("publisher", ""),
        "show_name": show.get("name", ""),
    }


def episode_row(episode: dict, show_name: str = "") -> dict:
    """Baut eine einheitliche Episodenzeile – inklusive Hörfortschritt.

    Spotify liefert zu jeder Episode einen ``resume_point``. Daraus wird
    einerseits die Anzeige („gehört", „weiter ab 12:30") und andererseits
    ``resume_ms`` für die Wiedergabe an genau dieser Stelle.
    """
    show = episode.get("show") or {}
    name_of_show = show_name or show.get("name", "")
    resume = episode.get("resume_point") or {}
    resume_ms = int(resume.get("resume_position_ms") or 0)
    fully_played = bool(resume.get("fully_played"))
    if fully_played:
        progress = "gehört"
        resume_ms = 0
    elif resume_ms > 0:
        progress = f"weiter ab {format_duration(resume_ms)}"
    else:
        progress = ""
    parts = [
        name_of_show,
        episode.get("release_date", ""),
        format_duration(episode.get("duration_ms")),
        progress,
    ]
    return {
        "type": "episode",
        "id": episode.get("id"),
        "uri": episode.get("uri"),
        "external_urls": episode.get("external_urls"),
        "name": episode.get("name", ""),
        "details": " - ".join(part for part in parts if part),
        "show_id": show.get("id"),
        "show_name": name_of_show,
        "resume_ms": resume_ms,
        "duration_ms": episode.get("duration_ms") or 0,
        "sort_date": episode.get("release_date", ""),
    }


def load_show_episodes(sp, show_id: str, show_name: str = "") -> list[dict]:
    """Lädt die Episoden eines Podcasts (neueste zuerst, wie bei Spotify)."""
    results = sp.show_episodes(show_id, limit=50)
    return [
        episode_row(item, show_name)
        for item in collect_page_items(sp, results)
        if item
    ]


# Titel der Künstler-Unterlisten (für die Überschrift der geöffneten Ansicht).
ARTIST_SECTION_TITLES = {
    "top_tracks": "Beliebte Titel",
    "albums": "Alben",
    "singles": "Singles & EPs",
    "playlists": "Playlists",
}


def artist_overview_rows(artist_id: str, name: str) -> list[dict]:
    """Liefert die Übersichtszeilen einer Künstlerseite (eigene Unterlisten)."""
    return [
        {
            "type": "artist_section",
            "section": "top_tracks",
            "artist_id": artist_id,
            "artist_name": name,
            "name": "Beliebte Titel",
            "details": "Die meistgehörten Titel",
        },
        {
            "type": "artist_section",
            "section": "albums",
            "artist_id": artist_id,
            "artist_name": name,
            "name": "Alben",
            "details": "Alle Alben",
        },
        {
            "type": "artist_section",
            "section": "singles",
            "artist_id": artist_id,
            "artist_name": name,
            "name": "Singles & EPs",
            "details": "Singles und EPs",
        },
        {
            "type": "artist_section",
            "section": "playlists",
            "artist_id": artist_id,
            "artist_name": name,
            "name": "Playlists",
            "details": "Passende Playlists",
        },
    ]


def load_artist_section(sp, section: str, artist_id: str, artist_name: str) -> list[dict]:
    """Lädt die Inhalte einer Künstler-Unterliste."""
    if section == "top_tracks":
        tracks = sp.artist_top_tracks(artist_id).get("tracks", [])
        return [track_row(track) for track in tracks if track]
    if section == "albums":
        results = sp.artist_albums(artist_id, album_type="album", limit=50)
        return [album_row(item) for item in collect_page_items(sp, results) if item]
    if section == "singles":
        results = sp.artist_albums(artist_id, album_type="single", limit=50)
        return [album_row(item) for item in collect_page_items(sp, results) if item]
    if section == "playlists":
        # Spotify bietet keine direkte „Playlists eines Künstlers"-API – darum
        # über die Suche nach dem Künstlernamen passende Playlists holen.
        results = sp.search(q=artist_name, type="playlist", limit=30)
        return [playlist_row(item) for item in section_items(results, "playlists") if item]
    return []


def load_album_tracks(sp, album_id: str) -> list[dict]:
    """Lädt die Titel eines Albums (mit Album-Kontext für Autoplay)."""
    album = sp.album(album_id)
    context_uri = f"spotify:album:{album_id}"
    rows = []
    for item in collect_page_items(sp, album.get("tracks")):
        track = dict(item)
        track["album"] = {"id": album_id, "name": album.get("name", "")}
        rows.append(track_row(track, context_uri=context_uri))
    return rows


def load_playlist_tracks(sp, playlist_id: str) -> list[dict]:
    """Lädt die Titel einer Playlist (mit Playlist-Kontext für Autoplay)."""
    results = sp.playlist_items(
        playlist_id,
        fields="next,items(track(id,name,artists(id,name),album(id,name),duration_ms,uri,external_urls,type))",
        limit=100,
    )
    context_uri = f"spotify:playlist:{playlist_id}"
    rows = []
    # Die Position ist die Nummer in der Playlist – sie bleibt auch dann
    # richtig, wenn die Anzeige gefiltert oder umsortiert wird.
    for position, item in enumerate(collect_page_items(sp, results)):
        track = (item or {}).get("track")
        if not track:
            continue
        row = track_row(track, context_uri=context_uri)
        row["playlist_position"] = position
        rows.append(row)
    return rows
