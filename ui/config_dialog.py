"""
Dialog für Spotify API Konfiguration
"""
import wx
import config as cfg


class ConfigurationDialog(wx.Dialog):
    """Konfigurationsdialog – validiert intern und gibt Daten über Methoden zurück."""

    def __init__(self, parent):
        super().__init__(parent, title="Einstellungen", size=(650, 700))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        info_text = wx.StaticText(
            panel,
            label="Geben Sie Ihre Spotify API-Credentials ein:\n"
                  "Diese werden sicher im System-Schlüsselspeicher gespeichert.",
        )
        sizer.Add(info_text, 0, wx.ALL | wx.EXPAND, 10)
        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 5)

        client_id_label = wx.StaticText(panel, label="Client-ID:")
        self.client_id_input = wx.TextCtrl(panel)
        self.client_id_input.SetToolTip("Ihre Spotify Client-ID vom Developer Dashboard")
        saved_id = cfg.get_client_id()
        if saved_id:
            self.client_id_input.SetValue(saved_id)
        sizer.Add(client_id_label, 0, wx.TOP, 5)
        sizer.Add(self.client_id_input, 1, wx.ALL | wx.EXPAND, 10)

        client_secret_label = wx.StaticText(panel, label="Client-Secret:")
        self.client_secret_input = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        self.client_secret_input.SetToolTip("Ihr Spotify Client-Secret vom Developer Dashboard")
        saved_secret = cfg.get_client_secret()
        if saved_secret:
            self.client_secret_input.SetValue(saved_secret)
        sizer.Add(client_secret_label, 0, wx.TOP, 5)
        sizer.Add(self.client_secret_input, 1, wx.ALL | wx.EXPAND, 10)

        playback_quality_label = wx.StaticText(panel, label="Wiedergabequalität:")
        self.playback_quality_combo = wx.ComboBox(
            panel,
            choices=list(cfg.PLAYBACK_QUALITIES.values()),
            style=wx.CB_READONLY,
        )
        playback_values = list(cfg.PLAYBACK_QUALITIES.keys())
        self._playback_quality_values = playback_values
        self.playback_quality_combo.SetSelection(playback_values.index(cfg.get_playback_quality()))
        self.playback_quality_combo.SetToolTip("Bitrate für lokale Wiedergabe über librespot")
        sizer.Add(playback_quality_label, 0, wx.TOP, 5)
        sizer.Add(self.playback_quality_combo, 1, wx.ALL | wx.EXPAND, 10)

        self.volume_normalisation = wx.CheckBox(panel, label="Lautstärke normalisieren")
        self.volume_normalisation.SetValue(cfg.get_volume_normalisation())
        self.volume_normalisation.SetToolTip(
            "Gleicht Lautstärkeunterschiede zwischen Alben aus (librespot). "
            "Die Änderung greift, sobald der lokale Player neu startet."
        )
        sizer.Add(self.volume_normalisation, 0, wx.ALL, 10)

        initial_volume_label = wx.StaticText(panel, label="Startlautstärke (Prozent):")
        self.initial_volume = wx.SpinCtrl(panel, min=0, max=100, initial=cfg.get_initial_volume())
        self.initial_volume.SetName("Startlautstärke in Prozent")
        self.initial_volume.SetToolTip("Lautstärke, mit der der lokale Player startet")
        sizer.Add(initial_volume_label, 0, wx.TOP, 5)
        sizer.Add(self.initial_volume, 0, wx.ALL | wx.EXPAND, 10)

        autoplay_label = wx.StaticText(panel, label="Autoplay:")
        self.autoplay_combo = wx.ComboBox(
            panel,
            choices=list(cfg.AUTOPLAY_MODES.values()),
            style=wx.CB_READONLY,
        )
        autoplay_values = list(cfg.AUTOPLAY_MODES.keys())
        self._autoplay_values = autoplay_values
        self.autoplay_combo.SetSelection(autoplay_values.index(cfg.get_autoplay()))
        self.autoplay_combo.SetToolTip(
            "Was passiert nach einem einzelnen Titel: Aus = nur dieser Titel; "
            "In Playlist/Album fortsetzen = der Kontext läuft weiter; "
            "Immer weiterspielen = auch einzelne Titel reihen die folgende Liste in die Warteschlange."
        )
        sizer.Add(autoplay_label, 0, wx.TOP, 5)
        sizer.Add(self.autoplay_combo, 1, wx.ALL | wx.EXPAND, 10)

        verbosity_label = wx.StaticText(panel, label="Ansagen (Screenreader):")
        self.verbosity_combo = wx.ComboBox(
            panel,
            choices=list(cfg.VERBOSITY_MODES.values()),
            style=wx.CB_READONLY,
        )
        verbosity_values = list(cfg.VERBOSITY_MODES.keys())
        self._verbosity_values = verbosity_values
        self.verbosity_combo.SetSelection(verbosity_values.index(cfg.get_verbosity()))
        self.verbosity_combo.SetToolTip(
            "Ausführlich sagt auch Zwischenmeldungen wie „Lade Alben …“ an; "
            "Kurz sagt nur Ergebnisse und Fehler an (die Statusleiste zeigt weiterhin alles)."
        )
        sizer.Add(verbosity_label, 0, wx.TOP, 5)
        sizer.Add(self.verbosity_combo, 1, wx.ALL | wx.EXPAND, 10)

        download_method_label = wx.StaticText(panel, label="Download-Methode:")
        self.download_method_combo = wx.ComboBox(
            panel,
            choices=list(cfg.DOWNLOAD_METHODS.values()),
            style=wx.CB_READONLY,
        )
        method_values = list(cfg.DOWNLOAD_METHODS.keys())
        self._download_method_values = method_values
        self.download_method_combo.SetSelection(method_values.index(cfg.get_download_method()))
        self.download_method_combo.SetToolTip(
            "librespot lädt den echten Spotify-Stream (OGG, Premium für 320 kbit/s); "
            "spotdl bezieht das Audio über YouTube als MP3."
        )
        sizer.Add(download_method_label, 0, wx.TOP, 5)
        sizer.Add(self.download_method_combo, 1, wx.ALL | wx.EXPAND, 10)

        download_format_label = wx.StaticText(panel, label="Download-Format (librespot):")
        self.download_format_combo = wx.ComboBox(
            panel,
            choices=list(cfg.DOWNLOAD_FORMATS.values()),
            style=wx.CB_READONLY,
        )
        format_values = list(cfg.DOWNLOAD_FORMATS.keys())
        self._download_format_values = format_values
        self.download_format_combo.SetSelection(format_values.index(cfg.get_download_format()))
        self.download_format_combo.SetToolTip(
            "Dateiformat für Downloads über librespot. OGG ist der unveränderte "
            "Spotify-Stream; MP3 und M4A werden per ffmpeg umgewandelt (ffmpeg muss "
            "installiert sein)."
        )
        sizer.Add(download_format_label, 0, wx.TOP, 5)
        sizer.Add(self.download_format_combo, 1, wx.ALL | wx.EXPAND, 10)

        download_quality_label = wx.StaticText(panel, label="Downloadqualität:")
        self.download_quality_combo = wx.ComboBox(
            panel,
            choices=list(cfg.DOWNLOAD_QUALITIES.values()),
            style=wx.CB_READONLY,
        )
        download_values = list(cfg.DOWNLOAD_QUALITIES.keys())
        self._download_quality_values = download_values
        self.download_quality_combo.SetSelection(download_values.index(cfg.get_download_quality()))
        self.download_quality_combo.SetToolTip("Bitrate für Downloads über spotdl")
        sizer.Add(download_quality_label, 0, wx.TOP, 5)
        sizer.Add(self.download_quality_combo, 1, wx.ALL | wx.EXPAND, 10)

        parallel_label = wx.StaticText(panel, label="Gleichzeitige Downloads:")
        self.download_parallel = wx.SpinCtrl(
            panel, min=1, max=cfg.MAX_DOWNLOAD_PARALLEL, initial=cfg.get_download_parallel()
        )
        self.download_parallel.SetName("Gleichzeitige Downloads")
        self.download_parallel.SetToolTip(
            "Wie viele Downloads gleichzeitig laufen; der Rest wartet in der Warteschlange."
        )
        sizer.Add(parallel_label, 0, wx.TOP, 5)
        sizer.Add(self.download_parallel, 0, wx.ALL | wx.EXPAND, 10)

        download_label = wx.StaticText(panel, label="Download-Ordner:")
        self.download_dir_input = wx.DirPickerCtrl(
            panel,
            path=cfg.get_download_dir(),
            message="Download-Ordner auswählen",
            style=wx.DIRP_USE_TEXTCTRL,
        )
        self.download_dir_input.SetToolTip("Zielordner für Downloads über das Kontextmenü")
        sizer.Add(download_label, 0, wx.TOP, 5)
        sizer.Add(self.download_dir_input, 1, wx.ALL | wx.EXPAND, 10)

        template_label = wx.StaticText(panel, label="Download-Ordnerstruktur:")
        self.download_template_input = wx.TextCtrl(panel)
        self.download_template_input.SetValue(cfg.get_download_template())
        self.download_template_input.SetToolTip("Beispiel: %artist%/%album%/%num,2% - %title%")
        sizer.Add(template_label, 0, wx.TOP, 5)
        sizer.Add(self.download_template_input, 1, wx.ALL | wx.EXPAND, 10)

        hint_text = wx.StaticText(
            panel,
            label="Credentials finden Sie unter: https://developer.spotify.com/dashboard",
        )
        sizer.Add(hint_text, 0, wx.ALL | wx.EXPAND, 10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        btn_save = wx.Button(panel, id=wx.ID_OK, label="Speichern")
        btn_save.SetDefault()
        btn_cancel = wx.Button(panel, id=wx.ID_CANCEL, label="Abbrechen")
        btn_box.Add(btn_save, 1, wx.ALL | wx.EXPAND, 5)
        btn_box.Add(btn_cancel, 1, wx.ALL | wx.EXPAND, 5)
        sizer.Add(btn_box, 0, wx.ALL | wx.EXPAND, 10)

        panel.SetSizer(sizer)
        self.CenterOnParent()

        # Validierung übernimmt der Dialog selbst
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _on_ok(self, event):
        if bool(self.get_client_id()) != bool(self.get_client_secret()):
            wx.MessageBox("Bitte Client-ID und Client-Secret gemeinsam ausfüllen.", "Fehler", wx.ICON_ERROR)
            return
        if not self.get_download_dir():
            wx.MessageBox("Bitte einen Download-Ordner auswählen.", "Fehler", wx.ICON_ERROR)
            return
        if not self.get_download_template():
            wx.MessageBox("Bitte eine Download-Ordnerstruktur eintragen.", "Fehler", wx.ICON_ERROR)
            return
        self.EndModal(wx.ID_OK)

    def get_client_id(self) -> str:
        return self.client_id_input.GetValue().strip()

    def get_client_secret(self) -> str:
        return self.client_secret_input.GetValue().strip()

    def get_download_dir(self) -> str:
        return self.download_dir_input.GetPath().strip()

    def get_playback_quality(self) -> str:
        return self._playback_quality_values[self.playback_quality_combo.GetSelection()]

    def get_download_quality(self) -> str:
        return self._download_quality_values[self.download_quality_combo.GetSelection()]

    def get_download_method(self) -> str:
        return self._download_method_values[self.download_method_combo.GetSelection()]

    def get_download_format(self) -> str:
        return self._download_format_values[self.download_format_combo.GetSelection()]

    def get_autoplay(self) -> str:
        return self._autoplay_values[self.autoplay_combo.GetSelection()]

    def get_verbosity(self) -> str:
        return self._verbosity_values[self.verbosity_combo.GetSelection()]

    def get_volume_normalisation(self) -> bool:
        return bool(self.volume_normalisation.GetValue())

    def get_initial_volume(self) -> int:
        return int(self.initial_volume.GetValue())

    def get_download_parallel(self) -> int:
        return int(self.download_parallel.GetValue())

    def get_download_template(self) -> str:
        return self.download_template_input.GetValue().strip()

    def save(self) -> bool:
        """Speichert die eingegebenen Einstellungen."""
        credentials_ok = True
        if self.get_client_id() and self.get_client_secret():
            credentials_ok = cfg.save_credentials(self.get_client_id(), self.get_client_secret())
        return (
            credentials_ok
            and cfg.save_download_dir(self.get_download_dir())
            and cfg.save_player_settings(
                self.get_playback_quality(),
                self.get_download_quality(),
                self.get_download_template(),
                self.get_download_method(),
                self.get_download_format(),
                self.get_autoplay(),
                self.get_verbosity(),
                self.get_volume_normalisation(),
                self.get_initial_volume(),
                self.get_download_parallel(),
            )
        )
