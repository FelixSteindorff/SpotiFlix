"""
Optionale Sprach- und Brailleausgabe für Barrierefreiheit.

Bevorzugt den NVDA Controller Client (``nvdaControllerClient*.dll``) und lässt
NVDA Statusmeldungen – etwa die Lautstärke in Prozent – direkt vorlesen und auf
der Braillezeile anzeigen. Ist NVDA bzw. die DLL nicht erreichbar, wird auf die
Windows-Sprachausgabe (SAPI5 über ``win32com``) zurückgegriffen, damit Ansagen
trotzdem hörbar sind.

Die NVDA-DLL wird im Projektverzeichnis, im Arbeitsverzeichnis, im NVDA-
Installationsordner und im PATH gesucht. NVDA liefert sie als Teil des separat
erhältlichen „NVDA Controller Client". Ist nichts davon verfügbar, verhält sich
das Modul still: Aufrufe geben einfach ``False`` zurück.

Wichtig für die Bedienung: ``interrupt`` steuert, ob eine bereits laufende
Ansage abgebrochen wird. Standard ist ``False`` – sonst würde jede Statusmeldung
NVDAs eigene Fokusansage (z. B. den gerade angesteuerten Listeneintrag)
mittendrin abschneiden. Nur bei schnell wiederholten Ansagen desselben Werts –
etwa der Lautstärke – ist ``interrupt=True`` richtig, damit sofort die aktuelle
Zahl kommt statt einer Warteschlange alter Werte.
"""
import ctypes
import os
import sys

_DLL_NAMES = (
    "nvdaControllerClient64.dll",
    "nvdaControllerClient32.dll",
    "nvdaControllerClient.dll",
)

_controller = None
_nvda_loaded = False
_sapi = None
_sapi_tried = False

# SAPI-Sprechflags: 1 = asynchron, 2 = laufende Ansage vorher abbrechen.
_SAPI_ASYNC = 1
_SAPI_PURGE = 2


def _nvda_search_dirs() -> list[str]:
    """Suchreihenfolge für die Controller-DLL.

    Die DLL einer installierten NVDA-Version kommt zuerst: Sie ist aktuell,
    während die im Projekt mitgelieferte Kopie alt sein kann. Erst danach
    kommen Projektordner, Arbeitsverzeichnis und – im PyInstaller-Build – der
    entpackte Bundle-Ordner bzw. der Ordner neben der Exe.
    """
    dirs = []
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            dirs.append(os.path.join(base, "NVDA"))
            dirs.append(os.path.join(base, "NVDA", "controllerClient"))
    dirs.append(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.getcwd())
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            dirs.append(meipass)
        dirs.append(os.path.dirname(sys.executable))
    return dirs


def _load_nvda():
    """Lädt die NVDA-Controller-DLL einmalig (lazy)."""
    global _controller, _nvda_loaded
    if _nvda_loaded:
        return _controller
    _nvda_loaded = True

    if os.name != "nt":
        return None

    candidates = [os.path.join(d, name) for d in _nvda_search_dirs() for name in _DLL_NAMES]
    candidates += list(_DLL_NAMES)  # zuletzt: über PATH auflösen lassen

    for candidate in candidates:
        try:
            _controller = ctypes.windll.LoadLibrary(candidate)
            return _controller
        except Exception:
            continue
    return None


def _nvda_running() -> bool:
    lib = _load_nvda()
    if not lib:
        return False
    try:
        # testIfRunning() liefert 0, wenn NVDA läuft.
        return lib.nvdaController_testIfRunning() == 0
    except Exception:
        return False


def _load_sapi():
    """Lädt die Windows-Sprachausgabe (SAPI5) einmalig (lazy)."""
    global _sapi, _sapi_tried
    if _sapi_tried:
        return _sapi
    _sapi_tried = True
    if os.name != "nt":
        return None
    try:
        import win32com.client

        _sapi = win32com.client.Dispatch("SAPI.SpVoice")
    except Exception:
        _sapi = None
    return _sapi


def output_name() -> str:
    """Beschreibt die aktive Ausgabe – für die Diagnose im Über-Dialog."""
    if _nvda_running():
        return "NVDA"
    if _load_sapi() is not None:
        return "Windows-Sprachausgabe (SAPI5)"
    return "keine"


def speak(text: str, interrupt: bool = False) -> bool:
    """Spricht ``text`` – bevorzugt über NVDA, sonst über SAPI5.

    ``interrupt=True`` bricht eine laufende Ansage ab (nur für schnell
    wiederholte Werte wie die Lautstärke sinnvoll). Gibt True zurück, wenn die
    Ansage abging.
    """
    if not text:
        return False

    lib = _load_nvda()
    if lib:
        try:
            if lib.nvdaController_testIfRunning() == 0:
                if interrupt:
                    try:
                        lib.nvdaController_cancelSpeech()
                    except Exception:
                        pass
                lib.nvdaController_speakText(ctypes.c_wchar_p(text))
                return True
        except Exception:
            pass

    sapi = _load_sapi()
    if sapi:
        try:
            flags = _SAPI_ASYNC | (_SAPI_PURGE if interrupt else 0)
            sapi.Speak(text, flags)
            return True
        except Exception:
            pass

    return False


def braille(text: str) -> bool:
    """Zeigt ``text`` auf der NVDA-Braillezeile an (SAPI kennt keine Braille-Ausgabe)."""
    if not text:
        return False
    lib = _load_nvda()
    if not lib:
        return False
    try:
        if lib.nvdaController_testIfRunning() != 0:
            return False
        lib.nvdaController_brailleMessage(ctypes.c_wchar_p(text))
        return True
    except Exception:
        return False


def announce(text: str, interrupt: bool = False) -> bool:
    """Gibt ``text`` gleichzeitig als Sprache und auf der Braillezeile aus.

    Taubblinde Nutzer erhalten so dieselben Statusmeldungen wie hörende.
    """
    spoken = speak(text, interrupt=interrupt)
    brailled = braille(text)
    return spoken or brailled
