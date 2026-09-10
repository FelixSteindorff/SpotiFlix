"""
Protokoll-Dialog: zeigt die gesammelten Fehler und Ereignisse.

Meldungen blitzen sonst nur kurz auf. Hier stehen sie mit Zeitstempel
beieinander, lassen sich in die Zwischenablage kopieren (für Rückfragen) und
die Protokolldatei kann direkt geöffnet werden.
"""
import os

import wx

import applog
from ui.panel_helpers import announce, open_folder, select_only


class LogDialog(wx.Dialog):
    """Liste der Protokolleinträge, neueste zuerst."""

    def __init__(self, parent):
        super().__init__(parent, title="Protokoll", size=(720, 480))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.SetName("Protokoll")
        self.list.InsertColumn(0, "Zeit", width=140)
        self.list.InsertColumn(1, "Art", width=70)
        self.list.InsertColumn(2, "Bereich", width=120)
        self.list.InsertColumn(3, "Meldung", width=360)
        sizer.Add(self.list, 1, wx.ALL | wx.EXPAND, 8)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        btn_copy = wx.Button(panel, label="In Zwischenablage")
        btn_copy.Bind(wx.EVT_BUTTON, self._on_copy)
        btn_open = wx.Button(panel, label="Protokolldatei öffnen")
        btn_open.Bind(wx.EVT_BUTTON, self._on_open_file)
        btn_clear = wx.Button(panel, label="Leeren")
        btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
        for btn in (btn_copy, btn_open, btn_clear):
            btn_box.Add(btn, 1, wx.ALL | wx.EXPAND, 4)
        sizer.Add(btn_box, 0, wx.ALL | wx.EXPAND, 4)

        btn_close = wx.Button(panel, id=wx.ID_CANCEL, label="Schließen")
        btn_close.SetDefault()
        sizer.Add(btn_close, 0, wx.ALL | wx.EXPAND, 8)

        panel.SetSizer(sizer)
        self._fill()
        self.CenterOnParent()
        self.list.SetFocus()

    def _fill(self):
        entries = applog.entries()
        self.list.DeleteAllItems()
        for entry in entries:
            index = self.list.InsertItem(self.list.GetItemCount(), entry["time"])
            self.list.SetItem(index, 1, entry["level"])
            self.list.SetItem(index, 2, entry["context"])
            self.list.SetItem(index, 3, entry["message"])
        self.list.SetName(f"Protokoll, {len(entries)} Einträge")
        if entries:
            select_only(self.list, 0)

    def _on_copy(self, event):
        text = applog.summary()
        if not text:
            announce(self, "Das Protokoll ist leer")
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            announce(self, "Protokoll in die Zwischenablage kopiert")
        else:
            announce(self, "Zwischenablage nicht verfügbar")

    def _on_open_file(self, event):
        if os.path.isfile(applog.LOG_FILE):
            open_folder(os.path.dirname(applog.LOG_FILE))
            announce(self, f"Ordner mit {os.path.basename(applog.LOG_FILE)} geöffnet")
        else:
            announce(self, "Es gibt noch keine Protokolldatei")

    def _on_clear(self, event):
        applog.clear()
        self._fill()
        announce(self, "Protokoll geleert")


def show_log(frame):
    """Öffnet den Protokoll-Dialog."""
    entries = applog.entries()
    announce(frame, f"Protokoll: {len(entries)} Einträge" if entries else "Protokoll ist leer")
    dialog = LogDialog(frame)
    dialog.ShowModal()
    dialog.Destroy()
