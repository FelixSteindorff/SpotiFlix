# SpotiFlix

Barrierefreie wxPython-Anwendung mit Spotify Web API Integration.

## Voraussetzungen

- Python 3.10+
- Spotify Developer Account
- `librespot` im Projektordner oder im `PATH` für lokale Wiedergabe in der App
- `ffmpeg` im `PATH`, falls librespot-Downloads als MP3 oder M4A gespeichert werden sollen
- NVDA für gesprochene Ansagen (z. B. der Lautstärke). Der benötigte NVDA Controller Client (`nvdaControllerClient32.dll`/`nvdaControllerClient64.dll`) liegt der App bei und wird automatisch genutzt, solange NVDA läuft. Läuft NVDA nicht, weicht die App automatisch auf die Windows-Sprachausgabe (SAPI5) aus.

## Setup

1. **Spotify App erstellen:**
   - Gehen Sie zu https://developer.spotify.com/dashboard
   - Klicken Sie auf "Create app"
   - Fügen Sie `http://127.0.0.1:8080/callback` als Redirect URI hinzu

2. **Credentials eintragen:**
   - Öffnen Sie `Bearbeiten > Einstellungen`
   - Tragen Sie Client-ID, Client-Secret und optional den Download-Ordner ein

3. **Installieren:**
```bash
pip install -r requirements.txt
```

4. **Starten:**
```bash
python main.py
```

## Barrierefreiheits-Features

- Zugängliche Namen für alle Listen und Eingabefelder (unter Windows über MSAA/UIA –
  NVDA meldet damit „Alben" statt nur „Liste"); der Name folgt der geöffneten Ansicht
