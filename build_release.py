"""
Baut die Windows-Auslieferung: portables ZIP und Installationsprogramm.

    py build_release.py                 # alles, was möglich ist
    py build_release.py --skip-installer
    py build_release.py --skip-build    # nur verpacken, ohne PyInstaller

Ablauf:
  1. Übersetzungskataloge kompilieren (.po -> .mo)
  2. PyInstaller im One-Dir-Modus über SpotiFlix.spec
  3. dist\\SpotiFlix als SpotiFlix-<version>-portable-win64.zip verpacken
  4. Installationsprogramm über Inno Setup (falls vorhanden)
  5. SHA-256 der Ergebnisse ausgeben

Inno Setup ist optional. Fehlt es, entsteht nur das portable Archiv, und der
Grund steht am Ende der Ausgabe.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile

from version import APP_NAME, VERSION

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
BUNDLE = os.path.join(DIST, APP_NAME)
PORTABLE = os.path.join(DIST, f"{APP_NAME}-{VERSION}-portable-win64.zip")
INSTALLER = os.path.join(DIST, f"{APP_NAME}-{VERSION}-Setup.exe")
ISS = os.path.join(ROOT, "packaging", "spotiflix.iss")

# winget installiert Inno Setup ins Benutzerprofil, nicht nach Program Files.
ISCC_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
]


def step(text: str):
    print(f"\n=== {text}")


def run(command: list[str]) -> int:
    print("   ", " ".join(command))
    return subprocess.run(command, cwd=ROOT).returncode


def find_iscc() -> str | None:
    """Sucht den Inno-Setup-Compiler im PATH und an den üblichen Orten."""
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    for candidate in ISCC_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def running_instance() -> bool:
    """Prüft, ob eine gebaute SpotiFlix-Instanz läuft (sie sperrt die Dateien)."""
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {APP_NAME}.exe", "/NH"],
        capture_output=True, text=True, errors="replace",
    )
    return f"{APP_NAME}.exe" in (result.stdout or "")


def make_portable() -> str:
    """Packt den One-Dir-Build als ZIP, mit dem Programmordner als Wurzel."""
    if os.path.exists(PORTABLE):
        os.remove(PORTABLE)
    with zipfile.ZipFile(PORTABLE, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for base, _dirs, files in os.walk(BUNDLE):
            for name in files:
                full = os.path.join(base, name)
                # Im Archiv liegt alles unter "SpotiFlix/", damit das Entpacken
                # keinen Wildwuchs im Zielordner hinterlässt.
                archive.write(full, os.path.join(APP_NAME, os.path.relpath(full, BUNDLE)))
    return PORTABLE


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows-Auslieferung bauen")
    parser.add_argument("--skip-build", action="store_true", help="PyInstaller überspringen")
    parser.add_argument("--skip-installer", action="store_true", help="Inno Setup überspringen")
    arguments = parser.parse_args()

    print(f"{APP_NAME} {VERSION}")

    if running_instance():
        print(f"\nFEHLER: {APP_NAME}.exe läuft noch und sperrt die Dateien in dist.")
        print("Bitte die Anwendung schließen und erneut starten.")
        return 1

    step("Übersetzungskataloge kompilieren")
    if run([sys.executable, os.path.join("tools", "i18n_tool.py"), "compile"]):
        return 1

    if not arguments.skip_build:
        step("PyInstaller")
        if run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                f"{APP_NAME}.spec"]):
            return 1

    if not os.path.isdir(BUNDLE):
        print(f"\nFEHLER: {BUNDLE} fehlt – erst bauen, dann verpacken.")
        return 1

    step("Portables Archiv")
    make_portable()
    print("   ", os.path.relpath(PORTABLE, ROOT))

    installer_note = ""
    if arguments.skip_installer:
        installer_note = "übersprungen (--skip-installer)"
    else:
        iscc = find_iscc()
        if not iscc:
            installer_note = (
                "Inno Setup nicht gefunden – ohne ISCC.exe entsteht kein Setup.\n"
                "    Installation: winget install JRSoftware.InnoSetup"
            )
        else:
            step("Installationsprogramm (Inno Setup)")
            if run([iscc, f"/DMyAppVersion={VERSION}", ISS]):
                return 1

    step("Ergebnisse")
    for path in (PORTABLE, INSTALLER):
        if os.path.isfile(path):
            size = os.path.getsize(path) / (1024 * 1024)
            print(f"    {os.path.relpath(path, ROOT)}")
            print(f"      {size:.1f} MB   SHA-256 {sha256(path)}")
    if installer_note:
        print(f"\n    Setup: {installer_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
