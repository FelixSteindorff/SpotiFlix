"""
Echter Spotify-Stream-Download über librespot-python (Zusatzoption zu spotdl).

Lädt den nativen OGG-Vorbis-Stream direkt von Spotify herunter, statt das Audio
über YouTube zu beziehen. Voraussetzungen:
  * pip install librespot
  * Spotify Premium für hohe Qualität (320 kbit/s); Free-Konten erhalten max. 160.

Das Login erfolgt einmalig über einen OAuth-Browser-Flow von librespot selbst
(getrennt vom spotipy-Token) und wird in einer Credentials-Datei gespeichert.
Die Auflösung von Alben/Playlists/Künstlern in einzelne Titel nutzt den
vorhandenen spotipy-Client.
"""
import os
import re
import shutil
import subprocess
import threading
import webbrowser
from collections import OrderedDict

import config as cfg

# librespot-python liefert vorgenerierte Protobuf-Dateien (_pb2.py) aus einer
# alten protoc-Version. Ab protobuf 4 verweigert die C++-Implementierung deren
# Laden ("Descriptors cannot be created directly"), und der Download bricht mit
# einer für Nutzer unverständlichen Meldung ab. Die reine Python-Implementierung
# lädt sie weiterhin – sie ist langsamer, aber für Metadaten völlig ausreichend.
# Das muss gesetzt sein, *bevor* google.protobuf zum ersten Mal importiert wird;
# librespot wird darum überall erst innerhalb der Funktionen importiert.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

# Unter Windows verhindert CREATE_NO_WINDOW das Aufblitzen eines Konsolen-
# fensters je ffmpeg-Aufruf (ein Aufruf pro Titel) – das stiehlt sonst den
# Fokus und wird von NVDA mitgelesen.
NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

# Windows bricht bei Pfaden über 260 Zeichen mit OSError ab. Etwas Reserve für
# Endung und temporäre Dateien (".spotiflix.tmp.ogg") einplanen.
MAX_PATH_LENGTH = 240

CREDENTIALS_FILE = os.path.join(os.path.expanduser("~"), ".spotiflix-librespot-creds.json")

# Dateiendung je Zielformat.
_FORMAT_EXTENSIONS = {"ogg": ".ogg", "mp3": ".mp3", "m4a": ".m4a"}

# Bitrate aus den Einstellungen → librespot-AudioQuality-Stufe.
_QUALITY_LEVELS = {
    "96": "NORMAL",
    "160": "HIGH",
    "320": "VERY_HIGH",
}

_session = None
_session_lock = threading.Lock()


def _require_librespot():
    """Importiert librespot oder wirft eine verständliche Fehlermeldung."""
    try:
        from librespot.core import Session  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Die Bibliothek 'librespot' ist nicht installiert.\n"
            "Installieren Sie sie mit: pip install librespot\n\n"
            "Oder wählen Sie in den Einstellungen die Download-Methode "
            "'YouTube-Quelle (spotdl)'."
        )
    except TypeError as error:
        # Tritt auf, wenn google.protobuf schon vor dieser Datei importiert
        # wurde und darum noch mit der C++-Implementierung läuft.
        if "Descriptors cannot" not in str(error):
            raise
        raise RuntimeError(
            "Die librespot-Bibliothek passt nicht zur installierten "
            "protobuf-Version.\n\n"
            "Setzen Sie die Umgebungsvariable "
            "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python, bevor Sie SpotiFlix "
            "starten, oder installieren Sie protobuf 3.20:\n"
            "  pip install \"protobuf<4\"\n\n"
            "Alternativ in den Einstellungen die Download-Methode "
            "'YouTube-Quelle (spotdl)' wählen."
        )


def _get_session():
    """Liefert eine angemeldete librespot-Session (lazy, threadsicher)."""
    global _session
    with _session_lock:
        if _session is not None:
            return _session

        _require_librespot()
        from librespot.core import Session

        conf = (
            Session.Configuration.Builder()
            .set_stored_credential_file(CREDENTIALS_FILE)
            .set_cache_enabled(False)
            .build()
        )
        # oauth() nutzt die gespeicherte Credentials-Datei, falls vorhanden,
        # und startet sonst den Browser-Login.
        _session = Session.Builder(conf).oauth(webbrowser.open).create()
        return _session


