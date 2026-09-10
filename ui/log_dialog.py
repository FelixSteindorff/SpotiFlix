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

from i18n import _


class LogDialog(wx.Dialog):
    """Liste der Protokolleinträge, neueste zuerst."""

    def __init__(self, parent):
        super().__init__(parent, title=_("Protokoll"), size=(720, 480))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.SetName(_("Protokoll"))
        self.list.InsertColumn(0, _("Zeit"), width=140)
        self.list.InsertColumn(1, _("Art"), width=70)
        self.list.InsertColumn(2, _("Bereich"), width=120)
        self.list.InsertColumn(3, _("Meldung"), width=360)
        sizer.Add(self.list, 1, wx.ALL | wx.EXPAND, 8)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        btn_copy = wx.Button(panel, label=_("In Zwischenablage"))
        btn_copy.Bind(wx.EVT_BUTTON, self._on_copy)
        btn_open = wx.Button(panel, label=_("Protokolldatei öffnen"))
        btn_open.Bind(wx.EVT_BUTTON, self._on_open_file)
        btn_clear = wx.Button(panel, label=_("Leeren"))
        btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
        for btn in (btn_copy, btn_open, btn_clear):
            btn_box.Add(btn, 1, wx.ALL | wx.EXPAND, 4)
        sizer.Add(btn_box, 0, wx.ALL | wx.EXPAND, 4)

        btn_close = wx.Button(panel, id=wx.ID_CANCEL, label=_("Schließen"))
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
        self.list.SetName(_("Protokoll, {count} Einträge").format(count=len(entries)))
        if entries:
            select_only(self.list, 0)

    def _on_copy(self, event):
        text = applog.summary()
        if not text:
            announce(self, _("Das Protokoll ist leer"))
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            announce(self, _("Protokoll in die Zwischenablage kopiert"))
        else:
            announce(self, _("Zwischenablage nicht verfügbar"))

    def _on_open_file(self, event):
        if os.path.isfile(applog.LOG_FILE):
            open_folder(os.path.dirname(applog.LOG_FILE))
            announce(self, _("Ordner mit {LOG_FILE} geöffnet").format(LOG_FILE=os.path.basename(applog.LOG_FILE)))
        else:
            announce(self, _("Es gibt noch keine Protokolldatei"))

    def _on_clear(self, event):
        applog.clear()
        self._fill()
        announce(self, _("Protokoll geleert"))


def show_log(frame):
    """Öffnet den Protokoll-Dialog."""
    entries = applog.entries()
    announce(frame, _("Protokoll: {count} Einträge").format(count=len(entries))
             if entries else _("Protokoll ist leer"))
    dialog = LogDialog(frame)
    dialog.ShowModal()
    dialog.Destroy()
