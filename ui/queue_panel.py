"""
Warteschlangen-Panel mit zwei Ansichten.

  * **Meine Liste** – alles, was über „Zur Warteschlange hinzufügen" eingereiht
    wurde. Diese Liste ist bearbeitbar (umsortieren, entfernen, leeren) und wird
    mit Enter ab dem markierten Titel abgespielt: Spotify bekommt die Titel-URIs
    in genau dieser Reihenfolge übergeben.
  * **Spotify-Warteschlange** – was Spotify selbst als Nächstes spielt, inklusive
    dem, was Autoplay oder ein anderes Gerät eingereiht hat. Diese Ansicht ist
    nur lesend: Die Web API kann Einträge weder entfernen noch umsortieren.
    Enter spielt den gewählten Titel direkt ab.

Tastenkürzel in der Liste:
  * Enter            – abspielen (ab markiertem Titel bzw. den Titel selbst)
  * Strg+Pfeil hoch  – Titel nach oben (nur „Meine Liste")
  * Strg+Pfeil runter– Titel nach unten (nur „Meine Liste")
  * Entf             – markierte Titel entfernen (nur „Meine Liste")
  * Strg+A           – alles markieren
  * Strg+E           – Liste exportieren
  * F5               – Spotify-Warteschlange neu laden
"""
import threading

import wx

import applog
from spotify_client import client
from ui.browse_common import episode_row, track_row
from ui.context_actions import populate_item_menu
from ui.list_io import export_rows
from ui.panel_helpers import (
    announce,
    call_after,
    context_menu_position,
    count_message,
    focus_origin,
    mark_local_player_running,
    restore_focus,
    select_only,
    selected_rows,
    set_now_playing,
    short_error,
    start_playback,
)


