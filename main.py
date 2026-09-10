#!/usr/bin/env python3
"""
Barrierefreier Spotify Player — Einstiegspunkt
"""
import os

# Muss vor dem ersten protobuf-Import gesetzt sein: Die von librespot-python
# mitgelieferten _pb2.py-Dateien laufen nur mit der reinen Python-Variante
# (siehe librespot_download). Hier gesetzt, damit es auch dann gilt, wenn eine
# andere Bibliothek protobuf früher lädt.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import wx

import config as cfg
from ui.main_window import MainWindow


def main():
    app = wx.App(False)
    frame = MainWindow()
    if not cfg.has_credentials():
        frame.SetStatusText(
            "Bitte zuerst Spotify API konfigurieren: Bearbeiten > Einstellungen"
        )
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