def _audio_quality():
    from librespot.audio.decoders import AudioQuality

    level = _QUALITY_LEVELS.get(cfg.get_playback_quality(), "HIGH")
    return getattr(AudioQuality, level)


def _sanitize(part: str) -> str:
    """Entfernt unter Windows/macOS unzulässige Zeichen aus einem Pfadsegment."""
    part = re.sub(r'[<>:"/\\|?*]', "_", part).strip(" .")
    return part or "Unbekannt"


def _render_path(meta: dict, output_dir: str) -> str:
    """Baut den Zielpfad (ohne Endung) aus der konfigurierten Vorlage."""
    track_number = meta.get("track_number") or 0
    values = {
        "%artist%": meta.get("artist", ""),
        "%artists%": meta.get("artists", meta.get("artist", "")),
        "%album%": meta.get("album", ""),
        "%title%": meta.get("title", ""),
        "%num,2%": f"{track_number:02d}",
        "%num%": str(track_number),
        "%disc%": str(meta.get("disc_number") or 1),
        "%year%": str(meta.get("year", "")),
    }
    template = cfg.get_download_template().replace("\\", "/")
    # Längere Platzhalter zuerst ersetzen, damit %num% nicht %num,2% zerstört.
    for placeholder in sorted(values, key=len, reverse=True):
        template = template.replace(placeholder, values[placeholder])

    segments = [_sanitize(seg) for seg in template.split("/") if seg.strip()]
    if not segments:
        segments = [_sanitize(meta.get("title", "")) or "Titel"]
    return _fit_path(output_dir, segments)


