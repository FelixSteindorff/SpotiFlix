"""
Konfiguration und Credential-Verwaltung via OS-Schlüsselspeicher (keyring)
"""
import os
import json
import threading

import keyring

SERVICE_NAME = "SpotiFlix"
TOKEN_FILE = os.path.expanduser("~/.spotify-token.json")
SETTINGS_FILE = os.path.expanduser("~/.spotiflix-settings.json")
DEFAULT_DOWNLOAD_DIR = os.path.expanduser("~/Music/SpotiFlix")
DEFAULT_PLAYBACK_QUALITY = "160"
DEFAULT_DOWNLOAD_QUALITY = "320k"
DEFAULT_DOWNLOAD_TEMPLATE = "%artist%/%album%/%num,2% - %title%"
DEFAULT_DOWNLOAD_METHOD = "spotdl"
DEFAULT_DOWNLOAD_FORMAT = "ogg"
DEFAULT_AUTOPLAY = "context"
DEFAULT_VERBOSITY = "full"
# Ausführlichkeit der Sprachansagen. „Kurz" lässt Zwischenmeldungen wie
# „Lade Alben …" weg und sagt nur noch Ergebnisse und Fehler an; in der
# Statusleiste stehen sie weiterhin.
VERBOSITY_MODES = {
    "full": "Ausführlich (auch Zwischenmeldungen)",
    "short": "Kurz (nur Ergebnisse)",
}
# Wie viele Suchbegriffe im Verlauf des Suchfelds behalten werden.
SEARCH_HISTORY_SIZE = 20
# librespot-Wiedergabe: Lautstärke-Normalisierung und Startlautstärke.
DEFAULT_VOLUME_NORMALISATION = True
DEFAULT_INITIAL_VOLUME = 50
# Wie viele Downloads gleichzeitig laufen dürfen (der Rest wartet in der Schlange).
DEFAULT_DOWNLOAD_PARALLEL = 2
MAX_DOWNLOAD_PARALLEL = 4
# Schnellzugriffe (Strg+Umschalt+1 … 9) auf Playlists, Alben, Künstler, Podcasts.
MAX_BOOKMARKS = 9
# Autoplay-Modus: Was passiert, nachdem ein einzelner Titel abgespielt wurde?
AUTOPLAY_MODES = {
    "off": "Aus (nur der gewählte Titel)",
    "context": "In Playlist/Album fortsetzen",
    "all": "Immer weiterspielen",
}
DOWNLOAD_METHODS = {
    "spotdl": "YouTube-Quelle (spotdl)",
    "librespot": "Echter Spotify-Stream (librespot)",
}
# Dateiformat für librespot-Downloads. "ogg" ist der native Stream ohne
# Umwandlung; "mp3"/"m4a" werden per ffmpeg aus dem OGG-Stream konvertiert.
DOWNLOAD_FORMATS = {
    "ogg": "OGG Vorbis (Original)",
    "mp3": "MP3",
    "m4a": "M4A (AAC)",
}
PLAYBACK_QUALITIES = {
    "96": "Niedrig (96 kbit/s)",
    "160": "Normal (160 kbit/s)",
    "320": "Hoch (320 kbit/s)",
}
DOWNLOAD_QUALITIES = {
    "128k": "128 kbit/s",
    "192k": "192 kbit/s",
    "256k": "256 kbit/s",
    "320k": "320 kbit/s",
}


def save_credentials(client_id: str, client_secret: str) -> bool:
    """Speichert Credentials sicher im OS-Schlüsselspeicher."""
    try:
        keyring.set_password(SERVICE_NAME, "client_id", client_id)
        keyring.set_password(SERVICE_NAME, "client_secret", client_secret)
        return True
    except Exception as e:
        print(f"Fehler beim Speichern der Credentials: {e}")
        return False


def get_client_id() -> str | None:
    """Gibt die gespeicherte Client-ID zurück."""
    return keyring.get_password(SERVICE_NAME, "client_id")


def get_client_secret() -> str | None:
    """Gibt das gespeicherte Client-Secret zurück."""
    return keyring.get_password(SERVICE_NAME, "client_secret")


def has_credentials() -> bool:
    """Prüft ob Credentials vorhanden sind."""
    return bool(get_client_id() and get_client_secret())


# Einstellungs-Cache: Getter wie get_download_template() werden pro
# heruntergeladenem Titel bzw. pro Wiedergabe aufgerufen – ohne Cache liest das
# jedes Mal die JSON-Datei. Der Cache wird verworfen, sobald sich die
# Änderungszeit der Datei unterscheidet (z. B. nach Bearbeiten von Hand).
_settings_cache: dict | None = None
_settings_mtime: float | None = None
_settings_lock = threading.Lock()


