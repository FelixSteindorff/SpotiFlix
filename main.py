#!/usr/bin/env python3
# SpotiFlix – ein barrierefreier Spotify-Player für Windows.
# Copyright (C) 2026 Felix Steindorff
#
# Dieses Programm ist freie Software: Sie können es unter den Bedingungen
# der GNU General Public License, Version 3 oder (nach Ihrer Wahl) einer
# neueren Version, weitergeben und/oder verändern. Es wird ohne jede
# Gewährleistung bereitgestellt; siehe LICENSE für den vollen Text.

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
import i18n

# Die Sprache muss stehen, bevor die Oberfläche importiert wird: Beschriftungen
# in Klassenattributen entstehen beim Import.
i18n.install(cfg.get_language())

from ui.main_window import MainWindow  # noqa: E402

from i18n import _


def main():
    app = wx.App(False)
    frame = MainWindow()
    if not cfg.has_credentials():
        frame.SetStatusText(
            _("Bitte zuerst Spotify API konfigurieren: Bearbeiten > Einstellungen")
        )
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
