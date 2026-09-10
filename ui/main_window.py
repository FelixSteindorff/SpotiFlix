"""
Hauptfenster des Spotify Players
"""
import threading
import time

import wx

import applog
import config as cfg
import nvda
from download_manager import STATUS_DONE, STATUS_FAILED, downloads
from spotify_client import client
from ui.config_dialog import ConfigurationDialog
from ui.library_panel import LibraryPanel
from ui.search_panel import SearchPanel
from ui.queue_panel import QueuePanel
from ui.discover_panel import DiscoverPanel
from ui.downloads_dialog import show_downloads
from ui.list_io import import_playlist
from ui.log_dialog import show_log
from ui.panel_helpers import call_after, format_position, mark_shutting_down, open_folder
from ui.shortcuts import show_shortcuts

APP_NAME = "SpotiFlix"

# Sprung beim Spulen (Strg+Umschalt+Pfeil links/rechts).
SEEK_STEP_MS = 10000
# Auswahl für den Einschlaf-Timer (Minuten; 0 = aus).
SLEEP_CHOICES = [(0, "Aus"), (15, "15 Minuten"), (30, "30 Minuten"),
                 (45, "45 Minuten"), (60, "60 Minuten"), (90, "90 Minuten")]
# Windows-Virtualcodes der Medientasten – damit die App auch im Hintergrund
# steuerbar bleibt (wichtig, wenn man mit NVDA in einem anderen Programm ist).
MEDIA_KEYS = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "stop": 0xB2,
}
# Feste IDs für RegisterHotKey (müssen im Bereich 0x0000–0xBFFF liegen).
_HOTKEY_ID_BASE = 9100

# Now-Playing-Polling: Ein fester 3-Sekunden-Takt sind ~1.200 Requests pro
# Stunde, auch wenn gar nichts läuft – Spotify drosselt das (HTTP 429). Darum
# ein ruhigerer Grundtakt, der sich verlängert, solange nichts passiert.
POLL_INTERVAL_MS = 5000
POLL_MAX_INTERVAL_MS = 30000
# Im Hintergrund (Fenster nicht aktiv) reicht ein deutlich langsamerer Takt.
POLL_BACKGROUND_MIN_MS = 15000

_REPEAT_LABELS = {"off": "aus", "track": "Titel", "context": "alle"}