def _settings_file_mtime() -> float | None:
    try:
        return os.path.getmtime(SETTINGS_FILE)
    except OSError:
        return None


def _read_settings_file() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"Fehler beim Laden der Einstellungen: {e}")
        return {}


def _load_settings() -> dict:
    """Liefert die Einstellungen (gecacht; Neuladen nur bei geänderter Datei).

    Gibt bewusst eine Kopie zurück, damit Aufrufer, die das Ergebnis für
    ``_save_settings`` verändern, nicht den Cache verfälschen.
    """
    global _settings_cache, _settings_mtime
    mtime = _settings_file_mtime()
    with _settings_lock:
        if _settings_cache is None or mtime != _settings_mtime:
            _settings_cache = _read_settings_file()
            _settings_mtime = mtime
        return dict(_settings_cache)


def _save_settings(settings: dict) -> bool:
    global _settings_cache, _settings_mtime
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
        with _settings_lock:
            _settings_cache = dict(settings)
            _settings_mtime = _settings_file_mtime()
        return True
    except Exception as e:
        print(f"Fehler beim Speichern der Einstellungen: {e}")
        return False


def get_download_dir() -> str:
    """Gibt den konfigurierten Download-Ordner zurück."""
    value = _load_settings().get("download_dir")
    if isinstance(value, str) and value.strip():
        return os.path.expanduser(value.strip())
    return DEFAULT_DOWNLOAD_DIR


def save_download_dir(download_dir: str) -> bool:
    """Speichert den Zielordner für Downloads."""
    settings = _load_settings()
    settings["download_dir"] = os.path.expanduser(download_dir.strip() or DEFAULT_DOWNLOAD_DIR)
    return _save_settings(settings)


def get_playback_quality() -> str:
    """Gibt die librespot-Bitrate für lokale Wiedergabe zurück."""
    value = str(_load_settings().get("playback_quality", DEFAULT_PLAYBACK_QUALITY))
    return value if value in PLAYBACK_QUALITIES else DEFAULT_PLAYBACK_QUALITY


def get_download_quality() -> str:
    """Gibt die spotdl-Download-Bitrate zurück."""
    value = str(_load_settings().get("download_quality", DEFAULT_DOWNLOAD_QUALITY))
    return value if value in DOWNLOAD_QUALITIES else DEFAULT_DOWNLOAD_QUALITY


def get_download_template() -> str:
    """Gibt die relative Ordner-/Dateivorlage für Downloads zurück."""
    value = _load_settings().get("download_template", DEFAULT_DOWNLOAD_TEMPLATE)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_DOWNLOAD_TEMPLATE


def get_download_method() -> str:
    """Gibt die gewählte Download-Methode zurück ('spotdl' oder 'librespot')."""
    value = str(_load_settings().get("download_method", DEFAULT_DOWNLOAD_METHOD))
    return value if value in DOWNLOAD_METHODS else DEFAULT_DOWNLOAD_METHOD


def get_download_format() -> str:
    """Gibt das librespot-Download-Dateiformat zurück ('ogg', 'mp3' oder 'm4a')."""
    value = str(_load_settings().get("download_format", DEFAULT_DOWNLOAD_FORMAT))
    return value if value in DOWNLOAD_FORMATS else DEFAULT_DOWNLOAD_FORMAT


def get_verbosity() -> str:
    """Gibt die Ausführlichkeit der Ansagen zurück ('full' oder 'short')."""
    value = str(_load_settings().get("verbosity", DEFAULT_VERBOSITY))
    return value if value in VERBOSITY_MODES else DEFAULT_VERBOSITY


def get_playback_device() -> str:
    """Gibt das gewählte Wiedergabegerät zurück ('' = lokaler SpotiFlix-Player)."""
    value = _load_settings().get("playback_device", "")
    return value.strip() if isinstance(value, str) else ""


def save_playback_device(name: str) -> bool:
    """Merkt sich das Wiedergabegerät über den Namen (IDs ändern sich)."""
    settings = _load_settings()
    settings["playback_device"] = (name or "").strip()
    return _save_settings(settings)


def get_search_history() -> list[str]:
    """Gibt die zuletzt genutzten Suchbegriffe zurück (neueste zuerst)."""
    value = _load_settings().get("search_history", [])
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str) and entry.strip()]


