"""
SpotifyClient: Zentrales Token-Management und Spotify-API-Zugriff
"""
import json
import os
import time
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
import config as cfg

from i18n import _

# Erweiterte Scopes für Bibliothek, Entdecken und lokale Wiedergabe.
# "streaming" wird für den Access-Token benötigt, mit dem librespot lokal startet.
SCOPES = (
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-private playlist-modify-public "
    "user-library-read user-library-modify "
    "user-follow-read user-follow-modify user-top-read user-read-recently-played "
    "user-modify-playback-state user-read-playback-state user-read-currently-playing streaming"
)
REDIRECT_URI = "http://127.0.0.1:8080/callback"
REQUIRED_SCOPES = set(SCOPES.split())

# Bibliotheks-Endpunkte je Elementtyp: (prüfen, hinzufügen, entfernen).
_LIBRARY_ENDPOINTS = {
    "track": (
        "current_user_saved_tracks_contains",
        "current_user_saved_tracks_add",
        "current_user_saved_tracks_delete",
    ),
    "album": (
        "current_user_saved_albums_contains",
        "current_user_saved_albums_add",
        "current_user_saved_albums_delete",
    ),
    "episode": (
        "current_user_saved_episodes_contains",
        "current_user_saved_episodes_add",
        "current_user_saved_episodes_delete",
    ),
    "show": (
        "current_user_saved_shows_contains",
        "current_user_saved_shows_add",
        "current_user_saved_shows_delete",
    ),
}
# Typen, die in der Mediathek gespeichert bzw. gefolgt werden können.
LIBRARY_TYPES = set(_LIBRARY_ENDPOINTS) | {"artist", "playlist"}


