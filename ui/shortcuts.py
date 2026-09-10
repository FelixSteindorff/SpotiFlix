# SpotiFlix – ein barrierefreier Spotify-Player für Windows.
# Copyright (C) 2026 Felix Steindorff
#
# Dieses Programm ist freie Software: Sie können es unter den Bedingungen
# der GNU General Public License, Version 3 oder (nach Ihrer Wahl) einer
# neueren Version, weitergeben und/oder verändern. Es wird ohne jede
# Gewährleistung bereitgestellt; siehe LICENSE für den vollen Text.

"""
Übersicht aller Tastenkürzel (F1).

Die Liste wird **nicht** gepflegt, sondern zur Laufzeit eingesammelt:

  * Menü-Kürzel kommen aus der Menüleiste selbst – ein neuer Menüpunkt mit
    ``\\tCtrl+X`` taucht darum automatisch hier auf.
  * Kürzel, die nur in einer Liste gelten (Rücktaste, Entf, F5 …), stehen als
    ``LOCAL_SHORTCUTS`` in der jeweiligen Panel-Klasse, direkt neben dem
    Tastatur-Handler. Wer dort eine Taste ergänzt, ergänzt sie hier mit.
  * Die Medientasten meldet das Hauptfenster – und zwar nur die, deren
    Registrierung tatsächlich geklappt hat.
"""
import wx

from ui.panel_helpers import announce

from i18n import _


def _menu_shortcuts(frame) -> list[dict]:
    """Liest alle Menüeinträge samt ihrer Kürzel aus der Menüleiste."""
    rows = []
    menubar = frame.GetMenuBar()
    if not menubar:
        return rows
    for index in range(menubar.GetMenuCount()):
        rows += _menu_items(menubar.GetMenu(index), menubar.GetMenuLabelText(index))
    return rows


def _menu_items(menu, area: str) -> list[dict]:
    """Läuft ein Menü samt seiner Untermenüs ab (z. B. die Schnellzugriffe)."""
    rows = []
    for item in menu.GetMenuItems():
        if item.IsSeparator():
            continue
        if item.IsSubMenu():
            rows += _menu_items(item.GetSubMenu(), area)
            continue
        label = item.GetItemLabel()
        text, _tab, accelerator = label.partition("\t")
        text = text.replace("&", "").strip()
        if not text:
            continue
        rows.append({"area": area, "key": accelerator.strip() or "–", "name": text})
    return rows


def _panel_shortcuts(frame) -> list[dict]:
    """Sammelt die Kürzel ein, die die Panels selbst behandeln."""
    rows = []
    notebook = getattr(frame, "notebook", None)
    if notebook is None:
        return rows
    for index in range(notebook.GetPageCount()):
        page = notebook.GetPage(index)
        local = getattr(page, "LOCAL_SHORTCUTS", None)
        if not local:
            continue
        area = notebook.GetPageText(index)
        for key, name in local:
            rows.append({"area": area, "key": _(key), "name": _(name)})
    return rows


def collect_shortcuts(frame) -> list[dict]:
    """Stellt alle bekannten Kürzel zusammen (ohne Dubletten)."""
    rows = _menu_shortcuts(frame) + _panel_shortcuts(frame)
    media = getattr(frame, "media_shortcuts", None)
    if media:
        rows += [{"area": _("Medientasten"), "key": key, "name": name}
                 for key, name in media()]
    seen = set()
    unique = []
    for row in rows:
        marker = (row["area"], row["key"], row["name"])
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(row)
    return unique


class ShortcutsDialog(wx.Dialog):
    """Zeigt alle Tastenkürzel; das Feld oben filtert die Liste."""

    def __init__(self, parent, rows: list[dict]):
        super().__init__(parent, title=_("Tastenkürzel"), size=(620, 520))
        self._rows = rows

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label=_("Suchen (Kürzel oder Funktion):")), 0, wx.ALL, 8)
        self.search = wx.TextCtrl(panel)
        self.search.SetName(_("Kürzel suchen"))
        self.search.Bind(wx.EVT_TEXT, self._on_filter)
        sizer.Add(self.search, 0, wx.ALL | wx.EXPAND, 8)

        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.SetName(_("Tastenkürzel"))
        self.list.InsertColumn(0, _("Bereich"), width=130)
        self.list.InsertColumn(1, _("Kürzel"), width=160)
        self.list.InsertColumn(2, _("Funktion"), width=290)
        sizer.Add(self.list, 1, wx.ALL | wx.EXPAND, 8)

        btn_close = wx.Button(panel, id=wx.ID_CANCEL, label=_("Schließen"))
        btn_close.SetDefault()
        sizer.Add(btn_close, 0, wx.ALL | wx.EXPAND, 8)

        panel.SetSizer(sizer)
        self._fill(self._rows)
        self.CenterOnParent()
        self.search.SetFocus()

    def _fill(self, rows: list[dict]):
        self.list.DeleteAllItems()
        for row in rows:
            index = self.list.InsertItem(self.list.GetItemCount(), row["area"])
            self.list.SetItem(index, 1, row["key"])
            self.list.SetItem(index, 2, row["name"])
        self.list.SetName(_("Tastenkürzel, {count} Einträge").format(count=len(rows)))

    def _on_filter(self, event):
        needle = self.search.GetValue().strip().casefold()
        if not needle:
            self._fill(self._rows)
            return
        self._fill([
            row for row in self._rows
            if needle in row["key"].casefold()
            or needle in row["name"].casefold()
            or needle in row["area"].casefold()
        ])


def show_shortcuts(frame):
    """Öffnet die Kürzelübersicht des aktuellen Fensters."""
    rows = collect_shortcuts(frame)
    announce(frame, _("Tastenkürzel: {count} Einträge").format(count=len(rows)))
    dialog = ShortcutsDialog(frame, rows)
    dialog.ShowModal()
    dialog.Destroy()