class QueuePanel(wx.Panel):
    """Bearbeitbare eigene Liste plus Blick auf Spotifys echte Warteschlange."""

    VIEWS = [("local", "Meine Liste"), ("spotify", "Spotify-Warteschlange")]
    #: Elementtypen, für die ein Kontextmenü angeboten wird.
    CONTEXT_TYPES = {"track", "episode"}
    #: Tasten, die dieses Panel selbst behandelt (für die Kürzelübersicht).
    LOCAL_SHORTCUTS = [
        ("Eingabe", "Ab markiertem Titel abspielen"),
        ("Strg+Pfeil hoch/runter", "Titel in „Meine Liste“ verschieben"),
        ("Entf", "Markierte Titel entfernen"),
        ("Strg+A", "Alles markieren"),
        ("Strg+E", "Liste exportieren"),
        ("F5", "Spotify-Warteschlange neu laden"),
        ("Anwendungstaste, Umschalt+F10", "Kontextmenü zum markierten Titel"),
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self.items: list[dict] = []
        self._spotify_items: list[dict] = []
        self.view = "local"

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.heading = wx.StaticText(self, label="Warteschlange")
        sizer.Add(self.heading, 0, wx.ALL | wx.EXPAND, 10)

        self.view_choice = wx.RadioBox(
            self,
            label="Ansicht",
            choices=[label for _key, label in self.VIEWS],
            majorDimension=2,
            style=wx.RA_SPECIFY_COLS,
        )
        self.view_choice.SetToolTip(
            "„Meine Liste“ ist bearbeitbar; „Spotify-Warteschlange“ zeigt, was "
            "Spotify wirklich als Nächstes spielt (nur lesend)."
        )
        self.view_choice.Bind(wx.EVT_RADIOBOX, self._on_view_changed)
        sizer.Add(self.view_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT)
        # Zugänglicher Name: NVDA meldet sonst nur „Liste".
        self.list.SetName("Warteschlange")
        self.list.InsertColumn(0, "Titel", width=360)
        self.list.InsertColumn(1, "Details", width=320)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        sizer.Add(self.list, 1, wx.ALL | wx.EXPAND, 10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_up = wx.Button(self, label="Nach oben (Strg+Hoch)")
        self.btn_up.Bind(wx.EVT_BUTTON, lambda e: self.move_selected(-1))
        self.btn_down = wx.Button(self, label="Nach unten (Strg+Runter)")
        self.btn_down.Bind(wx.EVT_BUTTON, lambda e: self.move_selected(1))
        self.btn_remove = wx.Button(self, label="Entfernen (Entf)")
        self.btn_remove.Bind(wx.EVT_BUTTON, lambda e: self.remove_selected())
        self.btn_clear = wx.Button(self, label="Leeren")
        self.btn_clear.Bind(wx.EVT_BUTTON, lambda e: self.clear())
        self.btn_reload = wx.Button(self, label="Aktualisieren (F5)")
        self.btn_reload.Bind(wx.EVT_BUTTON, lambda e: self.reload_spotify_queue())
        for btn in (self.btn_up, self.btn_down, self.btn_remove, self.btn_clear, self.btn_reload):
            btn_box.Add(btn, 1, wx.ALL | wx.EXPAND, 5)
        sizer.Add(btn_box, 0, wx.ALL | wx.EXPAND, 5)

        self.SetSizer(sizer)
        self._render()

    def focus_default(self):
        self.list.SetFocus()

    # -- Ansicht -------------------------------------------------------------

    @property
    def rows(self) -> list[dict]:
        """Die aktuell angezeigten Zeilen (je nach Ansicht)."""
        return self.items if self.view == "local" else self._spotify_items

    def _view_label(self) -> str:
        return dict(self.VIEWS)[self.view]

    def _on_view_changed(self, event):
        self.view = self.VIEWS[self.view_choice.GetSelection()][0]
        self._render()
        announce(self, count_message(self._view_label(), len(self.rows)))
        if self.view == "spotify" and not self._spotify_items:
            self.reload_spotify_queue()

    # -- Anzeige -------------------------------------------------------------

    def add_items(self, rows: list[dict]):
        """Hängt Titel an die eigene Warteschlange an.

        Die Markierung bleibt erhalten: Wer gerade in der Warteschlange
        navigiert und per Kontextmenü etwas anhängt, soll seine Position nicht
        verlieren.
        """
        for row in rows:
            if row.get("uri"):
                self.items.append(row)
        if self.view == "local":
            self._render()

    def _render(self, select: int | None = None):
        """Baut die Liste neu auf; ``select`` bestimmt die neue Markierung.

        Ohne ``select`` bleibt der bisher markierte Eintrag markiert.
        """
        if select is None:
            select = self.list.GetFirstSelected()
        rows = self.rows
        self.list.DeleteAllItems()
        for row in rows:
            index = self.list.InsertItem(self.list.GetItemCount(), row.get("name", ""))
            self.list.SetItem(index, 1, self._details(row))
        label = f"{self._view_label()} ({len(rows)})"
        self.heading.SetLabel(label)
        self.list.SetName(f"{self._view_label()}, {len(rows)} Titel")
        editable = self.view == "local" and bool(rows)
        for btn in (self.btn_up, self.btn_down, self.btn_remove, self.btn_clear):
            btn.Enable(editable)
        self.btn_reload.Enable(self.view == "spotify")
        if rows:
            target = 0 if select is None or select < 0 else max(0, min(select, len(rows) - 1))
            select_only(self.list, target)

    def _details(self, row: dict) -> str:
        details = row.get("details")
        if details:
            return details
        artists = row.get("artists")
        if isinstance(artists, list):
            return ", ".join(a.get("name", "") for a in artists)
        return row.get("artist_name", "")

    def get_selected_item(self) -> dict | None:
        index = self.list.GetFirstSelected()
        rows = self.rows
        if index == wx.NOT_FOUND or index >= len(rows):
            return None
        return rows[index]

    def get_selected_items(self) -> list[dict]:
        """Alle markierten Titel – Grundlage für Aktionen auf mehreren."""
        return selected_rows(self.list, self.rows)

    # -- Spotify-Warteschlange lesen -----------------------------------------

    def reload_spotify_queue(self):
        """Holt Spotifys tatsächliche Warteschlange im Hintergrund."""
        announce(self, "Lade Spotify-Warteschlange …", verbose=True)
        origin = focus_origin()

        def worker():
            try:
                current, upcoming = client.queue_snapshot()
            except Exception as e:
                applog.error("Warteschlange", e)
                call_after(announce, self, f"Warteschlange konnte nicht geladen werden: {short_error(e)}")
                return
            rows = []
            if current:
                rows.append(self._queue_row(current, playing=True))
            rows.extend(self._queue_row(item) for item in upcoming)
            call_after(self._apply_spotify_rows, rows, origin)

        threading.Thread(target=worker, daemon=True).start()

    def _queue_row(self, item: dict, playing: bool = False) -> dict:
        """Wandelt einen Warteschlangen-Eintrag in eine Anzeigezeile um."""
        row = episode_row(item) if item.get("type") == "episode" else track_row(item)
        if playing:
            row = dict(row, playing=True)
            row["details"] = " - ".join(part for part in ["Läuft gerade", row.get("details", "")] if part)
        return row

    def _apply_spotify_rows(self, rows: list[dict], origin):
        self._spotify_items = rows
        if self.view != "spotify":
            return
        self._render(select=0)
        announce(self, count_message("Spotify-Warteschlange", len(rows)))
        restore_focus(self.list, origin)

    # -- Bearbeiten (nur „Meine Liste") --------------------------------------

    def _require_local(self) -> bool:
        if self.view == "local":
            return True
        announce(self, "Die Spotify-Warteschlange lässt sich nicht bearbeiten.")
        return False

    def move_selected(self, direction: int):
        if not self._require_local():
            return
        index = self.list.GetFirstSelected()
        if index == wx.NOT_FOUND:
            return
        target = index + direction
        if target < 0 or target >= len(self.items):
            return
        self.items[index], self.items[target] = self.items[target], self.items[index]
        self._render(select=target)
        announce(self, f"{self.items[target].get('name', '')} verschoben")

    def remove_selected(self):
        if not self._require_local():
            return
        indices = sorted(
            (index for index in range(self.list.GetItemCount()) if self.list.IsSelected(index)),
            reverse=True,
        )
        if not indices:
            return
        removed = [self.items.pop(index) for index in indices if index < len(self.items)]
        if not removed:
            return
        self._render(select=min(indices))
        if len(removed) == 1:
            announce(self, f"{removed[0].get('name', '')} aus der Warteschlange entfernt")
        else:
            announce(self, f"{len(removed)} Titel aus der Warteschlange entfernt")

    def clear(self):
        if not self._require_local():
            return
        if not self.items:
            return
        self.items = []
        self._render()
        announce(self, "Warteschlange geleert")

    # -- Wiedergabe ----------------------------------------------------------

    def _on_activate(self, event):
        index = event.GetIndex()
        if not (0 <= index < len(self.rows)):
            return
        if self.view == "local":
            self._play_from(index)
        else:
            # Spotifys Warteschlange bleibt unangetastet – nur den Titel starten.
            start_playback(self, self.rows[index])

    def _play_from(self, index: int):
        uris = [row["uri"] for row in self.items[index:] if row.get("uri")]
        if not uris:
            return
        row = self.items[index]
        name = row.get("name", "")
        artist = self._details(row)
        now_playing_label = f"{artist} - {name}" if artist else name
        announce(self, f"Spiele Warteschlange ab: {name}")

        def worker():
            try:
                played = client.play_uris(uris)
                if not played:
                    call_after(wx.MessageBox, "Zuerst autorisieren!", "Fehler", wx.ICON_ERROR)
                    call_after(announce, self, "Wiedergabe nicht möglich – zuerst autorisieren")
                    return
                call_after(mark_local_player_running, self)
                call_after(set_now_playing, self, now_playing_label)
                # Spotify nimmt pro Start maximal 100 Titel entgegen – das wird
                # angesagt, statt die Liste stillschweigend zu kürzen.
                message = f"Wiedergabe gestartet: {name}"
                if played < len(uris):
                    message += f" – die ersten {played} von {len(uris)} Titeln"
                call_after(announce, self, message)
            except Exception as e:
                call_after(wx.MessageBox, str(e), "Wiedergabefehler", wx.ICON_WARNING)

        threading.Thread(target=worker, daemon=True).start()

    # -- Tastatur / Kontextmenü ----------------------------------------------

    def _select_all(self):
        for index in range(self.list.GetItemCount()):
            self.list.Select(index)
        announce(self, f"{self.list.GetSelectedItemCount()} Titel markiert")

    def _export_view(self):
        export_rows(self, self.rows, self._view_label())

    def _on_key_down(self, event):
        key = event.GetKeyCode()
        if event.ControlDown() and key in (ord("A"), ord("a")):
            self._select_all()
            return
        if event.ControlDown() and key in (ord("E"), ord("e")):
            self._export_view()
            return
        if event.ControlDown() and key == wx.WXK_UP:
            self.move_selected(-1)
            return
        if event.ControlDown() and key == wx.WXK_DOWN:
            self.move_selected(1)
            return
        if key == wx.WXK_DELETE:
            self.remove_selected()
            return
        if key == wx.WXK_F5:
            self.reload_spotify_queue()
            return
        event.Skip()

    def _on_context_menu(self, event):
        items = self.get_selected_items()
        if not items or not {item.get("type") for item in items} & self.CONTEXT_TYPES:
            return
        menu = wx.Menu()
        populate_item_menu(self, menu, items)
        position = context_menu_position(self.list, event, self.list.GetFirstSelected())
        self.list.PopupMenu(menu, position)
        menu.Destroy()
