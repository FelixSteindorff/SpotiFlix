"""
Anwendungsprotokoll für Fehler und wichtige Ereignisse.

Fehler erscheinen in der Oberfläche als Meldung und sind danach weg – für die
Fehlersuche ist das zu wenig. Dieses Modul hält die letzten Einträge im
Speicher (für den Protokoll-Dialog) und schreibt sie zusätzlich in
``~/.spotiflix.log``, damit sie einen Neustart überleben. Die Datei wird bei
Überschreiten von ``MAX_LOG_BYTES`` rotiert und wächst darum nicht unbegrenzt.

Das Protokoll ist bewusst anspruchslos: Es darf nie selbst eine Ausnahme
auslösen und wird aus beliebigen Threads aufgerufen.
"""
import os
import threading
import time
from collections import deque

from i18n import _

LOG_FILE = os.path.expanduser("~/.spotiflix.log")
MAX_LOG_BYTES = 500_000
#: So viele Einträge hält der Dialog im Speicher vor.
MAX_ENTRIES = 300

_entries: deque = deque(maxlen=MAX_ENTRIES)
_lock = threading.Lock()


def _rotate():
    """Rotiert die Protokolldatei, bevor sie zu groß wird."""
    try:
        if os.path.getsize(LOG_FILE) < MAX_LOG_BYTES:
            return
    except OSError:
        return
    try:
        os.replace(LOG_FILE, LOG_FILE + ".1")
    except OSError:
        pass


def log(level: str, context: str, message: str):
    """Schreibt einen Eintrag ins Protokoll (Speicher und Datei)."""
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "context": context,
        "message": " ".join(str(message).split()),
    }
    with _lock:
        _entries.append(entry)
        try:
            _rotate()
            with open(LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(f"{entry['time']}\t{level}\t{context}\t{entry['message']}\n")
        except Exception:
            # Ein kaputtes Protokoll darf die App nicht stören.
            pass
    return entry


def info(context: str, message: str):
    return log("Info", context, message)


def error(context: str, message) -> dict:
    """Protokolliert einen Fehler; ``message`` darf auch eine Exception sein."""
    if isinstance(message, BaseException):
        message = f"{type(message).__name__}: {message}"
    return log("Fehler", context, message)


def short_error(error, limit: int = 140, hint: bool = True) -> str:
    """Kürzt eine Fehlermeldung auf eine ansagbare Zeile.

    Bibliotheken werfen gelegentlich mehrzeilige Meldungen mit Links und
    Handlungsanweisungen. In der Statusleiste und in der Sprachausgabe ist
    davon nur der Anfang brauchbar – der vollständige Text steht im Protokoll.
    ``hint=False`` lässt den Hinweis auf das Protokoll weg (z. B. in der
    Statusleiste, die ohnehin nicht vorgelesen wird).
    """
    if error is None:
        return _("Unbekannter Fehler")
    text = str(error).strip()
    if not text:
        return _("Unbekannter Fehler")
    first_line = " ".join(text.splitlines()[0].split())
    truncated = len(text.splitlines()) > 1 or len(first_line) > limit
    if len(first_line) > limit:
        first_line = first_line[:limit].rstrip(" ,;:.") + " …"
    if truncated and hint:
        first_line += _(" (Details: Protokoll, Strg+Umschalt+G)")
    return first_line


def entries() -> list[dict]:
    """Liefert die gesammelten Einträge, neueste zuerst."""
    with _lock:
        return list(reversed(_entries))


def clear():
    """Leert Speicher und Protokolldatei."""
    with _lock:
        _entries.clear()
        try:
            open(LOG_FILE, "w", encoding="utf-8").close()
        except OSError:
            pass


def summary() -> str:
    """Fasst das Protokoll als Text zusammen (für die Zwischenablage)."""
    lines = [f"{e['time']}\t{e['level']}\t{e['context']}\t{e['message']}" for e in entries()]
    return "\n".join(lines)
