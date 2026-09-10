#!/usr/bin/env python3
"""
Barrierefreier Spotify Player — Einstiegspunkt
"""
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