- Vollständige Keyboard-Navigation; zurück mit `Backspace`, `Alt+Pfeil links` oder `Esc`
- Kontextmenüs öffnen bei Tastaturaufruf am markierten Eintrag, nicht an der Mausposition
- Tooltips für alle Buttons
- Sprach- und Brailleansagen für Status, Ladevorgänge (inkl. „keine Einträge"),
  Lautstärke (Prozent), Warteschlangen- und Playlist-Aktionen (NVDA, sonst SAPI5)
- Ansagen unterbrechen einander nicht – nur die Lautstärke bricht die laufende Ansage ab
- Ausführlichkeit der Ansagen wählbar (`Bearbeiten > Einstellungen`): „Ausführlich"
  sagt auch Zwischenmeldungen wie „Lade Alben …" an, „Kurz" nur Ergebnisse und Fehler
- Der Fokus springt nach einem Ladevorgang nur dann in die Liste, wenn man
  inzwischen nicht in einen anderen Tab oder ein anderes Feld gewechselt ist
- Systemweite Medientasten (Wiedergabe/Pause, Vor, Zurück, Stopp) steuern die App
  auch dann, wenn sie im Hintergrund läuft
- `Strg+F` filtert jede Liste; die Trefferzahl wird angesagt
- `F1` listet **alle** Tastenkürzel auf – die Übersicht entsteht zur Laufzeit aus
  Menü, Panels und Medientasten und ist damit immer aktuell
- Mehrfachauswahl in allen Listen (`Umschalt+Pfeiltasten`, `Strg+A`); Aktionen
  wirken auf die gesamte Auswahl und nennen die Anzahl in der Ansage
- Sortierung in jeder Liste nach Name, Künstler, Album, Dauer oder Datum
- Der laufende Titel erscheint im Fenstertitel

## Verwendung

1. **Autorisieren:** Hilfe > Autorisieren
2. **Einstellungen:** `Ctrl+,` öffnet jederzeit den Einstellungsdialog
3. **Mediathek:** `Ctrl+1` - Playlists, Künstler, Alben und Titel vollständig laden und mit Pfeiltasten, `Enter` und `Backspace` durchsuchen. `Strg+F` filtert die aktuelle Liste, `Esc` hebt den Filter wieder auf.
4. **Suche:** `Ctrl+2` - Suchfeld plus Ergebnisart wie Top-Ergebnisse, Titel, Playlists, Alben, Künstler und Podcasts. Ein Podcast öffnet mit `Enter` seine Episodenliste (die Web API kann eine Show nicht direkt abspielen), einzelne Episoden lassen sich abspielen und herunterladen – angefangene Folgen laufen dort weiter, wo Sie aufgehört haben. Das Suchfeld merkt sich frühere Suchbegriffe (Pfeiltasten), `Mehr laden` holt die nächsten Treffer.
5. **Warteschlange:** `Ctrl+3` - zeigt die Warteschlange und macht sie bearbeitbar (siehe unten).
6. **Entdecken:** `Ctrl+4` - Neue Alben, Top-Künstler, Top-Titel, Neues von Top-Künstlern und **Zuletzt gehört** öffnen
7. **Wiedergabe:** `Enter` spielt den gewählten Titel; bei Album, Künstler oder Playlist öffnet `Enter` den Inhalt. `Ctrl+P` pausiert/setzt fort, `Ctrl+N` springt vor, `Ctrl+B` zurück, `Ctrl++`/`Ctrl+-` ändern die Lautstärke. `Ctrl+Shift+Rechts`/`Ctrl+Shift+Links` spulen 10 Sekunden vor/zurück, `Ctrl+Shift+S` schaltet die Zufallswiedergabe um, `Ctrl+Shift+R` die Wiederholung (aus → alle → Titel). `Ctrl+J` sagt an, **was gerade läuft** (Titel, Künstler, Album, abgelaufene/verbleibende Zeit, Pausiert-Status, Zufall, Wiederholung und Restzeit des Einschlaf-Timers). Der laufende Titel steht im Fenstertitel. Die Medientasten der Tastatur wirken auch, wenn das Fenster im Hintergrund ist.
8. **Navigation per Kontextmenü:** Rechtsklick oder Kontextmenütaste bietet je nach Element `Album öffnen`, `Künstler öffnen`, `Playlist öffnen` sowie bei Titeln `Zum Künstler` und `Zum Album`. Die Künstleransicht öffnet eine Übersicht mit eigenen Unterlisten: **Beliebte Titel**, **Alben**, **Singles & EPs** und passende **Playlists** – jeweils mit `Enter` zum Öffnen und `Backspace` zum Zurückgehen.
9. **Kontextmenü (Hinzufügen):** `Zur Warteschlange hinzufügen` (`Ctrl+Q`) und `Zu Playlist hinzufügen …` (`Ctrl+Shift+P`, mit Auswahl-Dialog samt Tippsuche) wirken auf Titel **und** ganze Alben/Playlists (alle enthaltenen Titel). Spotify nimmt für die Warteschlange nur einen Titel pro Anfrage entgegen; die Ansage nennt darum die tatsächlich eingereihte Anzahl und meldet einen Abbruch. Die Kurztasten wirken auf den markierten Eintrag des aktiven Tabs. Das Hinzufügen zu Playlists benötigt erweiterte Berechtigungen – führen Sie ggf. einmalig `Hilfe > Autorisieren` erneut aus.
10. **Mediathek pflegen:** `Ctrl+S` (oder das Kontextmenü) speichert den markierten Titel, das Album, die Episode oder den Podcast in Ihrer Mediathek – und entfernt ihn beim nächsten Druck wieder. Bei Künstlern folgen/entfolgen Sie damit, bei Playlists speichern Sie sie. Der aktuelle Zustand wird vorher abgefragt, die Ansage nennt das Ergebnis.
11. **Playlist anlegen:** Im Dialog `Zu Playlist hinzufügen …` legt `Neue Playlist …` eine neue private Playlist an und wählt sie sofort aus.
12. **Wiedergabegerät:** `Ctrl+Shift+D` (`Extras > Wiedergabegerät …`) wählt, worauf abgespielt wird – der lokale SpotiFlix-Player oder ein anderes Spotify-Connect-Gerät (Handy, Desktop-App, Lautsprecher). Die Wahl bleibt über den Namen gespeichert.
13. **Einschlaf-Timer:** `Ctrl+Shift+E` pausiert die Wiedergabe nach 15 bis 90 Minuten; `Ctrl+J` sagt die Restzeit mit an.
14. **Downloads:** Rechtsklick oder Kontextmenütaste auf Titel, Episode, Album, Künstler oder Playlist. Zielordner, Download-Methode und -Format werden über `Bearbeiten > Einstellungen` festgelegt. Aufträge laufen über eine **Warteschlange**: Es arbeiten nur so viele gleichzeitig, wie eingestellt sind (Vorgabe 2), der Rest wartet. `Ctrl+Shift+L` öffnet die Warteschlange – dort lassen sich Aufträge abbrechen, fehlgeschlagene wiederholen und erledigte ausblenden. `Extras > Download-Ordner öffnen` zeigt die Dateien im Explorer.
15. **Status:** Normale Aktionen wie Laden, Wiedergabe und abgeschlossene Downloads erscheinen in der Statusleiste; laufende Downloads im rechten Statusfeld.
16. **Playlists bearbeiten:** In einer geöffneten Playlist entfernt `Entf` die markierten Titel, `Strg+Pfeil hoch/runter` verschiebt einen Titel, und `F2` öffnet Name **und Beschreibung** zum Bearbeiten. Es wird positionsgenau gelöscht – steht ein Titel mehrfach in der Playlist, verschwindet nur der markierte. Die Ansicht lädt danach automatisch neu (`F5` geht auch von Hand).
17. **Schnellzugriffe:** `Als Schnellzugriff merken` im Kontextmenü legt Album, Künstler, Playlist oder Podcast auf einen der neun Plätze; `Strg+Umschalt+1` … `9` öffnen sie direkt. Verwalten über `Navigation > Schnellzugriffe verwalten …`.
18. **Export/Import:** `Strg+E` speichert die angezeigte Liste als CSV (für Tabellen) oder M3U8 – beides mit Spotify-URIs. `Strg+Umschalt+I` liest URIs oder `open.spotify.com`-Links aus einer beliebigen Textdatei und legt daraus eine neue Playlist an.
19. **Protokoll:** `Strg+Umschalt+G` zeigt gesammelte Fehler und Ereignisse mit Zeitstempel; kopierbar in die Zwischenablage. Die Datei liegt unter `~/.spotiflix.log` und wird rotiert.

## Einstellungen

`Bearbeiten > Einstellungen` (`Ctrl+,`) enthält neben Credentials und Download-Ordner:

- **Wiedergabequalität** und **Startlautstärke** des lokalen Players
- **Lautstärke normalisieren** – gleicht Pegelunterschiede zwischen Alben aus
- **Ansagen** – „Ausführlich" (mit Zwischenmeldungen) oder „Kurz" (nur Ergebnisse und Fehler)
- **Autoplay**, **Download-Methode**, **-Format**, **-Qualität** und **-Ordnerstruktur**
- **Gleichzeitige Downloads** (1–4)

Änderungen an Qualität, Startlautstärke oder Normalisierung stoppen den lokalen Player – librespot liest diese Werte nur beim Start.

## Warteschlange

Der Tab **Warteschlange** (`Ctrl+3`) hat zwei Ansichten (Umschalten über die Auswahl „Ansicht"):

**Meine Liste** sammelt alles, was über `Zur Warteschlange hinzufügen` (`Ctrl+Q`) eingereiht wurde, und lässt sich bearbeiten:

- `Enter` – ab dem markierten Titel abspielen (Spotify spielt die Reihenfolge der Liste der Reihe nach ab)
- `Strg+Pfeil hoch` / `Strg+Pfeil runter` – markierten Titel nach oben/unten verschieben
- `Entf` – markierten Titel entfernen

**Spotify-Warteschlange** zeigt, was Spotify selbst als Nächstes spielt – inklusive dem, was Autoplay oder ein anderes Gerät eingereiht hat; der laufende Titel steht mit „Läuft gerade" an erster Stelle. Diese Ansicht ist nur lesend (die Web API kann Einträge weder entfernen noch umsortieren); `F5` bzw. `Aktualisieren` lädt sie neu, `Enter` spielt den gewählten Titel direkt ab.

Die dafür vorgesehenen Schaltflächen unter der Liste machen dieselben Aktionen per Maus verfügbar. Hinweis: Ein neu Hinzugefügter Titel wird sofort in den laufenden Spotify-Player eingereiht; eine geänderte Reihenfolge wird angewendet, sobald die Warteschlange mit `Enter` (neu) gestartet wird.

## Autoplay

Unter `Bearbeiten > Einstellungen` steuert **Autoplay**, was nach einem einzelnen Titel passiert:

- **Aus (nur der gewählte Titel):** Es wird ausschließlich der gewählte Titel gespielt.
- **In Playlist/Album fortsetzen** (Standard): Wird ein Titel aus einer Playlist oder einem Album gestartet, läuft die Liste ab diesem Titel weiter. **Vor/Zurück** (`Ctrl+N`/`Ctrl+B`) navigieren innerhalb des Albums bzw. der Playlist.
- **Immer weiterspielen:** Wie oben; zusätzlich laufen bei Titeln ohne Album-/Playlist-Bezug (z. B. aus der Suche oder den gespeicherten Titeln) die folgenden Einträge der angezeigten Liste automatisch weiter.

Technischer Hinweis: Der lokale `librespot`-Player löst ein reines Spotify-`context_uri` (Album/Playlist) nicht zuverlässig auf und würde sonst nach dem Einzeltitel in Spotifys eigenes Autoplay fallen. SpotiFlix übergibt deshalb bei Album-/Playlist-Wiedergabe die **explizite Titelliste** mit Positions-Offset, damit Vor/Zurück verlässlich innerhalb der Liste bleiben (bei sehr langen Listen ein Fenster von bis zu 100 Titeln um die aktuelle Position).

## Lokale Wiedergabe

Die App spielt lokal über `librespot`. Beim Abspielen startet die App den lokalen Player `SpotiFlix` automatisch und sendet die Wiedergabe ausschließlich an dieses lokale Gerät. Es gibt keinen Fallback auf andere Spotify-Geräte.

Für `librespot` muss die Spotify-Autorisierung den Scope `streaming` enthalten. Wenn Sie die App bereits vor dieser Änderung autorisiert hatten, führen Sie `Hilfe > Autorisieren` erneut aus.

Die Wiedergabequalität wird unter `Bearbeiten > Einstellungen` gesetzt. Wenn der lokale Player bereits läuft und die Qualität geändert wird, stoppt die App den lokalen Player. Beim nächsten Abspielen startet er mit der neuen Qualität.

Beim Beenden der App wird der lokale Player automatisch gestoppt.

## Download-Methoden

Unter `Bearbeiten > Einstellungen` lässt sich die Download-Methode wählen:

- **YouTube-Quelle (spotdl):** Standard. Lädt das Audio passend zu den Spotify-Metadaten über YouTube als MP3. Benötigt `spotdl` (`pip install spotdl`).
- **Echter Spotify-Stream (librespot):** Lädt den nativen OGG-Vorbis-Stream direkt von Spotify. Benötigt `librespot` (`pip install librespot`) und für 320 kbit/s ein **Spotify-Premium-Konto** (Free-Konten erhalten max. 160 kbit/s). Beim ersten Download öffnet sich ein separater Browser-Login von librespot; die Anmeldedaten werden in `~/.spotiflix-librespot-creds.json` gespeichert. Die librespot-Qualitätsstufe folgt der eingestellten **Wiedergabequalität**. Hinweis: Dieser Weg umgeht Spotifys DRM und kann gegen die Spotify-Nutzungsbedingungen verstoßen.

## Download-Format (librespot)

Unter `Bearbeiten > Einstellungen` lässt sich das Dateiformat für librespot-Downloads wählen:

- **OGG Vorbis (Original):** Der unveränderte Spotify-Stream, ohne Umwandlung.
- **MP3** bzw. **M4A (AAC):** Der Stream wird per `ffmpeg` in das gewählte Format umgewandelt. Die Zielbitrate folgt der eingestellten **Downloadqualität**. Dafür muss `ffmpeg` im `PATH` liegen.

Das Format gilt nur für die librespot-Methode; spotdl liefert weiterhin MP3.

### Metadaten / Tags

librespot-Downloads werden in allen drei Formaten (OGG/MP3/M4A) einheitlich und reichhaltig getaggt – die Daten stammen aus der Spotify Web API:

- Titel, Künstler, **Album-Künstler**, Album
- **Cover-Bild** (eingebettet)
- **Veröffentlichungsdatum** (vollständig, z. B. `1998-05-04`) plus Jahr
- **Titelnummer/Gesamtanzahl** und **CD-Nummer/Gesamtanzahl** (Disc-Gesamtzahl bei Album-Downloads)
- **Genre** (vom Künstler), **ISRC** und **Label** (Label bei Album-/Einzeltitel-Downloads)

Für das Cover-Bild wird `requests` genutzt (bereits in den Abhängigkeiten); das Tagging übernimmt `mutagen`. Beides ist optional – fehlt eine Angabe, wird der Tag einfach weggelassen, der Download bricht nicht ab.

## Download-Struktur

Unter `Bearbeiten > Einstellungen` können Downloadqualität und Ordnerstruktur gesetzt werden. Die Ordnerstruktur ist relativ zum Download-Ordner.

Beispiel:

```text
%artist%/%album%/%num,2% - %title%
```

Das ergibt zum Beispiel:

```text
Download-Ordner/Künstler/Album/01 - Titel
```

Verfügbare Platzhalter:

- `%artist%` - Hauptkünstler
- `%artists%` - alle Künstler
- `%album%` - Albumname
- `%title%` - Titelname
- `%num%` - Tracknummer
- `%num,2%` - Tracknummer, zweistellig, wenn spotdl diese Angabe liefert
- `%disc%` - Disc-Nummer
- `%year%` - Veröffentlichungsjahr

`/` oder `\` erzeugen Unterordner.
