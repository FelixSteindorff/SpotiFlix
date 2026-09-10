# SpotiFlix – ein barrierefreier Spotify-Player für Windows.
# Copyright (C) 2026 Felix Steindorff
#
# Dieses Programm ist freie Software: Sie können es unter den Bedingungen
# der GNU General Public License, Version 3 oder (nach Ihrer Wahl) einer
# neueren Version, weitergeben und/oder verändern. Es wird ohne jede
# Gewährleistung bereitgestellt; siehe LICENSE für den vollen Text.

"""
Bearbeiten einer Playlist direkt in ihrer geöffneten Titelliste.

Die Panels müssen dafür keinen Zustand mitschleppen: Zu welcher Playlist eine
Titelliste gehört, steht im ``context_uri`` der Zeilen, und die Nummer in der
Playlist in ``playlist_position``. Beides setzt ``browse_common.load_playlist_tracks``
– dadurch bleiben Entfernen und Verschieben auch dann richtig, wenn die Anzeige
gefiltert oder umsortiert ist.

Alle Änderungen laufen im Hintergrund und melden das Ergebnis per Ansage; danach
lädt das Panel die Ansicht über den ``on_done``-Rückruf neu.
"""
import threading

import wx

import applog
from spotify_client import client
from ui.panel_helpers import announce, call_after, short_error

from i18n import _

# Ob eine Playlist bearbeitet werden darf, ändert sich während einer Sitzung
# praktisch nie – die Antwort wird darum je Playlist gemerkt.
_editable_cache: dict[str, bool] = {}


def playlist_id_for(rows: list[dict]) -> str | None:
    """Ermittelt die Playlist, zu der eine Titelliste gehört."""
    for row in rows:
        context = row.get("context_uri") or ""
        if context.startswith("spotify:playlist:"):
            return context.rsplit(":", 1)[-1]
    return None


def _is_editable(playlist_id: str) -> bool:
    if playlist_id not in _editable_cache:
        _editable_cache[playlist_id] = client.playlist_is_editable(playlist_id)
    return _editable_cache[playlist_id]


def forget_editable(playlist_id: str | None = None):
    """Verwirft die gemerkte Bearbeitbarkeit (z. B. nach einem Kontowechsel)."""
    if playlist_id:
        _editable_cache.pop(playlist_id, None)
    else:
        _editable_cache.clear()


def _run(panel: wx.Window, playlist_id: str, action, on_done, context: str):
    """Führt eine Playlist-Änderung im Hintergrund aus (mit Rechteprüfung)."""

    def worker():
        try:
            if not _is_editable(playlist_id):
                call_after(announce, panel, _("Diese Playlist können Sie nicht bearbeiten."))
                return
            message = action()
            if message:
                call_after(announce, panel, message)
            if on_done:
                call_after(on_done)
        except Exception as e:
            applog.error(context, e)
            call_after(announce, panel, _("{context} fehlgeschlagen: {short_error}").format(context=context, short_error=short_error(e)))
            call_after(wx.MessageBox, str(e), _(context), wx.ICON_WARNING)

    threading.Thread(target=worker, daemon=True).start()


