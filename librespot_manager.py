# SpotiFlix – ein barrierefreier Spotify-Player für Windows.
# Copyright (C) 2026 Felix Steindorff
#
# Dieses Programm ist freie Software: Sie können es unter den Bedingungen
# der GNU General Public License, Version 3 oder (nach Ihrer Wahl) einer
# neueren Version, weitergeben und/oder verändern. Es wird ohne jede
# Gewährleistung bereitgestellt; siehe LICENSE für den vollen Text.

"""
LibrespotManager: Verwaltet den librespot-Prozess für lokale Audiowiedergabe.

librespot registriert sich als Spotify Connect-Gerät namens "SpotiFlix".
Die Spotify Web API kann dann Wiedergabe gezielt auf dieses Gerät senden.

Installation: cargo install librespot
              Oder librespot.exe ins Projektverzeichnis legen.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import atexit

import config as cfg

from i18n import _

DEVICE_NAME = "SpotiFlix"
LIBRESPOT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".spotiflix-librespot-cache")
# librespot liest seine Anmeldung aus dieser Datei im Cache-Verzeichnis.
CREDENTIALS_CACHE = os.path.join(LIBRESPOT_CACHE_DIR, "credentials.json")
# Wert von AuthenticationType.AUTHENTICATION_STORED_SPOTIFY_CREDENTIALS.
_AUTH_TYPE_STORED = 1
# Ab dieser Größe wird das librespot-Log rotiert (sonst wächst es unbegrenzt).
MAX_LOG_BYTES = 1_000_000


class LibrespotManager:
    """Startet und verwaltet einen librespot-Prozess als lokales Spotify-Wiedergabegerät."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stderr_log = os.path.join(os.path.expanduser("~"), ".spotiflix-librespot.log")
        # Ab welcher Stelle das Log zum aktuellen Lauf gehört. Ohne das würden
        # Fehlermeldungen und die Anmelde-Diagnose alte Läufe mitlesen.
        self._log_offset = 0

    def find_binary(self) -> str | None:
        """Sucht librespot: im PyInstaller-Bundle, neben der Exe, im
        Projektverzeichnis oder im PATH."""
        search_dirs = []
        if getattr(sys, "frozen", False):
            # PyInstaller: mitgelieferte Binärdatei (datas -> _MEIPASS) und
            # der Ordner neben der ausführbaren Datei.
            meipass = getattr(sys, "_MEIPASS", "")
            if meipass:
                search_dirs.append(meipass)
            search_dirs.append(os.path.dirname(sys.executable))
        # Entwicklungsmodus: Verzeichnis dieser Quelldatei.
        search_dirs.append(os.path.dirname(os.path.abspath(__file__)))

        for base in search_dirs:
            for name in ("librespot.exe", "librespot"):
                path = os.path.join(base, name)
                if os.path.isfile(path):
                    return path
        return shutil.which("librespot")

    def _seed_credentials(self) -> bool:
        """Übernimmt die librespot-Anmeldung in librespots eigenen Cache.

        Mit ``--access-token`` verweigert Spotify die Anmeldung als
        Connect-Gerät: librespot meldet sich zwar am Konto an, bricht dann aber
        mit „could not initialize spirc: Login request was denied:
        INVALID_CREDENTIALS" ab – ein Token unserer eigenen App-Registrierung
        darf kein Gerät anmelden. Die gespeicherten Zugangsdaten aus dem
        librespot-eigenen OAuth-Login dürfen es; die liegen dank der
        Download-Funktion ohnehin schon vor.
        """
        from librespot_download import CREDENTIALS_FILE

        if not os.path.isfile(CREDENTIALS_FILE):
            return False
        try:
            with open(CREDENTIALS_FILE, encoding="utf-8") as handle:
                source = json.load(handle)
            blob = {
                "username": source["username"],
                "auth_type": _AUTH_TYPE_STORED,
                "auth_data": source["credentials"],
            }
        except (OSError, ValueError, KeyError):
            return False

        try:
            if os.path.isfile(CREDENTIALS_CACHE):
                with open(CREDENTIALS_CACHE, encoding="utf-8") as handle:
                    if json.load(handle).get("auth_data") == blob["auth_data"]:
                        return True
        except (OSError, ValueError):
            pass

        try:
            os.makedirs(LIBRESPOT_CACHE_DIR, exist_ok=True)
            with open(CREDENTIALS_CACHE, "w", encoding="utf-8") as handle:
                json.dump(blob, handle)
        except OSError:
            return False
        return True

    def _ensure_credentials(self):
        """Sorgt dafür, dass librespot eine brauchbare Anmeldung im Cache hat."""
        if self._seed_credentials():
            return
        # Noch keine librespot-Anmeldung: einmalig über den Browser nachholen.
        # Danach gilt sie für Wiedergabe und Downloads gleichermaßen.
        from librespot_download import ensure_login

        ensure_login()
        if not self._seed_credentials():
            raise ValueError(
                _("Für den lokalen Player fehlt die librespot-Anmeldung.\n"
                "Sie öffnet sich einmalig im Browser – bitte dort bestätigen "
                "und den Player erneut starten.")
            )

    def reset_login(self) -> None:
        """Verwirft die librespot-Anmeldung, damit sie neu erfolgen kann."""
        from librespot_download import CREDENTIALS_FILE

        self.stop()
        for path in (CREDENTIALS_CACHE, CREDENTIALS_FILE):
            try:
                os.remove(path)
            except OSError:
                pass

    def login_problem(self) -> bool:
        """Deutet das letzte Log auf abgelehnte Zugangsdaten hin?"""
        log = self.last_log()
        return "INVALID_CREDENTIALS" in log or "Login request was denied" in log

    def start(self) -> None:
        """Startet librespot als lokales Wiedergabegerät. Wirft Exception bei Fehler."""
        with self._lock:
            if self.is_running():
                return

            binary = self.find_binary()
            if not binary:
                raise FileNotFoundError(
                    "librespot nicht gefunden.\n\n"
                    "Installation via Rust:\n"
                    "  cargo install librespot\n\n"
                    "Oder librespot.exe ins Projektverzeichnis legen."
                )

            os.makedirs(LIBRESPOT_CACHE_DIR, exist_ok=True)
            self._ensure_credentials()

            # Bewusst ohne --access-token: librespot meldet sich aus dem Cache
            # an (siehe _seed_credentials), sonst lehnt Spotify die
            # Geräteregistrierung ab.
            cmd = [
                binary,
                "--name", DEVICE_NAME,
                "--cache", LIBRESPOT_CACHE_DIR,
                "--bitrate", cfg.get_playback_quality(),
                "--initial-volume", str(cfg.get_initial_volume()),
                "--disable-audio-cache",
            ]
            if cfg.get_volume_normalisation():
                # Gleicht Lautstärkeunterschiede zwischen Alben aus.
                cmd.append("--enable-volume-normalisation")

            # Unter Windows verhindert CREATE_NO_WINDOW das separate
            # Konsolenfenster von librespot (Konsolen-Anwendung).
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW

            self._rotate_log()
            try:
                self._log_offset = os.path.getsize(self._stderr_log)
            except OSError:
                self._log_offset = 0
            stderr = open(self._stderr_log, "ab", buffering=0)
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                creationflags=creationflags,
            )
            stderr.close()

            # Warten, bis der Prozess sicher gestartet ist. Die Registrierung als
            # Spotify-Connect-Gerät prüft SpotifyClient über die Web API.
            time.sleep(1.0)

            if self._process.poll() is not None:
                err = self.last_log()
                self._process = None
                raise RuntimeError(_("librespot konnte nicht gestartet werden:\n\n{err}").format(err=err))

    def stop(self) -> None:
        """Stoppt den librespot-Prozess."""
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None

    def _rotate_log(self):
        """Rotiert das librespot-Log, bevor es unbegrenzt anwächst.

        Die letzte Generation bleibt als ``.1`` erhalten – genug für die
        Fehlersuche, ohne nach Monaten hunderte MB zu belegen.
        """
        try:
            if os.path.getsize(self._stderr_log) < MAX_LOG_BYTES:
                return
        except OSError:
            return
        previous = self._stderr_log + ".1"
        try:
            os.replace(self._stderr_log, previous)
        except OSError:
            # Läuft das Umbenennen nicht (Datei in Benutzung), lieber leeren
            # als das Log unbegrenzt wachsen lassen.
            try:
                open(self._stderr_log, "wb").close()
            except OSError:
                pass

    def last_log(self, max_bytes: int = 6000) -> str:
        """Liefert die Logzeilen des aktuellen librespot-Laufs."""
        try:
            with open(self._stderr_log, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                start = max(self._log_offset, size - max_bytes)
                handle.seek(min(start, size))
                return handle.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    def is_running(self) -> bool:
        """Gibt an, ob librespot aktuell läuft."""
        return self._process is not None and self._process.poll() is None


# Modul-weite Instanz
librespot = LibrespotManager()
atexit.register(librespot.stop)
