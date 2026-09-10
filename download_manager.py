"""
Optionaler Download-Hook über spotdl.
"""
import os
import shutil
import subprocess
import re

import config as cfg

# Unter Windows verhindert CREATE_NO_WINDOW, dass für jeden Aufruf kurz ein
# Konsolenfenster aufblitzt (im PyInstaller-Windowed-Build sichtbar). Das stiehlt
# sonst den Fokus und wird von NVDA mitgelesen.
NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def get_item_url(item: dict) -> str:
    """Liefert eine Spotify-URL für ein API-Objekt."""
    external_urls = item.get("external_urls") or {}
    if external_urls.get("spotify"):
        return external_urls["spotify"]

    uri = item.get("uri", "")
    if uri.startswith("spotify:"):
        parts = uri.split(":")
        if len(parts) >= 3:
            return f"https://open.spotify.com/{parts[1]}/{parts[2]}"
    return ""


def _spotdl_output_template(output_dir: str) -> str:
    """Übersetzt SpotiFlix-Platzhalter in das spotdl-Ausgabeformat."""
    template = cfg.get_download_template()
    replacements = {
        "%artist%": "{artist}",
        "%artists%": "{artists}",
        "%album%": "{album}",
        "%title%": "{title}",
        "%num%": "{track-number}",
        "%num,2%": "{track-number}",
        "%disc%": "{disc-number}",
        "%year%": "{year}",
    }
    for source, target in replacements.items():
        template = template.replace(source, target)

    template = template.replace("\\", "/").strip("/")
    template = re.sub(r"/+", "/", template)
    if not template:
        template = cfg.DEFAULT_DOWNLOAD_TEMPLATE
        for source, target in replacements.items():
            template = template.replace(source, target)
    return os.path.join(output_dir, template)


class DownloadCancelled(Exception):
    """Wird ausgelöst, wenn der Nutzer einen laufenden Download abbricht."""


def download_item(item: dict, output_dir: str | None = None, progress_callback=None, cancel_event=None) -> str:
    """Lädt ein Spotify-Objekt mit der konfigurierten Methode herunter.

    ``progress_callback`` wird – soweit ermittelbar – mit (verarbeitet, gesamt)
    aufgerufen, damit die UI den Fortschritt ohne Blockieren anzeigen kann.
    ``cancel_event`` ist ein ``threading.Event``: Ist es gesetzt, bricht der
    Download an der nächsten Zwischenstation mit ``DownloadCancelled`` ab.
    """
    if cfg.get_download_method() == "librespot":
        from librespot_download import download_via_librespot
        return download_via_librespot(item, output_dir, progress_callback, cancel_event)
    return download_via_spotdl(item, output_dir, progress_callback, cancel_event)


def download_via_spotdl(item: dict, output_dir: str | None = None, progress_callback=None, cancel_event=None) -> str:
    """Startet spotdl für ein Spotify-Objekt und gibt die Konsolenausgabe zurück."""
    url = get_item_url(item)
    if not url:
        raise RuntimeError("Für dieses Element ist kein Spotify-Link verfügbar.")

    spotdl = shutil.which("spotdl")
    if not spotdl:
        raise RuntimeError(
            "spotdl ist nicht installiert. Installieren Sie es mit: pip install spotdl"
        )

    target_dir = os.path.expanduser(output_dir or cfg.get_download_dir())
    os.makedirs(target_dir, exist_ok=True)

    if progress_callback:
        progress_callback(0, 0)

    process = subprocess.Popen(
        [
            spotdl,
            "download",
            url,
            "--output",
            _spotdl_output_template(target_dir),
            "--bitrate",
            cfg.get_download_quality(),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # Ohne explizites Encoding dekodiert Python unter Windows mit der
        # ANSI-Codepage (cp1252) – ein Umlaut oder CJK-Zeichen im Songtitel
        # würde den Download mitten im Lesen mit UnicodeDecodeError abbrechen.
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=NO_WINDOW_FLAGS,
    )

    lines: list[str] = []
    total = 0
    done = 0
    # spotdl meldet die Anzahl gefundener Titel und je Titel eine "Downloaded"-Zeile.
    for line in process.stdout:
        if cancel_event is not None and cancel_event.is_set():
            process.terminate()
            process.wait(timeout=10)
            raise DownloadCancelled("Download abgebrochen.")
        lines.append(line)
        match = re.search(r"Found (\d+) song", line)
        if match:
            total = int(match.group(1))
            if progress_callback:
                progress_callback(done, total)
        if "Downloaded" in line:
            done += 1
            if progress_callback:
                progress_callback(done, total)
    process.wait()

    output = "".join(lines).strip()
    if process.returncode != 0:
        raise RuntimeError(output or "Download fehlgeschlagen.")
    return output
