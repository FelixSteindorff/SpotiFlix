"""
Dialog für die Download-Warteschlange.

Zeigt wartende, laufende und abgeschlossene Aufträge und macht sie steuerbar:
abbrechen, fehlgeschlagene erneut versuchen, erledigte ausblenden. Die Liste
frischt sich im Sekundentakt auf, solange der Dialog offen ist.
"""
import wx

from download_manager import RETRYABLE, downloads
from ui.panel_helpers import announce, select_only

#: Wie oft die Anzeige aktualisiert wird, solange der Dialog offen ist.
REFRESH_MS = 1000


class DownloadsDialog(wx.Dialog):
    """Übersicht und Steuerung der laufenden Downloads."""

    def __init__(self, parent):
        super().__init__(parent, title="Downloads", size=(640, 460))
        self._jobs = []

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.list.SetName("Downloads")
        self.list.InsertColumn(0, "Titel", width=300)
        self.list.InsertColumn(1, "Status", width=140)
        self.list.InsertColumn(2, "Fortschritt", width=140)
        sizer.Add(self.list, 1, wx.ALL | wx.EXPAND, 8)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_cancel_selected = wx.Button(panel, label="Auswahl abbrechen")
        self.btn_cancel_selected.Bind(wx.EVT_BUTTON, self._on_cancel_selected)
        self.btn_cancel_all = wx.Button(panel, label="Alle abbrechen")
        self.btn_cancel_all.Bind(wx.EVT_BUTTON, self._on_cancel_all)
        self.btn_retry = wx.Button(panel, label="Fehlgeschlagene wiederholen")
        self.btn_retry.Bind(wx.EVT_BUTTON, self._on_retry)
        self.btn_clear = wx.Button(panel, label="Erledigte entfernen")
        self.btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
        for btn in (self.btn_cancel_selected, self.btn_cancel_all, self.btn_retry, self.btn_clear):
            btn_box.Add(btn, 1, wx.ALL | wx.EXPAND, 4)
        sizer.Add(btn_box, 0, wx.ALL | wx.EXPAND, 4)

        btn_close = wx.Button(panel, id=wx.ID_CANCEL, label="Schließen")
        btn_close.SetDefault()
        sizer.Add(btn_close, 0, wx.ALL | wx.EXPAND, 8)

        panel.SetSizer(sizer)
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda event: self.refresh(), self._timer)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.refresh()
        self._timer.Start(REFRESH_MS)
        self.CenterOnParent()
        self.list.SetFocus()

    # -- Anzeige -------------------------------------------------------------

    def refresh(self):
        """Zeichnet die Auftragsliste neu (Markierung bleibt erhalten)."""
        selected = [index for index in range(self.list.GetItemCount()) if self.list.IsSelected(index)]
        self._jobs = downloads.jobs()
        self.list.DeleteAllItems()
        for job in self._jobs:
            index = self.list.InsertItem(self.list.GetItemCount(), job.name)
            self.list.SetItem(index, 1, job.status)
            self.list.SetItem(index, 2, self._progress_text(job))
        for index in selected:
            if index < self.list.GetItemCount():
                self.list.Select(index)
        if self._jobs and not selected:
            select_only(self.list, 0)
        self.list.SetName(f"Downloads, {len(self._jobs)} Aufträge")
        self.btn_retry.Enable(any(job.status in RETRYABLE for job in self._jobs))
        self.btn_clear.Enable(any(job.finished for job in self._jobs))
        active = [job for job in self._jobs if not job.finished]
        self.btn_cancel_all.Enable(bool(active))
        self.btn_cancel_selected.Enable(bool(self._jobs))

    def _progress_text(self, job) -> str:
        if job.total:
            return f"{job.done} von {job.total}"
        if job.error:
            return str(job.error)[:60]
        return ""

    def _selected_jobs(self) -> list:
        return [job for index, job in enumerate(self._jobs) if self.list.IsSelected(index)]

    # -- Aktionen ------------------------------------------------------------

    def _on_cancel_selected(self, event):
        cancelled = sum(1 for job in self._selected_jobs() if downloads.cancel(job.id))
        announce(self, f"{cancelled} Download(s) werden abgebrochen" if cancelled
                 else "Nichts zum Abbrechen ausgewählt")
        self.refresh()

    def _on_cancel_all(self, event):
        cancelled = downloads.cancel_all()
        announce(self, f"{cancelled} Download(s) werden abgebrochen")
        self.refresh()

    def _on_retry(self, event):
        retried = downloads.retry_failed()
        announce(self, f"{retried} Download(s) erneut eingereiht" if retried
                 else "Keine fehlgeschlagenen Downloads")
        self.refresh()

    def _on_clear(self, event):
        removed = downloads.clear_finished()
        announce(self, f"{removed} erledigte Einträge entfernt")
        self.refresh()

    def _on_close(self, event):
        self._timer.Stop()
        event.Skip()


def show_downloads(frame):
    """Öffnet den Download-Dialog (oder meldet, dass nichts ansteht)."""
    if not downloads.jobs():
        announce(frame, "Keine Downloads vorhanden")
        return
    dialog = DownloadsDialog(frame)
    dialog.ShowModal()
    dialog.Destroy()
