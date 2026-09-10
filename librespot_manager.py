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

DEVICE_NAME = "SpotiFlix"
LIBRESPOT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".spotiflix-librespot-cache")
# Ab dieser Größe wird das librespot-Log rotiert (sonst wächst es unbegrenzt).
MAX_LOG_BYTES = 1_000_000


class LibrespotManager:
    """Startet und verwaltet einen librespot-Prozess als lokales Spotify-Wiedergabegerät."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stderr_log = os.path.join(os.path.expanduser("~"), ".spotiflix-librespot.log")

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

    def _read_access_token(self) -> str | None:
        """Liest den aktuellen Access-Token aus dem spotipy-Token-Cache."""
        try:
            with open(cfg.TOKEN_FILE, encoding="utf-8") as f:
                token_info = json.load(f)
                scope = token_info.get("scope", "")
                scopes = set(scope.split()) if isinstance(scope, str) else set(scope or [])
                if "streaming" not in scopes:
                    raise ValueError(
                        "Der gespeicherte Spotify-Token enthält nicht den Scope 'streaming'.\n"
                        "Bitte über 'Hilfe > Autorisieren' erneut autorisieren."
                    )
                return token_info.get("access_token")
        except Exception:
            raise

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

            try:
                token = self._read_access_token()
            except FileNotFoundError:
                raise ValueError(
                    "Kein Zugriffstoken vorhanden.\n"
                    "Bitte zuerst über 'Hilfe > Autorisieren' mit Spotify verbinden."
                )

            if not token:
                raise ValueError("Kein Spotify-Access-Token vorhanden.")

            os.makedirs(LIBRESPOT_CACHE_DIR, exist_ok=True)

            cmd = [
                binary,
                "--name", DEVICE_NAME,
                "--cache", LIBRESPOT_CACHE_DIR,
                "--access-token", token,
                "--bitrate", cfg.get_playback_quality(),
                "--disable-audio-cache",
            ]

            # Unter Windows verhindert CREATE_NO_WINDOW das separate
            # Konsolenfenster von librespot (Konsolen-Anwendung).
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW

            self._rotate_log()
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
                raise RuntimeError(f"librespot konnte nicht gestartet werden:\n\n{err}")

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
        """Liefert die letzten librespot-Logzeilen für Fehlermeldungen."""
        try:
            with open(self._stderr_log, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - max_bytes))
                return handle.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    def is_running(self) -> bool:
        """Gibt an, ob librespot aktuell läuft."""
        return self._process is not None and self._process.poll() is None


# Modul-weite Instanz
librespot = LibrespotManager()
atexit.register(librespot.stop)
