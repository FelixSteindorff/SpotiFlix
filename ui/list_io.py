"""
Export und Import von Titellisten.

Export schreibt die gerade angezeigte Liste als CSV (für Tabellen) oder M3U8
(für Player) – beides mit den Spotify-URIs, damit sich die Liste später wieder
einlesen lässt. Import liest URIs oder open.spotify.com-Links aus einer
beliebigen Textdatei und legt daraus eine neue Playlist an; so lassen sich
Playlists sichern und zurückholen.
"""
import csv
import os
import re
import threading

import wx

import applog
from spotify_client import client
from ui.panel_helpers import announce, call_after, format_position

#: Erkennt sowohl "spotify:track:ID" als auch open.spotify.com-Links.
_URI_PATTERN = re.compile(
    r"spotify:(track|episode):([A-Za-z0-9]+)"
    r"|open\.spotify\.com/(?:intl-\w+/)?(track|episode)/([A-Za-z0-9]+)"
)

_WILDCARD = "CSV-Datei (*.csv)|*.csv|M3U-Playlist (*.m3u8)|*.m3u8|Textdatei (*.txt)|*.txt"


def _safe_name(name: str) -> str:
    """Macht aus einem Listentitel einen brauchbaren Dateinamen."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .")
    return cleaned or "Titelliste"


def export_rows(panel: wx.Window, rows: list[dict], title: str = "Titelliste"):
    """Speichert die übergebenen Zeilen als CSV, M3U8 oder Textdatei."""
    rows = [row for row in rows if row.get("uri")]
    if not rows:
        announce(panel, "Diese Ansicht enthält nichts zum Exportieren.")
        return

    dialog = wx.FileDialog(
        panel.GetTopLevelParent(),
        message="Titelliste speichern",
        defaultFile=_safe_name(title) + ".csv",
        wildcard=_WILDCARD,
        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
    )
    if dialog.ShowModal() != wx.ID_OK:
        dialog.Destroy()
        announce(panel, "Export abgebrochen")
        return
    path = dialog.GetPath()
    dialog.Destroy()

    try:
        if os.path.splitext(path)[1].lower() in (".m3u", ".m3u8"):
            _write_m3u(path, rows, title)
        else:
            _write_csv(path, rows)
    except Exception as e:
        applog.error("Export", e)
        announce(panel, f"Export fehlgeschlagen: {e}")
        wx.MessageBox(str(e), "Export-Fehler", wx.ICON_ERROR)
        return

    applog.info("Export", f"{len(rows)} Titel nach {path}")
    announce(panel, f"{len(rows)} Titel exportiert nach {os.path.basename(path)}")


def _write_csv(path: str, rows: list[dict]):
    # utf-8-sig, damit Excel die Umlaute richtig anzeigt.
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Titel", "Künstler", "Album", "Dauer", "URI"])
        for row in rows:
            writer.writerow([
                row.get("name", ""),
                row.get("artist_name", "") or row.get("show_name", ""),
                row.get("album_name", ""),
                format_position(row.get("duration_ms") or 0),
                row.get("uri", ""),
            ])


def _write_m3u(path: str, rows: list[dict], title: str):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("#EXTM3U\n")
        handle.write(f"#PLAYLIST:{title}\n")
        for row in rows:
            seconds = int((row.get("duration_ms") or 0) / 1000)
            artist = row.get("artist_name", "") or row.get("show_name", "")
            label = f"{artist} - {row.get('name', '')}" if artist else row.get("name", "")
            handle.write(f"#EXTINF:{seconds},{label}\n")
            handle.write(f"{row.get('uri', '')}\n")


def read_uris(path: str) -> list[str]:
    """Liest alle Titel-/Episoden-URIs aus einer Textdatei (CSV, M3U, Liste …)."""
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        content = handle.read()
    uris = []
    seen = set()
    for match in _URI_PATTERN.finditer(content):
        kind = match.group(1) or match.group(3)
        spotify_id = match.group(2) or match.group(4)
        uri = f"spotify:{kind}:{spotify_id}"
        if uri not in seen:
            seen.add(uri)
            uris.append(uri)
    return uris


def import_playlist(panel: wx.Window, on_done=None):
    """Legt aus den URIs einer Datei eine neue Playlist an."""
    dialog = wx.FileDialog(
        panel.GetTopLevelParent(),
        message="Titelliste öffnen",
        wildcard=_WILDCARD,
        style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
    )
    if dialog.ShowModal() != wx.ID_OK:
        dialog.Destroy()
        announce(panel, "Import abgebrochen")
        return
    path = dialog.GetPath()
    dialog.Destroy()

    try:
        uris = read_uris(path)
    except Exception as e:
        applog.error("Import", e)
        announce(panel, f"Datei konnte nicht gelesen werden: {e}")
        return
    if not uris:
        announce(panel, "In dieser Datei stehen keine Spotify-Titel.")
        wx.MessageBox(
            "In der Datei wurden keine Spotify-URIs oder -Links gefunden.\n"
            "Erwartet werden Einträge wie spotify:track:… oder open.spotify.com/track/…",
            "Nichts zu importieren",
            wx.ICON_INFORMATION,
        )
        return

    default_name = os.path.splitext(os.path.basename(path))[0]
    name_dialog = wx.TextEntryDialog(
        panel.GetTopLevelParent(),
        f"{len(uris)} Titel gefunden.\nName der neuen Playlist:",
        "Playlist importieren",
        default_name,
    )
    accepted = name_dialog.ShowModal() == wx.ID_OK
    name = name_dialog.GetValue().strip()
    name_dialog.Destroy()
    if not accepted or not name:
        announce(panel, "Import abgebrochen")
        return

    announce(panel, f"Playlist {name} wird angelegt …")

    def worker():
        try:
            playlist = client.create_playlist(name, description="Importiert mit SpotiFlix")
            added = client.add_tracks_to_playlist(playlist["id"], uris)
        except Exception as e:
            applog.error("Import", e)
            call_after(announce, panel, f"Import fehlgeschlagen: {e}")
            call_after(wx.MessageBox, str(e), "Import-Fehler", wx.ICON_ERROR)
            return
        applog.info("Import", f"{added} Titel in Playlist {name}")
        call_after(announce, panel, f"Playlist {name} mit {added} Titeln angelegt")
        if on_done:
            call_after(on_done)

    threading.Thread(target=worker, daemon=True).start()