def add_search_history(query: str) -> bool:
    """Stellt einen Suchbegriff an den Anfang des Verlaufs (ohne Duplikate)."""
    query = (query or "").strip()
    if not query:
        return False
    history = [entry for entry in get_search_history() if entry.casefold() != query.casefold()]
    history.insert(0, query)
    settings = _load_settings()
    settings["search_history"] = history[:SEARCH_HISTORY_SIZE]
    return _save_settings(settings)


def get_volume_normalisation() -> bool:
    """Gibt an, ob librespot die Lautstärke normalisieren soll."""
    value = _load_settings().get("volume_normalisation", DEFAULT_VOLUME_NORMALISATION)
    return bool(value)


def get_initial_volume() -> int:
    """Gibt die Startlautstärke des lokalen Players in Prozent zurück."""
    try:
        value = int(_load_settings().get("initial_volume", DEFAULT_INITIAL_VOLUME))
    except (TypeError, ValueError):
        return DEFAULT_INITIAL_VOLUME
    return max(0, min(100, value))


def get_download_parallel() -> int:
    """Gibt zurück, wie viele Downloads gleichzeitig laufen dürfen."""
    try:
        value = int(_load_settings().get("download_parallel", DEFAULT_DOWNLOAD_PARALLEL))
    except (TypeError, ValueError):
        return DEFAULT_DOWNLOAD_PARALLEL
    return max(1, min(MAX_DOWNLOAD_PARALLEL, value))


def get_bookmarks() -> list[dict]:
    """Gibt die gespeicherten Schnellzugriffe zurück (Reihenfolge = Tastennummer)."""
    value = _load_settings().get("bookmarks", [])
    if not isinstance(value, list):
        return []
    return [
        entry for entry in value
        if isinstance(entry, dict) and entry.get("id") and entry.get("type")
    ][:MAX_BOOKMARKS]


def save_bookmarks(bookmarks: list[dict]) -> bool:
    """Speichert die Schnellzugriffe (höchstens ``MAX_BOOKMARKS`` Stück)."""
    settings = _load_settings()
    settings["bookmarks"] = [
        {"type": entry.get("type", ""), "id": entry.get("id", ""), "name": entry.get("name", "")}
        for entry in bookmarks[:MAX_BOOKMARKS]
    ]
    return _save_settings(settings)


def get_autoplay() -> str:
    """Gibt den Autoplay-Modus zurück ('off', 'context' oder 'all')."""
    value = str(_load_settings().get("autoplay", DEFAULT_AUTOPLAY))
    return value if value in AUTOPLAY_MODES else DEFAULT_AUTOPLAY


def save_player_settings(
    playback_quality: str,
    download_quality: str,
    download_template: str,
    download_method: str = DEFAULT_DOWNLOAD_METHOD,
    download_format: str = DEFAULT_DOWNLOAD_FORMAT,
    autoplay: str = DEFAULT_AUTOPLAY,
    verbosity: str = DEFAULT_VERBOSITY,
    volume_normalisation: bool = DEFAULT_VOLUME_NORMALISATION,
    initial_volume: int = DEFAULT_INITIAL_VOLUME,
    download_parallel: int = DEFAULT_DOWNLOAD_PARALLEL,
) -> bool:
    """Speichert Wiedergabe- und Download-Einstellungen."""
    settings = _load_settings()
    settings["playback_quality"] = playback_quality if playback_quality in PLAYBACK_QUALITIES else DEFAULT_PLAYBACK_QUALITY
    settings["download_quality"] = download_quality if download_quality in DOWNLOAD_QUALITIES else DEFAULT_DOWNLOAD_QUALITY
    settings["download_template"] = download_template.strip() or DEFAULT_DOWNLOAD_TEMPLATE
    settings["download_method"] = download_method if download_method in DOWNLOAD_METHODS else DEFAULT_DOWNLOAD_METHOD
    settings["download_format"] = download_format if download_format in DOWNLOAD_FORMATS else DEFAULT_DOWNLOAD_FORMAT
    settings["autoplay"] = autoplay if autoplay in AUTOPLAY_MODES else DEFAULT_AUTOPLAY
    settings["verbosity"] = verbosity if verbosity in VERBOSITY_MODES else DEFAULT_VERBOSITY
    settings["volume_normalisation"] = bool(volume_normalisation)
    settings["initial_volume"] = max(0, min(100, int(initial_volume)))
    settings["download_parallel"] = max(1, min(MAX_DOWNLOAD_PARALLEL, int(download_parallel)))
    return _save_settings(settings)