class SpotifyClient:
    """Kapselt den Spotify-Client mit automatischer Token-Erneuerung und Wiedergabesteuerung."""

    def __init__(self):
        self._sp: Spotify | None = None
        self._auth_manager: SpotifyOAuth | None = None
        self._local_device_cache: tuple[str, float] | None = None
        self._user_id: str | None = None
        # Credentials aus dem Schlüsselspeicher zwischenspeichern: get() läuft
        # bei jedem API-Aufruf (inkl. Now-Playing-Polling), und jeder
        # keyring-Zugriff geht in den Windows-Anmeldeinformationsspeicher.
        self._credentials: tuple[str | None, str | None] | None = None
        # Auflösung des gewählten Wiedergabegeräts (Name → ID) mit Zeitstempel.
        self._device_cache: tuple[str, str, float] | None = None
        # Merkt, dass das gespeicherte Token nicht alle Berechtigungen hat –
        # das Hauptfenster kann dann gezielt zum Neu-Autorisieren auffordern.
        self.missing_scopes = False

    def _get_credentials(self) -> tuple[str | None, str | None]:
        """Liest Client-ID/Secret einmalig aus dem Schlüsselspeicher (Cache)."""
        if self._credentials is None:
            self._credentials = (cfg.get_client_id(), cfg.get_client_secret())
        return self._credentials

    def get(self) -> Spotify | None:
        """Liefert den Spotify-Client, führt bei Bedarf eine automatische Token-Erneuerung durch."""
        client_id, client_secret = self._get_credentials()
        if not client_id or not client_secret:
            return None

        if not self._auth_manager:
            self._auth_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=REDIRECT_URI,
                scope=SCOPES,
                cache_path=cfg.TOKEN_FILE,
                open_browser=True,
            )

        # Prüft, ob ein gültiges Token im Cache ist oder erneuert es automatisch.
        # Ab dem 20.07.2026 laufen Refresh-Tokens nach 6 Monaten ab; Spotify
        # antwortet dann beim Erneuern mit invalid_grant. Gemäß Vorgabe wird das
        # gespeicherte Token verworfen (kein erneuter Versuch) und ein neuer
        # Login erzwungen.
        try:
            token_info = self._auth_manager.get_cached_token()
        except SpotifyOauthError as error:
            if getattr(error, "error", None) == "invalid_grant":
                self._discard_token()
            else:
                self._sp = None
            return None
        if not token_info:
            # Wenn kein Cache vorhanden ist, wird die Browser-Autorisierung gestartet
            return None
        if not self._token_has_required_scopes(token_info):
            self.missing_scopes = True
            self._sp = None
            return None
        self.missing_scopes = False

        if not self._sp:
            self._sp = Spotify(auth_manager=self._auth_manager)
        return self._sp

    def _discard_token(self):
        """Verwirft ein ungültiges/abgelaufenes Token und setzt den Client
        zurück, sodass beim nächsten Bedarf ein neuer Login nötig ist."""
        try:
            os.remove(cfg.TOKEN_FILE)
        except FileNotFoundError:
            pass
        self._sp = None
        self._auth_manager = None
        self._local_device_cache = None

    def _token_has_required_scopes(self, token_info: dict) -> bool:
        scope_value = token_info.get("scope", "")
        if isinstance(scope_value, str):
            token_scopes = set(scope_value.split())
        elif isinstance(scope_value, list):
            token_scopes = set(scope_value)
        else:
            token_scopes = set()
        return REQUIRED_SCOPES.issubset(token_scopes)

    def start_auth_flow(self):
        """Startet den automatisierten Browser-Autorisierungsfluss."""
        # Frisch aus dem Schlüsselspeicher lesen – der Nutzer hat die
        # Credentials womöglich gerade erst eingetragen.
        self._credentials = None
        client_id, client_secret = self._get_credentials()
        if not client_id or not client_secret:
            return False

        # open_browser=False: Wir öffnen den Browser und betreiben den lokalen
        # Callback-Server selbst (siehe _capture_auth_code). spotipys eingebauter
        # Server behandelt nur EINE Anfrage – trifft ihn vorher ein codeloser
        # Request (Favicon/Prefetch/alter Tab), schließt er, bevor der echte
        # Callback ankommt ("Server listening on localhost has not been accessed").
        self._auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=REDIRECT_URI,
            scope=SCOPES,
            cache_path=cfg.TOKEN_FILE,
            open_browser=False,
        )
        cached_token = self._auth_manager.get_cached_token()
        if cached_token and not self._token_has_required_scopes(cached_token):
            try:
                os.remove(cfg.TOKEN_FILE)
            except FileNotFoundError:
                pass

        code = self._capture_auth_code()
        if not code:
            return False
        # Tauscht den Code gegen ein Token und legt es im Cache ab.
        token_info = self._auth_manager.get_access_token(code, check_cache=False)
        if token_info:
            self._sp = Spotify(auth_manager=self._auth_manager)
            return True
        return False

    def _capture_auth_code(self, timeout: float = 180.0) -> str | None:
        """Öffnet den Browser und wartet über einen dauerhaften lokalen Server
        auf den OAuth-Callback. Codelose Anfragen (Favicon, Prefetch, alte Tabs)
        werden ignoriert, statt den Server zu verbrauchen."""
        import webbrowser
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from urllib.parse import urlparse, parse_qs

        result: dict[str, str | None] = {"code": None, "error": None}

        class _CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlparse(self.path).query)
                if "code" in query:
                    result["code"] = query["code"][0]
                    body = (_("<h1>Login erfolgreich</h1>"
                            "Du kannst dieses Fenster jetzt schließen."))
                elif "error" in query:
                    result["error"] = query["error"][0]
                    body = _("<h1>Login fehlgeschlagen</h1>{result}").format(result=result['error'])
                else:
                    # Codelose Anfrage – ignorieren, Server bleibt offen.
                    self.send_response(204)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    f"<html><body>{body}</body></html>".encode("utf-8")
                )

            def log_message(self, *args):
                return

        parsed = urlparse(REDIRECT_URI)
        server = HTTPServer((parsed.hostname, parsed.port), _CallbackHandler)
        server.timeout = 1.0
        try:
            webbrowser.open(self._auth_manager.get_authorize_url())
            deadline = time.time() + timeout
            while result["code"] is None and result["error"] is None:
                if time.time() >= deadline:
                    break
                server.handle_request()
        finally:
            server.server_close()
        return result["code"]

    def get_device_id(self, device_name: str) -> str | None:
        """Sucht die Geräte-ID eines aktiven Spotify-Geräts nach Name."""
        sp = self.get()
        if not sp:
            return None
        try:
            for device in sp.devices().get("devices", []):
                if device["name"] == device_name:
                    return device["id"]
        except Exception:
            pass
        return None

    # librespot braucht nach dem Start rund 13 Sekunden, bis es sich beim
    # Access Point angemeldet und als Connect-Gerät registriert hat. Das
    # Wartefenster muss deutlich darüber liegen, sonst gilt der Player als
    # "nicht gefunden", obwohl er gleich darauf erscheint.
    def _local_device_id(self, wait_seconds: float = 35.0) -> str:
        """Startet/ermittelt ausschließlich das lokale SpotiFlix-Gerät."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))

        from librespot_manager import DEVICE_NAME, librespot

        if self._local_device_cache and librespot.is_running():
            device_id, cached_at = self._local_device_cache
            if time.time() - cached_at < 30:
                return device_id

        if not librespot.is_running():
            # Erzwingt bei Bedarf eine Token-Erneuerung, bevor librespot den
            # Access-Token aus dem Spotipy-Cache liest.
            sp.devices()
            librespot.start()

        deadline = time.time() + wait_seconds
        last_devices = []
        # Wachsender Abstand zwischen den Abfragen: schnell, solange der Player
        # gleich auftauchen kann, danach sparsam – sonst läuft man beim Warten
        # in Spotifys Anfragegrenze (HTTP 429).
        delay = 1.0
        while time.time() < deadline:
            devices = sp.devices().get("devices", [])
            last_devices = devices
            for device in devices:
                if device.get("name") == DEVICE_NAME:
                    self._local_device_cache = (device["id"], time.time())
                    return device["id"]
            time.sleep(delay)
            delay = min(delay * 1.5, 4.0)

        device_names = ", ".join(device.get("name", "?") for device in last_devices) or "keine"
        detail = _("\n\nGefundene Spotify-Geräte: {device_names}").format(device_names=device_names)
        if librespot.login_problem():
            detail += (
                _("\n\nSpotify hat die Anmeldung des Geräts abgelehnt. Melden Sie den "
                "lokalen Player über 'Extras > Lokalen Player neu anmelden' erneut an.")
            )
        log = librespot.last_log()
        if log:
            detail += f"\n\nlibrespot-Log:\n{log}"
        raise RuntimeError(
            _("Der lokale Player '{DEVICE_NAME}' wurde gestartet, aber nicht als Spotify-Gerät gefunden.{detail}").format(DEVICE_NAME=DEVICE_NAME, detail=detail)
        )

    def clear_local_device_cache(self):
        """Verwirft die gecachte lokale Geräte-ID."""
        self._local_device_cache = None
        self._device_cache = None

    def reset_auth(self):
        """Verwirft Client und Auth-Manager, z. B. nach geänderten Credentials."""
        self._auth_manager = None
        self._sp = None
        self._local_device_cache = None
        self._device_cache = None
        self._user_id = None
        self._credentials = None
        self.missing_scopes = False

    def list_devices(self) -> list[dict]:
        """Listet die verfügbaren Spotify-Connect-Geräte des Kontos."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        devices = sp.devices().get("devices", []) or []
        return [
            {
                "id": device.get("id"),
                "name": device.get("name", ""),
                "type": device.get("type", ""),
                "is_active": bool(device.get("is_active")),
                "volume_percent": device.get("volume_percent"),
            }
            for device in devices
            if device.get("id")
        ]

    def _selected_device_id(self, name: str) -> str:
        """Löst das gewählte Gerät über seinen Namen auf (IDs wechseln)."""
        if self._device_cache:
            cached_name, device_id, cached_at = self._device_cache
            if cached_name == name and time.time() - cached_at < 30:
                return device_id
        for device in self.list_devices():
            if device["name"] == name:
                self._device_cache = (name, device["id"], time.time())
                return device["id"]
        raise RuntimeError(
            _("Das Wiedergabegerät „{name}“ ist gerade nicht verfügbar.\nSchalten Sie es ein oder wählen Sie unter 'Extras > Wiedergabegerät …' ein anderes Gerät.").format(name=name)
        )

    def _playback_device_id(self) -> str:
        """Liefert die Geräte-ID für alle Wiedergabebefehle.

        Ohne ausdrückliche Wahl ist das der lokale librespot-Player; er wird
        bei Bedarf gestartet. Ein fremdes Gerät (Handy, Desktop-App, Box) wird
        dagegen nur benutzt, wenn es gerade online ist.
        """
        name = cfg.get_playback_device()
        if name:
            return self._selected_device_id(name)
        return self._local_device_id()

    def _local_kwargs(self) -> dict:
        return {"device_id": self._playback_device_id()}

    def activate_local_player(self) -> str:
        """Startet den lokalen Player, wartet auf das Connect-Gerät und transferiert die Wiedergabe."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))

        device_id = self._local_device_id()
        sp.transfer_playback(device_id=device_id, force_play=False)
        return device_id

    # Spotify akzeptiert pro start_playback nur eine begrenzte URI-Liste.
    _MAX_URIS = 100

    def _uri_window(self, track_uris: list[str], position: int) -> tuple[list[str], int]:
        """Liefert ein bis zu 100 Titel großes Fenster um ``position`` (für lange Listen)."""
        if len(track_uris) <= self._MAX_URIS:
            return track_uris, max(0, min(position, len(track_uris) - 1))
        # Etwas Vorlauf behalten, damit „vorheriger Titel" weiter funktioniert.
        start = max(0, min(position - 25, len(track_uris) - self._MAX_URIS))
        return track_uris[start:start + self._MAX_URIS], position - start

    def start_playback(
        self,
        uri: str | None = None,
        context_uri: str | None = None,
        track_uris: list[str] | None = None,
        position: int = 0,
        position_ms: int = 0,
    ) -> bool:
        """Startet oder setzt die Wiedergabe fort (nur lokaler librespot-Player).

        librespot löst ein ``context_uri`` (Album/Playlist) nicht zuverlässig
        auf – es spielt dann nur den Einzeltitel und fällt danach in Spotifys
        Autoplay. Darum wird bei Album-/Playlist-Wiedergabe die **explizite
        Titelliste** (``track_uris``) mit Positions-Offset übergeben; so
        navigieren Vor/Zurück zuverlässig innerhalb des Albums/der Playlist.

        Der Autoplay-Modus steuert, was bei *einzelnen* Titeln passiert:
          * ``off``     – nur der gewählte Titel.
          * ``context`` – aus Album/Playlist gestartete Titel laufen im Kontext
                          weiter; lose Einzeltitel nicht.
          * ``all``     – wie ``context``; zusätzlich reihen lose Einzeltitel die
                          folgenden Titel der Liste an.
        """
        sp = self.get()
        if not sp:
            return False
        autoplay = cfg.get_autoplay()
        try:
            kwargs: dict = self._local_kwargs()
            single = bool(uri and (uri.startswith("spotify:track") or uri.startswith("spotify:episode")))
            if uri and uri.startswith("spotify:show"):
                # Die Web API akzeptiert als context_uri nur Album, Künstler und
                # Playlist – ein Show-URI führt zu HTTP 400. Podcasts werden
                # darum als Episodenliste geöffnet (siehe browse_common).
                raise RuntimeError(
                    _("Podcasts lassen sich nicht direkt abspielen.\n"
                    "Öffnen Sie den Podcast mit Enter und wählen Sie eine Episode.")
                )
            if uri:
                if not single:
                    # Album/Playlist/Künstler direkt: als Kontext abspielen.
                    kwargs["context_uri"] = uri
                elif autoplay == "off" or not track_uris:
                    kwargs["uris"] = [uri]
                elif context_uri:
                    # Aus Album/Playlist gestartet → komplette Titelliste mit Offset.
                    window, offset = self._uri_window(track_uris, position)
                    kwargs["uris"] = window or [uri]
                    kwargs["offset"] = {"position": offset}
                elif autoplay == "all":
                    # Loser Einzeltitel: ab hier die folgenden Titel mitspielen.
                    kwargs["uris"] = track_uris[position:position + self._MAX_URIS] or [uri]
                else:
                    kwargs["uris"] = [uri]
            if position_ms:
                # Episoden dort fortsetzen, wo der Nutzer aufgehört hat.
                kwargs["position_ms"] = int(position_ms)
            sp.start_playback(**kwargs)
            return True
        except Exception as e:
            error_msg = str(e)
            if "No active device" in error_msg or "404" in error_msg:
                device = cfg.get_playback_device()
                if device:
                    raise Exception(
                        _("Das Wiedergabegerät „{device}“ hat den Befehl nicht angenommen.\nPrüfen Sie, ob es noch online ist, oder wählen Sie unter 'Extras > Wiedergabegerät …' ein anderes Gerät.").format(device=device)
                    )
                raise Exception(
                    _("Der lokale Spotify-Player ist noch nicht als Gerät verfügbar.\n"
                    "Starten Sie ihn über 'Extras > Lokalen Player starten' oder versuchen Sie es erneut.")
                )
            raise e

    def pause_playback(self) -> bool:
        """Pausiert die Wiedergabe."""
        sp = self.get()
        if not sp:
            return False
        device_id = self._playback_device_id()
        sp.pause_playback(device_id=device_id)
        return True

    def toggle_play_pause(self) -> bool:
        """Schaltet zwischen Pause und Wiedergabe um."""
        sp = self.get()
        if not sp:
            return False
        device_id = self._playback_device_id()
        playback = sp.current_playback()
        playback_device = (playback or {}).get("device") or {}
        if playback_device.get("id") == device_id and playback.get("is_playing"):
            sp.pause_playback(device_id=device_id)
            return True
        return self.start_playback()

    def next_track(self) -> bool:
        """Springt zum nächsten Titel."""
        sp = self.get()
        if not sp:
            return False
        sp.next_track(**self._local_kwargs())
        return True

    def previous_track(self) -> bool:
        """Springt zum vorherigen Titel."""
        sp = self.get()
        if not sp:
            return False
        sp.previous_track(**self._local_kwargs())
        return True

    def current_track_name(self, settle_delay: float = 0.4) -> str | None:
        """Liefert 'Interpret - Titel' der aktuellen Wiedergabe (für Fenstertitel/Ansage)."""
        sp = self.get()
        if not sp:
            return None
        # Kurz warten, damit ein gerade ausgelöster Titelwechsel registriert ist.
        if settle_delay:
            time.sleep(settle_delay)
        playback = sp.current_playback()
        item = (playback or {}).get("item") or {}
        name = item.get("name")
        if not name:
            return None
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        return f"{artists} - {name}" if artists else name

    def now_playing(self) -> dict | None:
        """Liefert Infos zur aktuellen Wiedergabe für die Ansage (oder None)."""
        sp = self.get()
        if not sp:
            return None
        playback = sp.current_playback()
        if not playback:
            return None
        item = playback.get("item") or {}
        name = item.get("name")
        if not name:
            return None
        if item.get("type") == "episode":
            show = item.get("show") or {}
            artists = show.get("publisher", "")
            album = show.get("name", "")
        else:
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            album = (item.get("album") or {}).get("name", "")
        return {
            "title": name,
            "artists": artists,
            "album": album,
            "progress_ms": playback.get("progress_ms") or 0,
            "duration_ms": item.get("duration_ms") or 0,
            "is_playing": bool(playback.get("is_playing")),
            "shuffle_state": bool(playback.get("shuffle_state")),
            "repeat_state": playback.get("repeat_state", "off"),
        }

    def change_volume(self, delta: int) -> int | None:
        """Ändert die Lautstärke und gibt den neuen Wert zurück."""
        sp = self.get()
        if not sp:
            return None

        device_id = self._playback_device_id()
        current_volume = None
        devices = sp.devices().get("devices", [])
        for device in devices:
            if device.get("id") == device_id:
                current_volume = device.get("volume_percent")
                break

        if current_volume is None:
            current_volume = 50

        new_volume = max(0, min(100, current_volume + delta))
        sp.volume(new_volume, device_id=device_id)
        return new_volume

    def set_shuffle(self, state: bool | None = None) -> bool | None:
        """Schaltet die Zufallswiedergabe (ohne Argument: umschalten)."""
        sp = self.get()
        if not sp:
            return None
        device_id = self._playback_device_id()
        if state is None:
            playback = sp.current_playback() or {}
            state = not bool(playback.get("shuffle_state"))
        sp.shuffle(bool(state), device_id=device_id)
        return bool(state)

    # Reihenfolge beim Durchschalten der Wiederholung.
    REPEAT_ORDER = ("off", "context", "track")

    def cycle_repeat(self) -> str | None:
        """Schaltet die Wiederholung weiter: aus → alle → Titel → aus."""
        sp = self.get()
        if not sp:
            return None
        device_id = self._playback_device_id()
        playback = sp.current_playback() or {}
        current = playback.get("repeat_state", "off")
        index = self.REPEAT_ORDER.index(current) if current in self.REPEAT_ORDER else 0
        state = self.REPEAT_ORDER[(index + 1) % len(self.REPEAT_ORDER)]
        sp.repeat(state, device_id=device_id)
        return state

    def seek_relative(self, delta_ms: int) -> tuple[int, int] | None:
        """Spult um ``delta_ms`` vor/zurück; liefert (neue Position, Dauer)."""
        sp = self.get()
        if not sp:
            return None
        playback = sp.current_playback()
        if not playback or not playback.get("item"):
            return None
        duration = playback["item"].get("duration_ms") or 0
        position = (playback.get("progress_ms") or 0) + delta_ms
        position = max(0, min(position, max(0, duration - 1000)))
        sp.seek_track(int(position), device_id=self._playback_device_id())
        return int(position), int(duration)

    def add_to_queue(self, uri: str) -> bool:
        """Reiht einen Titel/eine Episode in die Warteschlange des lokalen Players ein."""
        sp = self.get()
        if not sp:
            return False
        sp.add_to_queue(uri, device_id=self._local_device_id())
        return True

    def _current_user_id(self) -> str | None:
        """Liefert (und cacht) die Spotify-User-ID des angemeldeten Kontos."""
        if self._user_id:
            return self._user_id
        sp = self.get()
        if not sp:
            return None
        try:
            self._user_id = (sp.me() or {}).get("id")
        except Exception:
            self._user_id = None
        return self._user_id

    def editable_playlists(self) -> list[dict]:
        """Listet Playlists, in die der Nutzer Titel hinzufügen darf (eigene + kollaborative)."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        me = self._current_user_id()
        editable: list[dict] = []
        all_playlists: list[dict] = []
        page = sp.current_user_playlists(limit=50)
        while page:
            for item in page.get("items", []) or []:
                if not item:
                    continue
                entry = {"id": item["id"], "name": item.get("name", "")}
                all_playlists.append(entry)
                owner_id = (item.get("owner") or {}).get("id")
                if item.get("collaborative") or (me and owner_id == me):
                    editable.append(entry)
            if not page.get("next"):
                break
            page = sp.next(page)
        # Konnte die eigene User-ID nicht ermittelt werden (z. B. fehlende
        # Berechtigung), lieber alle Playlists anbieten als gar keine.
        if not editable and me is None:
            return all_playlists
        return editable

    def album_track_uris(self, album_id: str) -> list[str]:
        """Liefert alle Titel-URIs eines Albums in Reihenfolge."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        album = sp.album(album_id)
        uris: list[str] = []
        page = album.get("tracks")
        while page:
            for track in page.get("items", []) or []:
                if track and track.get("uri"):
                    uris.append(track["uri"])
            if not page.get("next"):
                break
            page = sp.next(page)
        return uris

    def playlist_track_uris(self, playlist_id: str) -> list[str]:
        """Liefert alle Titel-URIs einer Playlist in Reihenfolge."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        uris: list[str] = []
        page = sp.playlist_items(playlist_id, fields="next,items(track(uri))", limit=100)
        while page:
            for item in page.get("items", []) or []:
                track = (item or {}).get("track") or {}
                if track.get("uri"):
                    uris.append(track["uri"])
            if not page.get("next"):
                break
            page = sp.next(page)
        return uris

    def play_uris(self, uris: list[str]) -> int:
        """Spielt eine geordnete Liste von Titel-URIs ab; liefert deren Anzahl.

        Spotify akzeptiert pro ``start_playback`` maximal 100 URIs. Längere
        Listen werden gekürzt – der Rückgabewert nennt darum die tatsächlich
        übergebene Anzahl, damit die UI das ehrlich ansagen kann.
        """
        sp = self.get()
        if not sp:
            return 0
        uris = [uri for uri in uris if uri]
        if not uris:
            return 0
        kwargs = self._local_kwargs()
        kwargs["uris"] = uris[:self._MAX_URIS]
        sp.start_playback(**kwargs)
        return len(kwargs["uris"])

    def current_queue(self) -> dict:
        """Liefert die aktuelle Spotify-Warteschlange (currently_playing + queue)."""
        sp = self.get()
        if not sp:
            return {}
        try:
            return sp.queue() or {}
        except Exception:
            return {}

    def is_in_library(self, item_type: str, item_id: str) -> bool | None:
        """Prüft, ob ein Element gespeichert ist bzw. ihm gefolgt wird."""
        sp = self.get()
        if not sp or not item_id:
            return None
        if item_type == "artist":
            result = sp.current_user_following_artists([item_id])
            return bool(result and result[0])
        if item_type == "playlist":
            me = self._current_user_id()
            if not me:
                return None
            result = sp.playlist_is_following(item_id, [me])
            return bool(result and result[0])
        endpoints = _LIBRARY_ENDPOINTS.get(item_type)
        if not endpoints:
            return None
        result = getattr(sp, endpoints[0])([item_id])
        return bool(result and result[0])

    def set_in_library(self, item_type: str, item_id: str, saved: bool) -> bool:
        """Speichert ein Element in der Mediathek bzw. entfernt es wieder."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        if not item_id:
            return False
        if item_type == "artist":
            if saved:
                sp.user_follow_artists([item_id])
            else:
                sp.user_unfollow_artists([item_id])
            return True
        if item_type == "playlist":
            if saved:
                sp.current_user_follow_playlist(item_id)
            else:
                sp.current_user_unfollow_playlist(item_id)
            return True
        endpoints = _LIBRARY_ENDPOINTS.get(item_type)
        if not endpoints:
            return False
        getattr(sp, endpoints[1] if saved else endpoints[2])([item_id])
        return True

    def playlist_details(self, playlist_id: str) -> dict:
        """Liefert Name, Beschreibung und Besitzverhältnisse einer Playlist."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        data = sp.playlist(
            playlist_id,
            fields="id,name,description,collaborative,snapshot_id,owner(id,display_name)",
        ) or {}
        owner = data.get("owner") or {}
        return {
            "id": data.get("id", playlist_id),
            "name": data.get("name", ""),
            "description": data.get("description", "") or "",
            "collaborative": bool(data.get("collaborative")),
            "snapshot_id": data.get("snapshot_id", ""),
            "owner_id": owner.get("id", ""),
            "owner_name": owner.get("display_name", ""),
        }

    def playlist_is_editable(self, playlist_id: str) -> bool:
        """Prüft, ob der angemeldete Nutzer diese Playlist ändern darf."""
        details = self.playlist_details(playlist_id)
        me = self._current_user_id()
        return bool(details["collaborative"] or (me and details["owner_id"] == me))

    def update_playlist_details(
        self, playlist_id: str, name: str | None = None, description: str | None = None
    ) -> bool:
        """Ändert Name und/oder Beschreibung einer Playlist."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        kwargs = {}
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError(_("Der Name der Playlist darf nicht leer sein."))
            kwargs["name"] = name
        if description is not None:
            kwargs["description"] = description.strip()
        if not kwargs:
            return False
        sp.playlist_change_details(playlist_id, **kwargs)
        return True

    def remove_playlist_positions(self, playlist_id: str, entries: list[tuple[str, int]]) -> int:
        """Entfernt Titel an genau diesen Positionen aus der Playlist.

        Es wird bewusst positionsgenau gelöscht: Steht derselbe Titel mehrfach
        in der Playlist, verschwindet sonst jedes Vorkommen.
        """
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        entries = [(uri, position) for uri, position in entries if uri and position is not None]
        if not entries:
            return 0
        snapshot = self.playlist_details(playlist_id).get("snapshot_id") or None
        items = [{"uri": uri, "positions": [int(position)]} for uri, position in entries]
        sp.playlist_remove_specific_occurrences_of_items(playlist_id, items, snapshot_id=snapshot)
        return len(items)

    def reorder_playlist(self, playlist_id: str, position: int, insert_before: int) -> bool:
        """Verschiebt einen Titel innerhalb der Playlist."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        if position == insert_before or position + 1 == insert_before:
            return False
        sp.playlist_reorder_items(playlist_id, position, insert_before, range_length=1)
        return True

    def create_playlist(self, name: str, public: bool = False, description: str = "") -> dict:
        """Legt eine neue Playlist im Konto des Nutzers an."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        name = (name or "").strip()
        if not name:
            raise ValueError(_("Bitte einen Namen für die Playlist eingeben."))
        created = sp.current_user_playlist_create(name, public=public, description=description) or {}
        return {"id": created.get("id"), "name": created.get("name", name)}

    def recently_played(self, limit: int = 50) -> list[dict]:
        """Liefert die zuletzt gehörten Titel (neueste zuerst, ohne Duplikate)."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        results = sp.current_user_recently_played(limit=min(50, limit)) or {}
        tracks = []
        seen = set()
        for entry in results.get("items", []) or []:
            track = (entry or {}).get("track") or {}
            uri = track.get("uri")
            if not uri or uri in seen:
                continue
            seen.add(uri)
            tracks.append(track)
        return tracks

    def queue_snapshot(self) -> tuple[dict | None, list[dict]]:
        """Liefert (laufender Titel, kommende Titel) aus Spotifys Warteschlange."""
        sp = self.get()
        if not sp:
            return None, []
        data = sp.queue() or {}
        return data.get("currently_playing"), [item for item in (data.get("queue") or []) if item]

    def add_tracks_to_playlist(self, playlist_id: str, uris: list[str]) -> int:
        """Fügt Titel/Episoden zu einer Playlist hinzu und gibt deren Anzahl zurück."""
        sp = self.get()
        if not sp:
            raise RuntimeError(_("Zuerst autorisieren!"))
        uris = [uri for uri in uris if uri]
        if not uris:
            return 0
        # Spotify erlaubt maximal 100 URIs pro Aufruf.
        for start in range(0, len(uris), 100):
            sp.playlist_add_items(playlist_id, uris[start:start + 100])
        return len(uris)


# Modul-weite Instanz — wird von allen UI-Modulen importiert
client = SpotifyClient()