def _format_time(ms: int) -> str:
    """Formatiert Millisekunden als m:ss."""
    seconds = max(0, ms // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _format_now_playing(info: dict | None) -> str:
    """Baut die gesprochene Now-Playing-Ansage."""
    if not info:
        return "Es wird gerade nichts abgespielt."
    parts = [info["title"]]
    if info.get("artists"):
        parts.append(f"von {info['artists']}")
    if info.get("album"):
        parts.append(f"Album {info['album']}")
    text = ", ".join(parts) + "."

    duration = info.get("duration_ms") or 0
    progress = info.get("progress_ms") or 0
    if duration:
        remaining = max(0, duration - progress)
        text += f" {_format_time(progress)} von {_format_time(duration)}, noch {_format_time(remaining)}."
    if not info.get("is_playing"):
        text += " Pausiert."
    text += f" Zufall {'an' if info.get('shuffle_state') else 'aus'}."
    text += f" Wiederholung {_REPEAT_LABELS.get(info.get('repeat_state', 'off'), 'aus')}."
    return text


class MainWindow(wx.Frame):
    """Hauptfenster – koordiniert Menü, Tabs und Autorisierungsfluss."""

    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(800, 600))

        # Downloads laufen über die gemeinsame Warteschlange; der Rückruf
        # aktualisiert Statusleiste und Ansagen.
        downloads.set_listener(self._on_download_event)
        # Einschlaf-Timer: Zeitpunkt, an dem pausiert wird (None = aus).
        self._sleep_deadline: float | None = None
        self._hotkey_ids: list[int] = []
        # Feste IDs für die Schnellzugriffe: Die Kürzel Strg+Umschalt+1…9
        # bleiben gültig, auch wenn sich die Menüeinträge ändern.
        self._bookmark_ids = [wx.NewIdRef() for _ in range(cfg.MAX_BOOKMARKS)]

        self._create_menu()

        self.notebook = wx.Notebook(self)
        self.library_panel = LibraryPanel(self.notebook)
        self.notebook.AddPage(self.library_panel, "Mediathek")
        self.search_panel = SearchPanel(self.notebook)
        self.notebook.AddPage(self.search_panel, "Suche")
        self.queue_panel = QueuePanel(self.notebook)
        self.notebook.AddPage(self.queue_panel, "Warteschlange")
        self.discover_panel = DiscoverPanel(self.notebook)
        self.notebook.AddPage(self.discover_panel, "Entdecken")

        # Feld 0: allgemeiner Status, Feld 1: Download-Fortschritt.
        self.CreateStatusBar(2)
        self.SetStatusWidths([-3, -2])
        self.SetStatusText("Klicken Sie auf 'Hilfe > Autorisieren', um sich mit Spotify zu verbinden")
        self._create_accelerators()
        self.Bind(wx.EVT_CLOSE, self._on_close)

        # Fenstertitel ("Interpret - Titel") jedem Titelwechsel folgen lassen –
        # auch bei automatischem Weiterspringen (Autoplay/Warteschlange).
        self._now_playing_label: str | None = None
        self._now_playing_polling = False
        self._closing = False
        self._poll_interval = POLL_INTERVAL_MS
        self._now_playing_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_now_playing_timer, self._now_playing_timer)
        self._now_playing_timer.Start(self._poll_interval)

        self._sleep_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_sleep_timer, self._sleep_timer)

        self._register_media_keys()
        self.Center()
        self.notebook.SetFocus()
        # Prüft im Hintergrund, ob das gespeicherte Token noch reicht.
        threading.Thread(target=self._check_authorization, daemon=True).start()

    def _create_menu(self):
        menubar = wx.MenuBar()

        edit_menu = wx.Menu()
        self._menu_config = edit_menu.Append(
            wx.ID_ANY,
            "Einstellungen...\tCtrl+,",
            "Konfiguriert Spotify API-Credentials und Download-Ordner",
        )
        menubar.Append(edit_menu, "Bearbeiten")
        self.Bind(wx.EVT_MENU, self._on_configure, self._menu_config)

        navigation_menu = wx.Menu()
        self._menu_library = navigation_menu.Append(wx.ID_ANY, "Mediathek\tCtrl+1")
        self._menu_search = navigation_menu.Append(wx.ID_ANY, "Suche\tCtrl+2")
        self._menu_queue = navigation_menu.Append(wx.ID_ANY, "Warteschlange\tCtrl+3")
        self._menu_discover = navigation_menu.Append(wx.ID_ANY, "Entdecken\tCtrl+4")
        navigation_menu.AppendSeparator()
        self._bookmark_menu = wx.Menu()
        navigation_menu.AppendSubMenu(self._bookmark_menu, "Schnellzugriffe")
        self._menu_manage_bookmarks = navigation_menu.Append(
            wx.ID_ANY, "Schnellzugriffe verwalten …", "Entfernt gespeicherte Schnellzugriffe"
        )
        menubar.Append(navigation_menu, "Navigation")
        self.Bind(wx.EVT_MENU, lambda event: self._select_tab(0), self._menu_library)
        self.Bind(wx.EVT_MENU, lambda event: self._select_tab(1), self._menu_search)
        self.Bind(wx.EVT_MENU, lambda event: self._select_tab(2), self._menu_queue)
        self.Bind(wx.EVT_MENU, lambda event: self._select_tab(3), self._menu_discover)
        self.Bind(wx.EVT_MENU, self._on_manage_bookmarks, self._menu_manage_bookmarks)
        for slot, ref in enumerate(self._bookmark_ids):
            self.Bind(wx.EVT_MENU, lambda event, index=slot: self._open_bookmark(index), id=ref)
        self._rebuild_bookmark_menu()

        playback_menu = wx.Menu()
        self._menu_play_pause = playback_menu.Append(wx.ID_ANY, "Play/Pause\tCtrl+P")
        self._menu_next = playback_menu.Append(wx.ID_ANY, "Nächster Titel\tCtrl+N")
        self._menu_previous = playback_menu.Append(wx.ID_ANY, "Vorheriger Titel\tCtrl+B")
        self._menu_seek_forward = playback_menu.Append(wx.ID_ANY, "Vorspulen (10 s)\tCtrl+Shift+Right")
        self._menu_seek_back = playback_menu.Append(wx.ID_ANY, "Zurückspulen (10 s)\tCtrl+Shift+Left")
        self._menu_volume_up = playback_menu.Append(wx.ID_ANY, "Lauter\tCtrl++")
        self._menu_volume_down = playback_menu.Append(wx.ID_ANY, "Leiser\tCtrl+-")
        playback_menu.AppendSeparator()
        self._menu_shuffle = playback_menu.Append(wx.ID_ANY, "Zufallswiedergabe umschalten\tCtrl+Shift+S")
        self._menu_repeat = playback_menu.Append(wx.ID_ANY, "Wiederholung umschalten\tCtrl+Shift+R")
        self._menu_now_playing = playback_menu.Append(wx.ID_ANY, "Was läuft gerade?\tCtrl+J")
        playback_menu.AppendSeparator()
        self._menu_add_queue = playback_menu.Append(wx.ID_ANY, "Zur Warteschlange hinzufügen\tCtrl+Q")
        self._menu_add_playlist = playback_menu.Append(wx.ID_ANY, "Zu Playlist hinzufügen …\tCtrl+Shift+P")
        self._menu_save_library = playback_menu.Append(
            wx.ID_ANY, "In Mediathek speichern / entfernen\tCtrl+S"
        )
        playback_menu.AppendSeparator()
        self._menu_sleep = playback_menu.Append(wx.ID_ANY, "Einschlaf-Timer …\tCtrl+Shift+E")
        menubar.Append(playback_menu, "Wiedergabe")
        self.Bind(wx.EVT_MENU, self._on_toggle_play_pause, self._menu_play_pause)
        self.Bind(wx.EVT_MENU, self._on_next_track, self._menu_next)
        self.Bind(wx.EVT_MENU, self._on_previous_track, self._menu_previous)
        self.Bind(wx.EVT_MENU, self._on_volume_up, self._menu_volume_up)
        self.Bind(wx.EVT_MENU, self._on_volume_down, self._menu_volume_down)
        self.Bind(wx.EVT_MENU, self._on_now_playing, self._menu_now_playing)
        self.Bind(wx.EVT_MENU, self._on_add_to_queue, self._menu_add_queue)
        self.Bind(wx.EVT_MENU, self._on_add_to_playlist, self._menu_add_playlist)
        self.Bind(wx.EVT_MENU, self._on_toggle_library, self._menu_save_library)
        self.Bind(wx.EVT_MENU, lambda event: self._seek(SEEK_STEP_MS), self._menu_seek_forward)
        self.Bind(wx.EVT_MENU, lambda event: self._seek(-SEEK_STEP_MS), self._menu_seek_back)
        self.Bind(wx.EVT_MENU, self._on_toggle_shuffle, self._menu_shuffle)
        self.Bind(wx.EVT_MENU, self._on_cycle_repeat, self._menu_repeat)
        self.Bind(wx.EVT_MENU, self._on_sleep_dialog, self._menu_sleep)

        extras_menu = wx.Menu()
        self._item_start_player = extras_menu.Append(
            wx.ID_ANY, "Lokalen Player starten", "Startet librespot für lokale Audiowiedergabe"
        )
        self._item_stop_player = extras_menu.Append(
            wx.ID_ANY, "Lokalen Player stoppen", "Stoppt den librespot-Player"
        )
        self._item_stop_player.Enable(False)
        self._item_device = extras_menu.Append(
            wx.ID_ANY, "Wiedergabegerät …\tCtrl+Shift+D", "Wählt das Spotify-Connect-Gerät für die Wiedergabe"
        )
        extras_menu.AppendSeparator()
        self._item_downloads = extras_menu.Append(
            wx.ID_ANY, "Downloads …\tCtrl+Shift+L", "Zeigt die Download-Warteschlange und steuert sie"
        )
        self._item_open_folder = extras_menu.Append(
            wx.ID_ANY, "Download-Ordner öffnen", "Öffnet den konfigurierten Zielordner im Explorer"
        )
        extras_menu.AppendSeparator()
        self._item_export = extras_menu.Append(
            wx.ID_ANY, "Angezeigte Liste exportieren …\tCtrl+E", "Speichert die aktuelle Liste als CSV oder M3U"
        )
        self._item_import = extras_menu.Append(
            wx.ID_ANY, "Playlist aus Datei importieren …\tCtrl+Shift+I",
            "Legt aus den Spotify-Links einer Datei eine neue Playlist an",
        )
        extras_menu.AppendSeparator()
        self._item_log = extras_menu.Append(
            wx.ID_ANY, "Protokoll …\tCtrl+Shift+G", "Zeigt gesammelte Fehler und Ereignisse"
        )
        menubar.Append(extras_menu, "Extras")
        self.Bind(wx.EVT_MENU, self._on_start_player, self._item_start_player)
        self.Bind(wx.EVT_MENU, self._on_stop_player, self._item_stop_player)
        self.Bind(wx.EVT_MENU, self._on_choose_device, self._item_device)
        self.Bind(wx.EVT_MENU, self._on_show_downloads, self._item_downloads)
        self.Bind(wx.EVT_MENU, self._on_open_download_folder, self._item_open_folder)
        self.Bind(wx.EVT_MENU, self._on_export_view, self._item_export)
        self.Bind(wx.EVT_MENU, lambda event: import_playlist(self), self._item_import)
        self.Bind(wx.EVT_MENU, lambda event: show_log(self), self._item_log)

        help_menu = wx.Menu()
        self._item_shortcuts = help_menu.Append(
            wx.ID_ANY, "Tastenkürzel …\tF1", "Zeigt alle Tastenkürzel dieser App"
        )
        auth_item = help_menu.Append(wx.ID_ANY, "Autorisieren...", "Autorisiert die App bei Spotify")
        about_item = help_menu.Append(wx.ID_ABOUT, "Über", "Informationen über diese App")
        menubar.Append(help_menu, "Hilfe")
        self.Bind(wx.EVT_MENU, lambda event: show_shortcuts(self), self._item_shortcuts)
        self.Bind(wx.EVT_MENU, self._on_auth, auth_item)
        self.Bind(wx.EVT_MENU, self._on_about, about_item)

        self.SetMenuBar(menubar)

    def _create_accelerators(self):
        entries = [
            (wx.ACCEL_CTRL, ord(","), self._menu_config.GetId()),
            (wx.ACCEL_CTRL, ord("1"), self._menu_library.GetId()),
            (wx.ACCEL_CTRL, ord("2"), self._menu_search.GetId()),
            (wx.ACCEL_CTRL, ord("3"), self._menu_queue.GetId()),
            (wx.ACCEL_CTRL, ord("4"), self._menu_discover.GetId()),
            (wx.ACCEL_CTRL, ord("P"), self._menu_play_pause.GetId()),
            (wx.ACCEL_CTRL, ord("N"), self._menu_next.GetId()),
            (wx.ACCEL_CTRL, ord("B"), self._menu_previous.GetId()),
            (wx.ACCEL_CTRL, ord("+"), self._menu_volume_up.GetId()),
            (wx.ACCEL_CTRL, ord("="), self._menu_volume_up.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_NUMPAD_ADD, self._menu_volume_up.GetId()),
            (wx.ACCEL_CTRL, ord("-"), self._menu_volume_down.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_NUMPAD_SUBTRACT, self._menu_volume_down.GetId()),
            (wx.ACCEL_CTRL, ord("J"), self._menu_now_playing.GetId()),
            (wx.ACCEL_CTRL, ord("Q"), self._menu_add_queue.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("P"), self._menu_add_playlist.GetId()),
            (wx.ACCEL_CTRL, ord("S"), self._menu_save_library.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, wx.WXK_RIGHT, self._menu_seek_forward.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, wx.WXK_LEFT, self._menu_seek_back.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("S"), self._menu_shuffle.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("R"), self._menu_repeat.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("E"), self._menu_sleep.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("D"), self._item_device.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("L"), self._item_downloads.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("G"), self._item_log.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("I"), self._item_import.GetId()),
            (wx.ACCEL_CTRL, ord("E"), self._item_export.GetId()),
            (wx.ACCEL_NORMAL, wx.WXK_F1, self._item_shortcuts.GetId()),
        ]
        # Strg+Umschalt+1 … 9 springen zu den Schnellzugriffen – unabhängig
        # davon, ob der Platz gerade belegt ist.
        entries += [
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord(str(slot + 1)), ref.GetId())
            for slot, ref in enumerate(self._bookmark_ids)
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

    def _register_media_keys(self):
        """Registriert die systemweiten Medientasten (nur Windows).

        Schlägt die Registrierung fehl, weil eine andere Anwendung die Taste
        schon belegt, bleibt es dabei – die Menü-Kurztasten funktionieren
        weiterhin.
        """
        if not hasattr(self, "RegisterHotKey"):
            return
        actions = {
            "play_pause": self._on_toggle_play_pause,
            "next": self._on_next_track,
            "previous": self._on_previous_track,
            "stop": self._on_stop_playback,
        }
        for offset, (name, key) in enumerate(MEDIA_KEYS.items()):
            hotkey_id = _HOTKEY_ID_BASE + offset
            try:
                if self.RegisterHotKey(hotkey_id, 0, key):
                    self.Bind(wx.EVT_HOTKEY, actions[name], id=hotkey_id)
                    self._hotkey_ids.append(hotkey_id)
            except Exception:
                continue

    def _unregister_media_keys(self):
        for hotkey_id in self._hotkey_ids:
            try:
                self.UnregisterHotKey(hotkey_id)
            except Exception:
                pass
        self._hotkey_ids = []

    def media_shortcuts(self) -> list[tuple[str, str]]:
        """Liefert die tatsächlich registrierten Medientasten für die Kürzelübersicht."""
        names = {
            "play_pause": "Wiedergabe/Pause",
            "next": "Nächster Titel",
            "previous": "Vorheriger Titel",
            "stop": "Wiedergabe pausieren",
        }
        keys = list(MEDIA_KEYS)
        return [
            (f"Medientaste {names[keys[hotkey_id - _HOTKEY_ID_BASE]]}",
             names[keys[hotkey_id - _HOTKEY_ID_BASE]])
            for hotkey_id in self._hotkey_ids
            if 0 <= hotkey_id - _HOTKEY_ID_BASE < len(keys)
        ]

    def _check_authorization(self):
        """Prüft im Hintergrund, ob das gespeicherte Token alle Rechte hat."""
        if not cfg.has_credentials():
            return
        client.get()
        if client.missing_scopes:
            call_after(
                self.announce,
                "Neue Berechtigungen nötig – bitte 'Hilfe > Autorisieren' erneut ausführen.",
            )

    def _rebuild_bookmark_menu(self):
        """Baut das Schnellzugriff-Menü aus den gespeicherten Einträgen neu.

        Dadurch stehen die belegten Plätze auch in der Kürzelübersicht (F1).
        """
        for item in list(self._bookmark_menu.GetMenuItems()):
            self._bookmark_menu.Delete(item)
        bookmarks = cfg.get_bookmarks()
        if not bookmarks:
            placeholder = self._bookmark_menu.Append(
                wx.ID_ANY, "Noch keine gespeichert", "Kontextmenü: „Als Schnellzugriff merken"
            )
            placeholder.Enable(False)
            return
        kinds = {"album": "Album", "artist": "Künstler", "playlist": "Playlist", "show": "Podcast"}
        for slot, entry in enumerate(bookmarks):
            kind = kinds.get(entry.get("type", ""), "Eintrag")
            self._bookmark_menu.Append(
                self._bookmark_ids[slot],
                f"{slot + 1} {entry.get('name', '')} ({kind})\tCtrl+Shift+{slot + 1}",
            )

    def _open_bookmark(self, index: int):
        """Öffnet den Schnellzugriff mit der Nummer ``index`` + 1."""
        bookmarks = cfg.get_bookmarks()
        if index >= len(bookmarks):
            self.announce(f"Schnellzugriff {index + 1} ist nicht belegt")
            return
        entry = bookmarks[index]
        item = {"type": entry["type"], "id": entry["id"], "name": entry.get("name", "")}
        panel = self.library_panel
        self._select_tab(0)
        opener = {
            "album": panel.goto_album,
            "artist": panel.goto_artist,
            "playlist": panel.goto_playlist,
            "show": panel.goto_show,
        }.get(entry["type"])
        if not opener:
            self.announce("Dieser Schnellzugriff lässt sich nicht öffnen")
            return
        self.announce(f"Schnellzugriff {index + 1}: {entry.get('name', '')}")
        opener(item)

    def _on_manage_bookmarks(self, event):
        """Entfernt ausgewählte Schnellzugriffe."""
        bookmarks = cfg.get_bookmarks()
        if not bookmarks:
            self.announce("Es sind keine Schnellzugriffe gespeichert")
            return
        labels = [f"{slot + 1} {entry.get('name', '')}" for slot, entry in enumerate(bookmarks)]
        dialog = wx.MultiChoiceDialog(
            self, "Schnellzugriffe zum Entfernen auswählen:", "Schnellzugriffe", labels
        )
        if dialog.ShowModal() == wx.ID_OK:
            remove = set(dialog.GetSelections())
            kept = [entry for slot, entry in enumerate(bookmarks) if slot not in remove]
            if remove:
                cfg.save_bookmarks(kept)
                self._rebuild_bookmark_menu()
                self._create_accelerators()
                self.announce(f"{len(remove)} Schnellzugriff(e) entfernt")
        dialog.Destroy()

    def _on_export_view(self, event):
        """Exportiert die Liste des aktiven Tabs."""
        page = self.notebook.GetCurrentPage()
        export = getattr(page, "_export_view", None)
        if export:
            export()
        else:
            self.announce("Diese Ansicht lässt sich nicht exportieren")

    def _select_tab(self, index: int):
        self.notebook.SetSelection(index)
        page = self.notebook.GetPage(index)
        if hasattr(page, "focus_default"):
            page.focus_default()
        else:
            page.SetFocus()

    def _on_configure(self, event):
        """Öffnet den Konfigurationsdialog; greift nicht auf interne Widgets zu."""
        # Diese Werte gibt librespot nur beim Start mit – ändern sie sich,
        # muss der lokale Player neu starten.
        old_player_settings = (
            cfg.get_playback_quality(),
            cfg.get_volume_normalisation(),
            cfg.get_initial_volume(),
        )
        old_client_id = cfg.get_client_id()
        old_client_secret = cfg.get_client_secret()
        dialog = ConfigurationDialog(self)
        if dialog.ShowModal() == wx.ID_OK:
            if dialog.save():
                if (cfg.get_client_id(), cfg.get_client_secret()) != (old_client_id, old_client_secret):
                    # Sonst arbeitet der gecachte SpotifyOAuth mit den alten Credentials weiter
                    client.reset_auth()
                new_player_settings = (
                    cfg.get_playback_quality(),
                    cfg.get_volume_normalisation(),
                    cfg.get_initial_volume(),
                )
                if new_player_settings != old_player_settings:
                    from librespot_manager import librespot
                    librespot.stop()
                    client.clear_local_device_cache()
                    self.mark_local_player_stopped()
                    self.SetStatusText(
                        "Einstellungen gespeichert. Lokaler Player wurde für die neuen "
                        "Wiedergabeeinstellungen gestoppt."
                    )
                else:
                    self.SetStatusText("Einstellungen gespeichert")
                wx.MessageBox("Einstellungen gespeichert!", "Erfolg", wx.ICON_INFORMATION)
            else:
                wx.MessageBox("Fehler beim Speichern der Einstellungen.", "Fehler", wx.ICON_ERROR)
        dialog.Destroy()

    def _on_auth(self, event):
        """Startet den automatisierten OAuth2-Autorisierungsfluss im Browser."""
        if not cfg.has_credentials():
            wx.MessageBox(
                "Bitte zuerst Spotify API konfigurieren!\n"
                "Menü: Bearbeiten > Einstellungen",
                "Konfiguration erforderlich",
                wx.ICON_WARNING,
            )
            self._on_configure(None)
            return

        self.SetStatusText("Autorisierung im Browser läuft...")
        
        # Startet den Prozess in einem Thread, um das UI nicht zu blockieren
        import threading
        def do_auth():
            try:
                if client.start_auth_flow():
                    call_after(self.SetStatusText, "Erfolgreich mit Spotify verbunden!")
                    call_after(wx.MessageBox, "Autorisierung erfolgreich!", "Erfolg", wx.ICON_INFORMATION)
                else:
                    call_after(self.SetStatusText, "Autorisierung fehlgeschlagen.")
                    call_after(wx.MessageBox, "Fehler bei der Autorisierung.", "Fehler", wx.ICON_ERROR)
            except Exception as e:
                call_after(wx.MessageBox, f"Fehler: {e}", "Fehler", wx.ICON_ERROR)

        threading.Thread(target=do_auth, daemon=True).start()

    def _on_start_player(self, event):
        """Startet librespot als lokalen Spotify Connect-Player."""
        self.SetStatusText("Lokaler Player wird gestartet...")
        self._item_start_player.Enable(False)

        def do_start():
            try:
                client.activate_local_player()
                call_after(self.SetStatusText, "Lokaler Player läuft – bereit zur Wiedergabe")
                call_after(self.mark_local_player_running)
            except Exception as e:
                call_after(self.SetStatusText, "Fehler beim Starten des Players")
                call_after(self._item_start_player.Enable, True)
                call_after(wx.MessageBox, str(e), "Player-Fehler", wx.ICON_ERROR)

        threading.Thread(target=do_start, daemon=True).start()

    def _on_stop_player(self, event):
        """Stoppt den librespot-Player."""
        from librespot_manager import librespot
        librespot.stop()
        client.clear_local_device_cache()
        self.SetStatusText("Lokaler Player gestoppt")
        self.mark_local_player_stopped()

    def _on_choose_device(self, event):
        """Lädt die verfügbaren Connect-Geräte und öffnet die Auswahl."""
        self.announce("Lade Wiedergabegeräte …")

        def worker():
            try:
                devices = client.list_devices()
            except Exception as e:
                call_after(self.announce, f"Geräte konnten nicht geladen werden: {e}")
                call_after(wx.MessageBox, str(e), "Fehler", wx.ICON_ERROR)
                return
            call_after(self._show_device_dialog, devices)

        threading.Thread(target=worker, daemon=True).start()

    def _show_device_dialog(self, devices: list[dict]):
        """Zeigt die Geräteauswahl; leerer Name bedeutet lokaler Player."""
        labels = ["Lokaler SpotiFlix-Player (Standard)"]
        names = [""]
        for device in devices:
            suffix = " – aktiv" if device.get("is_active") else ""
            labels.append(f"{device['name']} ({device.get('type', 'Gerät')}){suffix}")
            names.append(device["name"])

        current = cfg.get_playback_device()
        selection = names.index(current) if current in names else 0
        dialog = wx.SingleChoiceDialog(
            self, "Wiedergabegerät auswählen:", "Wiedergabegerät", labels
        )
        dialog.SetSelection(selection)
        if dialog.ShowModal() == wx.ID_OK:
            chosen = names[dialog.GetSelection()]
            cfg.save_playback_device(chosen)
            client.clear_local_device_cache()
            self.announce(f"Wiedergabegerät: {labels[dialog.GetSelection()]}")
        dialog.Destroy()

    # -- Einschlaf-Timer -----------------------------------------------------

    def _on_sleep_dialog(self, event):
        labels = [label for _minutes, label in SLEEP_CHOICES]
        dialog = wx.SingleChoiceDialog(self, "Wiedergabe pausieren nach:", "Einschlaf-Timer", labels)
        if dialog.ShowModal() == wx.ID_OK:
            minutes = SLEEP_CHOICES[dialog.GetSelection()][0]
            self._set_sleep_timer(minutes)
        dialog.Destroy()

    def _set_sleep_timer(self, minutes: int):
        self._sleep_timer.Stop()
        if minutes <= 0:
            self._sleep_deadline = None
            self.announce("Einschlaf-Timer aus")
            return
        self._sleep_deadline = time.time() + minutes * 60
        self._sleep_timer.StartOnce(minutes * 60 * 1000)
        self.announce(f"Einschlaf-Timer: Wiedergabe pausiert in {minutes} Minuten")

    def _on_sleep_timer(self, event):
        """Pausiert die Wiedergabe, wenn der Einschlaf-Timer abgelaufen ist."""
        self._sleep_deadline = None

        def worker():
            try:
                client.pause_playback()
            except Exception:
                pass
            call_after(self.announce, "Einschlaf-Timer abgelaufen – Wiedergabe pausiert")

        threading.Thread(target=worker, daemon=True).start()

    def _sleep_remaining_text(self) -> str:
        """Beschreibt die Restzeit des Einschlaf-Timers (leer, wenn aus)."""
        if not self._sleep_deadline:
            return ""
        remaining = max(0, int(self._sleep_deadline - time.time()))
        # Aufrunden: direkt nach dem Stellen sollen es „30 Minuten" sein, nicht 29.
        return f" Einschlaf-Timer: noch {max(1, -(-remaining // 60))} Minuten."

    def mark_local_player_running(self):
        self._item_start_player.Enable(False)
        self._item_stop_player.Enable(True)
        # Es wird gleich etwas laufen – wieder im schnellen Takt nachsehen.
        self.reset_now_playing_poll()

    def mark_local_player_stopped(self):
        self._item_start_player.Enable(True)
        self._item_stop_player.Enable(False)
        self.set_now_playing(None)

    def set_now_playing(self, label: str | None):
        """Setzt den Fenstertitel auf 'Interpret - Titel' (oder zurück auf den App-Namen)."""
        self._now_playing_label = label or None
        self.SetTitle(label if label else APP_NAME)

    def _on_now_playing_timer(self, event):
        """Pollt die laufende Wiedergabe, damit der Fenstertitel jedem Titelwechsel folgt."""
        if self._now_playing_polling or self._closing:
            return
        self._now_playing_polling = True

        def worker():
            try:
                info = client.now_playing()
            except Exception:
                info = None
            call_after(self._refresh_now_playing_title, info)

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_now_playing_title(self, info: dict | None):
        """Aktualisiert den Fenstertitel nur, wenn sich der laufende Titel geändert hat."""
        self._now_playing_polling = False
        label = None
        if info and info.get("title"):
            artists = info.get("artists") or ""
            label = f"{artists} - {info['title']}" if artists else info["title"]
        if label != self._now_playing_label:
            self.set_now_playing(label)
        self._tune_polling(playing=bool(info and info.get("is_playing")))

    def _tune_polling(self, playing: bool):
        """Verlängert den Polling-Takt, solange nichts läuft oder das Fenster ruht."""
        if playing:
            interval = POLL_INTERVAL_MS
        else:
            interval = min(self._poll_interval * 2, POLL_MAX_INTERVAL_MS)
        if not self.IsActive():
            interval = max(interval, POLL_BACKGROUND_MIN_MS)
        self._set_poll_interval(interval)

    def _set_poll_interval(self, interval: int):
        if interval == self._poll_interval or self._closing:
            return
        self._poll_interval = interval
        self._now_playing_timer.Start(interval)

    def reset_now_playing_poll(self):
        """Setzt den Polling-Takt zurück – z. B. wenn gerade Wiedergabe startet."""
        self._set_poll_interval(POLL_INTERVAL_MS)

    def announce(self, message: str, interrupt: bool = False):
        """Zentrale Kurzansage für Statusänderungen (Statusleiste + NVDA/Braille).

        ``interrupt=True`` bricht eine laufende Ansage ab – sinnvoll nur bei
        schnell wiederholten Werten wie der Lautstärke. Sonst würde jede
        Statusmeldung NVDAs eigene Fokusansage abschneiden.
        """
        self.SetStatusText(message)
        # NVDA spricht die Meldung und zeigt sie auf der Braillezeile an.
        nvda.announce(message, interrupt=interrupt)

    def _on_download_event(self, job):
        """Rückruf der Download-Warteschlange (läuft im Worker-Thread)."""
        call_after(self._refresh_download_status)
        if job.status == STATUS_DONE:
            call_after(self.announce, f"Download abgeschlossen: {job.name}")
        elif job.status == STATUS_FAILED:
            call_after(
                self.announce,
                f"Download fehlgeschlagen: {job.name} – {applog.short_error(job.error)}",
            )

    def _refresh_download_status(self):
        """Schreibt den Stand der Download-Warteschlange in Statusfeld 1."""
        active = downloads.active_jobs()
        if not active:
            failed = [job for job in downloads.jobs() if job.status == STATUS_FAILED]
            self.SetStatusText(
                f"{len(failed)} Download(s) fehlgeschlagen – Strg+Umschalt+L" if failed else "", 1
            )
            return
        running = [job for job in active if job.status != "wartet"]
        segments = [job.label() for job in running] or [f"{len(active)} in der Warteschlange"]
        waiting = len(active) - len(running)
        text = " | ".join(segments)
        if waiting:
            text += f" (+{waiting} wartend)"
        prefix = "Downloads: " if len(active) > 1 else "Download: "
        self.SetStatusText(prefix + text, 1)

    def _on_show_downloads(self, event):
        """Öffnet die Download-Warteschlange."""
        show_downloads(self)
        self._refresh_download_status()

    def _on_open_download_folder(self, event):
        target = cfg.get_download_dir()
        if open_folder(target):
            self.announce(f"Download-Ordner geöffnet: {target}")
        else:
            self.announce("Download-Ordner konnte nicht geöffnet werden")

    def _run_playback_action(self, action, success_message: str, now_playing: bool = False):
        def worker():
            try:
                result = action()
                if result is False or result is None:
                    call_after(wx.MessageBox, "Zuerst autorisieren!", "Fehler", wx.ICON_ERROR)
                    return
                if type(result) is int:
                    # Lautstärke wird schnell wiederholt – hier ist Abbrechen
                    # der laufenden Ansage gewollt.
                    call_after(self.announce, f"Lautstärke {result} Prozent", True)
                else:
                    call_after(self.mark_local_player_running)
                    track_name = None
                    if now_playing:
                        try:
                            track_name = client.current_track_name()
                        except Exception:
                            track_name = None
                    if track_name:
                        call_after(self.set_now_playing, track_name)
                        call_after(self.announce, track_name)
                    else:
                        call_after(self.announce, success_message)
            except Exception as e:
                call_after(wx.MessageBox, str(e), "Wiedergabefehler", wx.ICON_WARNING)

        threading.Thread(target=worker, daemon=True).start()

    def _run_async(self, action, describe, empty_message: str = "Zuerst autorisieren!"):
        """Führt eine API-Aktion im Hintergrund aus und sagt das Ergebnis an."""

        def worker():
            try:
                result = action()
                if result is None:
                    call_after(self.announce, empty_message)
                    return
                call_after(self.announce, describe(result))
            except Exception as e:
                call_after(wx.MessageBox, str(e), "Wiedergabefehler", wx.ICON_WARNING)

        threading.Thread(target=worker, daemon=True).start()

    def _on_toggle_shuffle(self, event):
        self._run_async(
            client.set_shuffle,
            lambda state: f"Zufallswiedergabe {'an' if state else 'aus'}",
        )

    def _on_cycle_repeat(self, event):
        self._run_async(
            client.cycle_repeat,
            lambda state: f"Wiederholung {_REPEAT_LABELS.get(state, state)}",
        )

    def _seek(self, delta_ms: int):
        """Spult vor oder zurück und sagt die neue Position an."""
        self._run_async(
            lambda: client.seek_relative(delta_ms),
            lambda result: f"{format_position(result[0])} von {format_position(result[1])}",
            empty_message="Es läuft gerade nichts zum Spulen",
        )

    def _on_stop_playback(self, event):
        """Medientaste „Stopp": pausiert die Wiedergabe."""
        self._run_playback_action(client.pause_playback, "Wiedergabe pausiert")

    def _on_toggle_play_pause(self, event):
        self._run_playback_action(client.toggle_play_pause, "Play/Pause")

    def _on_next_track(self, event):
        self._run_playback_action(client.next_track, "Nächster Titel", now_playing=True)

    def _on_previous_track(self, event):
        self._run_playback_action(client.previous_track, "Vorheriger Titel", now_playing=True)

    def _on_volume_up(self, event):
        self._run_playback_action(lambda: client.change_volume(10), "Lauter")

    def _on_volume_down(self, event):
        self._run_playback_action(lambda: client.change_volume(-10), "Leiser")

    def _on_now_playing(self, event):
        """Sagt die aktuelle Wiedergabe an (Titel, Zeit, Zufall/Wiederholung)."""
        def worker():
            try:
                info = client.now_playing()
            except Exception:
                info = None
            call_after(self.announce, _format_now_playing(info) + self._sleep_remaining_text())

        threading.Thread(target=worker, daemon=True).start()

    def refresh_bookmarks(self):
        """Wird aufgerufen, wenn sich die Schnellzugriffe geändert haben."""
        self._rebuild_bookmark_menu()
        self._create_accelerators()

    def enqueue(self, rows: list[dict]):
        """Trägt Titel in den Warteschlangen-Tab ein (für die Bearbeitung)."""
        self.queue_panel.add_items(rows)

    def _selected_items(self):
        """Liefert die markierten Elemente des aktiven Tabs (oder eine leere Liste)."""
        page = self.notebook.GetCurrentPage()
        getter = getattr(page, "get_selected_items", None)
        if getter:
            return page, getter()
        single = getattr(page, "get_selected_item", None)
        item = single() if single else None
        return page, [item] if item else []

    def _on_add_to_queue(self, event):
        page, items = self._selected_items()
        if not items:
            self.announce("Kein Titel ausgewählt")
            return
        from ui.context_actions import add_to_queue
        add_to_queue(page, items)

    def _on_add_to_playlist(self, event):
        page, items = self._selected_items()
        if not items:
            self.announce("Kein Titel ausgewählt")
            return
        from ui.context_actions import add_to_playlist
        add_to_playlist(page, items)

    def _on_toggle_library(self, event):
        page, items = self._selected_items()
        if not items:
            self.announce("Kein Eintrag ausgewählt")
            return
        from ui.context_actions import toggle_library
        toggle_library(page, items)

    def _on_close(self, event):
        """Stoppt lokale Wiedergabe zuverlässig beim Beenden.

        Worker-Threads (Downloads, Wiedergabe, Now-Playing) laufen als Daemons
        weiter. Das Flag sorgt dafür, dass ihre ``call_after``-Rückrufe nicht
        mehr auf zerstörte Widgets zugreifen.
        """
        self._closing = True
        mark_shutting_down()
        self._now_playing_timer.Stop()
        self._sleep_timer.Stop()
        self._unregister_media_keys()
        # Laufende Downloads abbrechen, damit keine halben Dateien entstehen.
        downloads.set_listener(None)
        downloads.cancel_all()
        try:
            from librespot_manager import librespot
            librespot.stop()
            client.clear_local_device_cache()
        finally:
            self.Destroy()

    def _on_about(self, event):
        about = wx.AboutDialogInfo()
        about.Name = APP_NAME
        about.Version = "1.1"
        about.Description = (
            "Ein barrierefreier wxPython-Player für Spotify\n"
            f"Sprachausgabe: {nvda.output_name()}"
        )
        about.WebSite = ("https://github.com/opencode", APP_NAME)
        wx.AboutBox(about)