def remove_tracks(panel: wx.Window, playlist_id: str, rows: list[dict], on_done=None):
    """Entfernt die übergebenen Titel positionsgenau aus der Playlist."""
    entries = [
        (row["uri"], row["playlist_position"])
        for row in rows
        if row.get("uri") and row.get("playlist_position") is not None
    ]
    if not entries:
        announce(panel, _("Keine Titel zum Entfernen ausgewählt."))
        return

    if len(entries) == 1:
        question = _("„{name}“ aus der Playlist entfernen?").format(name=rows[0].get('name', ''))
    else:
        question = _("{count} Titel aus der Playlist entfernen?").format(count=len(entries))
    if wx.MessageBox(question, _("Aus Playlist entfernen"), wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
        announce(panel, _("Entfernen abgebrochen"))
        return

    def action():
        removed = client.remove_playlist_positions(playlist_id, entries)
        if removed == 1:
            return _("{name} aus der Playlist entfernt").format(name=rows[0].get('name', ''))
        return _("{removed} Titel aus der Playlist entfernt").format(removed=removed)

    announce(panel, _("Titel werden entfernt …"), verbose=True)
    _run(panel, playlist_id, action, on_done, "Playlist bearbeiten")


def move_track(panel: wx.Window, playlist_id: str, row: dict, direction: int, on_done=None):
    """Verschiebt einen Titel in der Playlist nach oben (-1) oder unten (+1)."""
    position = row.get("playlist_position")
    if position is None:
        announce(panel, _("Dieser Titel lässt sich nicht verschieben."))
        return
    target = position + direction
    if target < 0:
        announce(panel, _("Der Titel steht bereits ganz oben."))
        return
    # Spotify erwartet die Zielstelle *vor* dem Einfügen: eine Position nach
    # unten heißt darum insert_before = position + 2.
    insert_before = target + 1 if direction > 0 else target

    def action():
        if not client.reorder_playlist(playlist_id, position, insert_before):
            return _("Der Titel steht bereits an dieser Stelle.")
        if direction > 0:
            return _("{name} nach unten verschoben").format(name=row.get("name", ""))
        return _("{name} nach oben verschoben").format(name=row.get("name", ""))

    _run(panel, playlist_id, action, on_done, "Playlist bearbeiten")


class PlaylistDetailsDialog(wx.Dialog):
    """Bearbeitet Name und Beschreibung einer Playlist."""

    def __init__(self, parent, name: str, description: str):
        super().__init__(parent, title=_("Playlist bearbeiten"), size=(480, 360))
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label=_("Name:")), 0, wx.ALL, 8)
        self.name_input = wx.TextCtrl(panel, value=name)
        self.name_input.SetName(_("Name der Playlist"))
        sizer.Add(self.name_input, 0, wx.ALL | wx.EXPAND, 8)

        sizer.Add(wx.StaticText(panel, label=_("Beschreibung:")), 0, wx.ALL, 8)
        self.description_input = wx.TextCtrl(panel, value=description, style=wx.TE_MULTILINE)
        self.description_input.SetName(_("Beschreibung der Playlist"))
        self.description_input.SetToolTip(_("Spotify zeigt die Beschreibung unter dem Playlist-Namen an"))
        sizer.Add(self.description_input, 1, wx.ALL | wx.EXPAND, 8)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(panel, id=wx.ID_OK, label=_("Speichern"))
        btn_ok.SetDefault()
        btn_box.Add(btn_ok, 1, wx.ALL | wx.EXPAND, 5)
        btn_box.Add(wx.Button(panel, id=wx.ID_CANCEL, label=_("Abbrechen")), 1, wx.ALL | wx.EXPAND, 5)
        sizer.Add(btn_box, 0, wx.ALL | wx.EXPAND, 8)

        panel.SetSizer(sizer)
        self.CenterOnParent()
        self.name_input.SetFocus()

    def get_name(self) -> str:
        return self.name_input.GetValue().strip()

    def get_description(self) -> str:
        return self.description_input.GetValue().strip()


def edit_details(panel: wx.Window, playlist_id: str, on_done=None):
    """Lädt Name und Beschreibung, zeigt den Dialog und speichert die Änderung."""
    announce(panel, _("Lade Playlist-Daten …"), verbose=True)

    def worker():
        try:
            details = client.playlist_details(playlist_id)
            editable = _is_editable(playlist_id)
        except Exception as e:
            applog.error("Playlist bearbeiten", e)
            call_after(announce, panel, _("Playlist konnte nicht geladen werden: {short_error}").format(short_error=short_error(e)))
            return
        if not editable:
            call_after(announce, panel, _("Diese Playlist können Sie nicht bearbeiten."))
            return
        call_after(_show_details_dialog, panel, playlist_id, details, on_done)

    threading.Thread(target=worker, daemon=True).start()


def _show_details_dialog(panel: wx.Window, playlist_id: str, details: dict, on_done):
    dialog = PlaylistDetailsDialog(panel.GetTopLevelParent(), details["name"], details["description"])
    accepted = dialog.ShowModal() == wx.ID_OK
    name, description = dialog.get_name(), dialog.get_description()
    dialog.Destroy()
    if not accepted:
        return
    if not name:
        announce(panel, _("Der Name darf nicht leer sein – nichts geändert."))
        return
    if name == details["name"] and description == details["description"]:
        announce(panel, _("Nichts geändert"))
        return

    def action():
        client.update_playlist_details(playlist_id, name=name, description=description)
        return _("Playlist gespeichert: {name}").format(name=name)

    _run(panel, playlist_id, action, on_done, "Playlist bearbeiten")