def _fit_path(output_dir: str, segments: list[str]) -> str:
    """Kürzt die Pfadsegmente so weit, dass der Gesamtpfad unter MAX_PATH bleibt.

    Ohne diese Kürzung sprengen lange Künstler-/Album-/Titelnamen die
    Windows-Grenze von 260 Zeichen; ``open()`` scheitert dann mit OSError und
    der Titel wird nur still als Fehler gezählt.
    """
    path = os.path.join(output_dir, *segments)
    if len(path) <= MAX_PATH_LENGTH:
        return path

    # Verfügbaren Platz gleichmäßig auf die Segmente verteilen (mind. 8 Zeichen
    # je Segment, damit Ordnernamen unterscheidbar bleiben).
    available = MAX_PATH_LENGTH - len(output_dir) - len(segments)
    per_segment = max(8, available // max(1, len(segments)))
    trimmed = [
        (segment[:per_segment].rstrip(" .") or "_") if len(segment) > per_segment else segment
        for segment in segments
    ]
    path = os.path.join(output_dir, *trimmed)
    if len(path) > MAX_PATH_LENGTH:
        raise RuntimeError(
            "Der Zielpfad für den Download ist zu lang.\n"
            "Wählen Sie einen kürzeren Download-Ordner oder eine einfachere "
            "Namensvorlage (Bearbeiten > Einstellungen)."
        )
    return path


# Heruntergeladene Cover (URL → Bytes) zwischenspeichern, damit das Albumbild
# nicht für jeden Titel desselben Albums erneut geladen wird. Cover sind
# 100–500 KB groß – der Cache ist darum als LRU begrenzt; er soll nur innerhalb
# eines Albums sparen, nicht alle Bilder einer Download-Sitzung im RAM halten.
_COVER_CACHE_SIZE = 16
_cover_cache: OrderedDict[str, bytes | None] = OrderedDict()
_cover_lock = threading.Lock()


def _fetch_cover(url: str) -> bytes | None:
    """Lädt das Cover-Bild (JPEG) einmalig pro URL herunter (LRU-Cache)."""
    if not url:
        return None
    with _cover_lock:
        if url in _cover_cache:
            _cover_cache.move_to_end(url)
            return _cover_cache[url]
    try:
        import requests

        data = requests.get(url, timeout=15).content
    except Exception:
        data = None
    with _cover_lock:
        _cover_cache[url] = data
        _cover_cache.move_to_end(url)
        while len(_cover_cache) > _COVER_CACHE_SIZE:
            _cover_cache.popitem(last=False)
    return data


def _write_tags(path: str, fmt: str, meta: dict):
    """Schreibt einen einheitlichen, reichhaltigen Tag-Satz (inkl. Cover)."""
    cover = _fetch_cover(meta.get("cover_url", ""))
    try:
        if fmt == "mp3":
            _tag_mp3(path, meta, cover)
        elif fmt == "m4a":
            _tag_m4a(path, meta, cover)
        else:
            _tag_ogg(path, meta, cover)
    except Exception:
        # Tagging ist optional – ein Fehler soll den Download nicht abbrechen.
        pass


def _tag_ogg(path: str, meta: dict, cover: bytes | None):
    """Schreibt Vorbis-Kommentare (inkl. eingebettetem Cover) in eine OGG-Datei."""
    import base64

    from mutagen.flac import Picture
    from mutagen.oggvorbis import OggVorbis

    audio = OggVorbis(path)
    fields = {
        "title": meta.get("title", ""),
        "artist": meta.get("artist", ""),
        "albumartist": meta.get("albumartist", ""),
        "album": meta.get("album", ""),
        "date": meta.get("date", ""),
        "genre": meta.get("genre", ""),
        "isrc": meta.get("isrc", ""),
        "organization": meta.get("label", ""),
        "discnumber": str(meta["disc_number"]) if meta.get("disc_number") else "",
        "disctotal": str(meta["total_discs"]) if meta.get("total_discs") else "",
        "tracknumber": str(meta["track_number"]) if meta.get("track_number") else "",
        "tracktotal": str(meta["total_tracks"]) if meta.get("total_tracks") else "",
    }
    for key, value in fields.items():
        if value:
            audio[key] = [value]
    if cover:
        picture = Picture()
        picture.type = 3  # Front cover
        picture.mime = "image/jpeg"
        picture.desc = "Cover"
        picture.data = cover
        audio["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
    audio.save()


def _tag_mp3(path: str, meta: dict, cover: bytes | None):
    """Schreibt ID3v2-Tags (inkl. APIC-Cover) in eine MP3-Datei."""
    from mutagen.id3 import (
        APIC, ID3, ID3NoHeaderError, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TPUB, TRCK, TSRC,
    )

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    def track_text(num, total):
        return f"{num}/{total}" if num and total else (str(num) if num else "")

    frames = [
        (TIT2, meta.get("title", "")),
        (TPE1, meta.get("artist", "")),
        (TPE2, meta.get("albumartist", "")),
        (TALB, meta.get("album", "")),
        (TDRC, meta.get("date", "")),
        (TCON, meta.get("genre", "")),
        (TSRC, meta.get("isrc", "")),
        (TPUB, meta.get("label", "")),
        (TRCK, track_text(meta.get("track_number"), meta.get("total_tracks"))),
        (TPOS, track_text(meta.get("disc_number"), meta.get("total_discs"))),
    ]
    for frame_cls, value in frames:
        if value:
            tags.add(frame_cls(encoding=3, text=str(value)))
    if cover:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    tags.save(path)


def _tag_m4a(path: str, meta: dict, cover: bytes | None):
    """Schreibt MP4/iTunes-Atome (inkl. Cover) in eine M4A-Datei."""
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    text_atoms = {
        "\xa9nam": meta.get("title", ""),
        "\xa9ART": meta.get("artist", ""),
        "aART": meta.get("albumartist", ""),
        "\xa9alb": meta.get("album", ""),
        "\xa9day": meta.get("date", ""),
        "\xa9gen": meta.get("genre", ""),
    }
    for atom, value in text_atoms.items():
        if value:
            audio[atom] = [value]
    if meta.get("track_number"):
        audio["trkn"] = [(meta["track_number"], meta.get("total_tracks") or 0)]
    if meta.get("disc_number"):
        audio["disk"] = [(meta["disc_number"], meta.get("total_discs") or 0)]
    if meta.get("isrc"):
        audio["----:com.apple.iTunes:ISRC"] = [meta["isrc"].encode("utf-8")]
    if meta.get("label"):
        audio["----:com.apple.iTunes:LABEL"] = [meta["label"].encode("utf-8")]
    if cover:
        audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def _require_ffmpeg() -> str:
    """Liefert den ffmpeg-Pfad oder wirft eine verständliche Fehlermeldung."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "Für MP3-/M4A-Downloads wird 'ffmpeg' benötigt, es wurde aber nicht gefunden.\n"
            "Installieren Sie ffmpeg und stellen Sie sicher, dass es im PATH liegt, "
            "oder wählen Sie in den Einstellungen das Download-Format 'OGG Vorbis'."
        )
    return ffmpeg


def _transcode(ogg_path: str, target: str, fmt: str):
    """Wandelt eine OGG-Datei per ffmpeg in MP3 oder M4A um (Tags setzt mutagen)."""
    ffmpeg = _require_ffmpeg()
    codec = "libmp3lame" if fmt == "mp3" else "aac"
    cmd = [
        ffmpeg,
        "-y",
        "-i", ogg_path,
        "-vn",
        "-c:a", codec,
        "-b:a", cfg.get_download_quality(),
        target,
    ]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW_FLAGS,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg konnte die Datei nicht umwandeln:\n"
            + (result.stderr or result.stdout or "Unbekannter ffmpeg-Fehler").strip()
        )


def _download_one(meta: dict, output_dir: str) -> str:
    """Lädt einen Titel und speichert ihn im konfigurierten Format; gibt den Pfad zurück."""
    from librespot.metadata import EpisodeId, TrackId
    from librespot.audio.decoders import VorbisOnlyAudioQuality

    uri = meta["uri"]
    if uri.startswith("spotify:episode"):
        content_id = EpisodeId.from_uri(uri)
    else:
        content_id = TrackId.from_uri(uri)

    fmt = cfg.get_download_format()
    extension = _FORMAT_EXTENSIONS.get(fmt, ".ogg")
    base = _render_path(meta, output_dir)
    target = base + extension
    if os.path.isfile(target):
        return target  # Bereits vorhanden – nicht erneut laden.

    # ffmpeg früh prüfen, bevor der Stream geladen wird.
    if fmt != "ogg":
        _require_ffmpeg()

    session = _get_session()
    loaded = session.content_feeder().load(
        content_id,
        VorbisOnlyAudioQuality(_audio_quality()),
        False,
        None,
    )
    data = loaded.input_stream.stream().read()

    os.makedirs(os.path.dirname(target), exist_ok=True)

    if fmt == "ogg":
        with open(target, "wb") as handle:
            handle.write(data)
        _write_tags(target, fmt, meta)
        return target

    # MP3/M4A: OGG-Stream zwischenspeichern und per ffmpeg umwandeln.
    ogg_temp = base + ".spotiflix.tmp.ogg"
    try:
        with open(ogg_temp, "wb") as handle:
            handle.write(data)
        _transcode(ogg_temp, target, fmt)
        _write_tags(target, fmt, meta)
    finally:
        try:
            os.remove(ogg_temp)
        except OSError:
            pass
    return target


# Genre je Künstler-ID zwischenspeichern (Spotify liefert Genres nur am Künstler).
_artist_genre_cache: dict[str, str] = {}


def _load_genres(sp, artist_ids: list[str]):
    """Lädt fehlende Künstler-Genres gebündelt (max. 50 pro Aufruf) in den Cache."""
    missing = [a for a in dict.fromkeys(artist_ids) if a and a not in _artist_genre_cache]
    for start in range(0, len(missing), 50):
        chunk = missing[start:start + 50]
        try:
            for artist in sp.artists(chunk).get("artists", []):
                if artist and artist.get("id"):
                    genres = artist.get("genres") or []
                    _artist_genre_cache[artist["id"]] = genres[0].title() if genres else ""
        except Exception:
            for artist_id in chunk:
                _artist_genre_cache.setdefault(artist_id, "")


def _primary_artist_id(track: dict) -> str:
    artists = track.get("artists") or []
    return artists[0].get("id", "") if artists else ""


def _track_meta(track: dict, album_obj: dict | None = None, label: str = "", total_discs: int = 0) -> dict:
    """Übersetzt ein Spotify-Track-Objekt in die interne Metadatenstruktur."""
    album = album_obj or track.get("album") or {}
    artists = track.get("artists", []) or []
    artist_names = ", ".join(a.get("name", "") for a in artists)
    album_artists = album.get("artists", []) or []
    albumartist = ", ".join(a.get("name", "") for a in album_artists)
    if not albumartist and artists:
        albumartist = artists[0].get("name", "")
    release_date = album.get("release_date", "") or track.get("release_date", "")
    images = album.get("images") or track.get("images") or []
    cover_url = images[0]["url"] if images and images[0].get("url") else ""
    genre = _artist_genre_cache.get(_primary_artist_id(track), "")
    return {
        "uri": track.get("uri", ""),
        "title": track.get("name", ""),
        "artist": artist_names,
        "artists": artist_names,
        "albumartist": albumartist,
        "album": album.get("name", ""),
        "track_number": track.get("track_number") or 0,
        "disc_number": track.get("disc_number") or 1,
        "total_tracks": album.get("total_tracks") or 0,
        "total_discs": total_discs or 0,
        "year": release_date[:4] if release_date else "",
        "date": release_date,
        "genre": genre,
        "isrc": (track.get("external_ids") or {}).get("isrc", ""),
        "label": label,
        "cover_url": cover_url,
    }


def _episode_meta(episode: dict) -> dict:
    """Metadaten für eine Podcast-Episode (Show statt Album)."""
    show = episode.get("show") or {}
    images = episode.get("images") or show.get("images") or []
    release_date = episode.get("release_date", "")
    return {
        "uri": episode.get("uri", ""),
        "title": episode.get("name", ""),
        "artist": show.get("publisher", "") or show.get("name", ""),
        "artists": show.get("publisher", "") or show.get("name", ""),
        "albumartist": show.get("name", ""),
        "album": show.get("name", ""),
        "track_number": 0,
        "disc_number": 1,
        "total_tracks": 0,
        "total_discs": 0,
        "year": release_date[:4] if release_date else "",
        "date": release_date,
        "genre": "",
        "isrc": "",
        "label": "",
        "cover_url": images[0]["url"] if images and images[0].get("url") else "",
    }


def _resolve_tracks(item: dict) -> list[dict]:
    """Löst ein UI-Element in eine Liste herunterladbarer Titel-Metadaten auf."""
    from spotify_client import client
    from ui.panel_helpers import collect_page_items

    item_type = item.get("type")
    uri = item.get("uri", "")

    sp = client.get()
    if not sp:
        raise RuntimeError("Zuerst autorisieren!")

    if item_type == "episode":
        if not uri:
            raise RuntimeError("Kein Spotify-URI für dieses Element verfügbar.")
        return [_episode_meta(sp.episode(uri))]

    if item_type == "track":
        if not uri:
            raise RuntimeError("Kein Spotify-URI für dieses Element verfügbar.")
        # Vollständigen Titel holen (Cover, ISRC, Album-Infos sind in der UI-Zeile nicht enthalten).
        track = sp.track(uri)
        album = track.get("album") or {}
        label = _album_label(sp, album.get("id"))
        _load_genres(sp, [_primary_artist_id(track)])
        return [_track_meta(track, album, label)]

    item_id = item.get("id")
    if not item_id:
        raise RuntimeError("Keine Spotify-ID für dieses Element verfügbar.")

    if item_type == "album":
        album = sp.album(item_id)
        label = album.get("label", "")
        tracks = [t for t in collect_page_items(sp, album.get("tracks")) if t.get("uri")]
        total_discs = max((t.get("disc_number") or 1) for t in tracks) if tracks else 1
        # ISRC steckt nicht in den vereinfachten Album-Tracks → gebündelt nachladen.
        isrc_map = _isrc_map(sp, [t["uri"] for t in tracks])
        _load_genres(sp, [_primary_artist_id(t) for t in tracks])
        metas = []
        for track in tracks:
            track.setdefault("external_ids", {})
            if isrc_map.get(track["uri"]):
                track["external_ids"]["isrc"] = isrc_map[track["uri"]]
            metas.append(_track_meta(track, album, label, total_discs))
        return metas

    if item_type == "playlist":
        results = sp.playlist_items(
            item_id,
            fields="next,items(track(uri,name,type,track_number,disc_number,external_ids,"
            "artists(id,name),album(id,name,release_date,total_tracks,images,artists(name))))",
            limit=100,
        )
        tracks = [
            entry["track"]
            for entry in collect_page_items(sp, results)
            if entry.get("track") and entry["track"].get("uri")
        ]
        _load_genres(sp, [_primary_artist_id(t) for t in tracks])
        return [_track_meta(track) for track in tracks]

    if item_type == "artist":
        top = [t for t in sp.artist_top_tracks(item_id).get("tracks", []) if t.get("uri")]
        _load_genres(sp, [_primary_artist_id(t) for t in top])
        return [_track_meta(track) for track in top]

    raise RuntimeError(f"Download für Typ '{item_type}' wird nicht unterstützt.")


# Album-Label je Album-ID zwischenspeichern (nur am vollständigen Album verfügbar).
_album_label_cache: dict[str, str] = {}


def _album_label(sp, album_id: str | None) -> str:
    if not album_id:
        return ""
    if album_id in _album_label_cache:
        return _album_label_cache[album_id]
    try:
        label = sp.album(album_id).get("label", "")
    except Exception:
        label = ""
    _album_label_cache[album_id] = label
    return label


def _isrc_map(sp, uris: list[str]) -> dict[str, str]:
    """Liefert {Track-URI: ISRC} gebündelt (max. 50 IDs pro Aufruf)."""
    result: dict[str, str] = {}
    for start in range(0, len(uris), 50):
        chunk = uris[start:start + 50]
        try:
            for track in sp.tracks(chunk).get("tracks", []):
                if track and track.get("uri"):
                    isrc = (track.get("external_ids") or {}).get("isrc", "")
                    if isrc:
                        result[track["uri"]] = isrc
        except Exception:
            break
    return result


def download_via_librespot(
    item: dict,
    output_dir: str | None = None,
    progress_callback=None,
    cancel_event=None,
) -> str:
    """Lädt ein Element (Titel/Album/Playlist/Künstler) als echten Spotify-Stream.

    ``progress_callback`` wird optional mit (verarbeitet, gesamt) aufgerufen,
    damit die UI den Fortschritt anzeigen kann, ohne zu blockieren.
    ``cancel_event`` bricht zwischen zwei Titeln ab; der laufende Titel wird
    noch fertig geschrieben, damit keine halbe Datei zurückbleibt.
    """
    _require_librespot()
    tracks = _resolve_tracks(item)
    if not tracks:
        raise RuntimeError("Keine herunterladbaren Titel gefunden.")

    target_dir = os.path.expanduser(output_dir or cfg.get_download_dir())
    os.makedirs(target_dir, exist_ok=True)

    total = len(tracks)
    if progress_callback:
        progress_callback(0, total)

    saved = 0
    errors = []
    cancelled = False
    for index, meta in enumerate(tracks, start=1):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        try:
            _download_one(meta, target_dir)
            saved += 1
        except Exception as e:
            errors.append(f"{meta.get('title', '?')}: {e}")
        if progress_callback:
            progress_callback(index, total)

    if cancelled:
        from download_manager import DownloadCancelled

        raise DownloadCancelled(f"Abgebrochen nach {saved} von {total} Titel(n).")

    if saved == 0:
        raise RuntimeError("Download fehlgeschlagen.\n" + "\n".join(errors))

    summary = f"{saved} von {len(tracks)} Titel(n) heruntergeladen."
    if errors:
        summary += "\n\nFehler bei:\n" + "\n".join(errors)
    return summary
