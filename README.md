# SpotiFlix

**Accessible, keyboard-driven Spotify player for Windows.**

I started this project because I wanted a Spotify client that is fully usable with a keyboard and a screen reader. SpotiFlix is built around native wxPython controls, talks to the Spotify Web API for browsing and control, and plays audio through [librespot](https://github.com/librespot-org/librespot), which registers itself as a Spotify Connect device.

The Windows build includes the playback engine, so there is nothing else to install for local playback.

> SpotiFlix is an independent third-party client. It is not affiliated with, endorsed by or supported by Spotify.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

## Features

- Library browsing: playlists, followed artists, saved albums and saved tracks
- Discover: new releases, your top artists, your top tracks, new releases from your top artists, recently played
- Search for tracks, playlists, albums, artists and podcasts, with a search history and "load more"
- Artist pages with popular tracks, albums, singles & EPs and matching playlists
- Podcasts open as an episode list; episodes remember where you stopped and resume there
- Playback control: play/pause, next, previous, seek, shuffle, repeat, volume
- Media keys that work while SpotiFlix is in the background
- Choose the playback device: the local player or any other Spotify Connect device
- Queue with two views: your own editable list and Spotify's actual upcoming tracks
- Save tracks, albums, episodes and podcasts to your library; follow and unfollow artists
- Create playlists, add to them, remove tracks, reorder them and edit name and description
- Multi-selection in every list, so actions apply to everything you marked
- Sorting and filtering in every list
- Nine quick jumps to albums, artists, playlists or podcasts
- Downloads through spotdl or as the native Spotify stream, with a queue you can cancel and retry
- Export any list as CSV or M3U8, and import a playlist from a file of Spotify links
- Sleep timer
- Spoken and braille feedback for status, results, volume, queue and library actions
- Shortcut overview that builds itself from the running application
- German and English interface

Most item actions are also available from the context menu, which opens at the selected row when you use the keyboard.

## Accessibility

SpotiFlix is built for people who use a keyboard and a screen reader.

Every list and input field has an accessible name, and the name follows the current view: entering a list announces "Albums" or "Podcast: …" instead of just "list". Lists work with the usual arrow-key navigation, context menus open with the Applications key or `Shift+F10`, and every important action has a menu entry and a shortcut.

Status messages, loading progress and results are spoken **and** sent to a braille display through the NVDA controller client. Announcements do not interrupt each other; only rapidly repeated values such as the volume cut off the running announcement, so NVDA's own focus announcements stay intact. How much is announced can be changed between "verbose" and "short".

Long operations run in a background thread. When one finishes, the focus only moves into the list if you have not switched to another tab or field in the meantime.

If NVDA is not reachable, SpotiFlix falls back to the Windows speech engine (SAPI5). Screen-reader output goes through the [NVDA Controller Client](https://github.com/nvaccess/nvda); an installed NVDA is preferred over the copy shipped with the project.

The interface is available in **German and English** and follows the system language by default. If something does not work properly with a screen reader or keyboard-only use, please open an issue and mention what your screen reader announced, or what it did not announce.

## Requirements

- Windows 10 or newer
- A **Spotify Premium** account – the Web API playback endpoints and Spotify Connect are Premium-only
- Your own Spotify API application (client ID and client secret, see below)
- Python 3.10 or newer, only for running from source (developed and tested with 3.13)

Optional, for downloads:

- [spotdl](https://github.com/spotDL/spotify-downloader) if you want the YouTube-based download method
- [ffmpeg](https://ffmpeg.org/) if you want librespot downloads as MP3 or M4A instead of OGG

## Installation

### Windows

There are two downloads on the [Releases page](https://github.com/FelixSteindorff/SpotiFlix/releases).

**Installer**

```text
SpotiFlix-<version>-Setup.exe
```

The installer does not need administrator rights. It installs into your user profile, adds SpotiFlix to the Start menu and creates an uninstall entry.

**Portable**

```text
SpotiFlix-<version>-portable-win64.zip
```

Unpack it anywhere and run `SpotiFlix.exe`. Keep the whole `SpotiFlix` folder together – the dependencies live next to the executable in `_internal`.

Both downloads include librespot for local playback, the NVDA controller DLLs and the translation catalogs. Your settings, tokens and downloads always stay in your user profile (see [Data locations](#data-locations)), so a portable copy on another computer will ask you to authorize again.

### Spotify API credentials

SpotiFlix uses your own Spotify application, so no shared client secret has to be trusted:

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create an app.
2. Add this redirect URI exactly:

   ```text
   http://127.0.0.1:8080/callback
   ```

3. Start SpotiFlix and enter client ID and secret under `Edit > Settings`. They are stored in the Windows Credential Manager, not in a file.
4. Run `Help > Authorize`. The browser opens, and SpotiFlix answers the callback with its own local server.

SpotiFlix requests 14 scopes. If the set of scopes changes with an update, the stored token is no longer sufficient, and the application says so on startup and asks you to authorize again.

### Running from source

```bash
git clone https://github.com/FelixSteindorff/SpotiFlix.git
cd SpotiFlix

py -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
py main.py
```

Use the same interpreter for installing and running. wxPython is installed per interpreter, so a second Python on the machine will not find it.

## Local playback

Playback always happens on a Spotify Connect device. By default that is the local player: SpotiFlix starts the bundled `librespot.exe`, which appears in your account as a device named **SpotiFlix**.

The local player needs its own one-time login, which opens in the browser. That login is shared with the download function, so you only do it once.

It cannot use the Web API token, and that is worth knowing if you ever look at the log: with a token from a third-party application registration, librespot signs in to the account but Spotify refuses to register the device.

```text
Authenticated as '<user>' !
ERROR librespot] could not initialize spirc:
  Invalid state { Login request was denied: INVALID_CREDENTIALS }
```

SpotiFlix therefore hands librespot the stored credentials from librespot's own OAuth login. If Spotify rejects them, `Extras > Sign the local player in again` discards them and starts a fresh login.

Registering the device takes a moment: measured between 4 and 16 seconds after the process starts. SpotiFlix waits up to 35 seconds for it and announces the result.

`Ctrl+Shift+D` opens the device selector, where you can send playback to your phone, the desktop app or a speaker instead. The choice is remembered by device name, so it survives a restart and reconnects when the device is online again.

## Keyboard shortcuts

`F1` opens the shortcut overview. The list is not maintained by hand: it is collected at runtime from the menu bar, the panels and the media keys that were actually registered, so it is always current.

The German interface labels these keys `Strg`, `Entf` and `Umschalt`.

| Function | Shortcut |
|---|---|
| Library / Search / Queue / Discover | `Ctrl+1` … `Ctrl+4` |
| Quick jumps 1–9 | `Ctrl+Shift+1` … `Ctrl+Shift+9` |
| Play / Pause | `Ctrl+P` |
| Next / previous track | `Ctrl+N` / `Ctrl+B` |
| Seek forward / back (10 s) | `Ctrl+Shift+Right` / `Ctrl+Shift+Left` |
| Volume up / down | `Ctrl++` / `Ctrl+-` |
| Toggle shuffle | `Ctrl+Shift+S` |
| Cycle repeat (off → all → track) | `Ctrl+Shift+R` |
| What is playing? | `Ctrl+J` |
| Add to queue | `Ctrl+Q` |
| Add to playlist | `Ctrl+Shift+P` |
| Save to / remove from library | `Ctrl+S` |
| Sleep timer | `Ctrl+Shift+E` |
| Playback device | `Ctrl+Shift+D` |
| Downloads | `Ctrl+Shift+L` |
| Export the current list | `Ctrl+E` |
| Import a playlist from a file | `Ctrl+Shift+I` |
| Log | `Ctrl+Shift+G` |
| Settings | `Ctrl+,` |
| Shortcut overview | `F1` |

Inside lists:

| Function | Shortcut |
|---|---|
| Open or play | `Enter` |
| Back one level | `Backspace`, `Alt+Left` or `Esc` |
| Filter the list | `Ctrl+F` |
| Clear the filter | `Esc` |
| Reload the view | `F5` |
| Select all | `Ctrl+A` |
| Extend the selection | `Shift+Arrow keys` |
| Context menu | Applications key or `Shift+F10` |
| Remove marked tracks from the open playlist | `Del` |
| Move a track inside the open playlist | `Ctrl+Up` / `Ctrl+Down` |
| Rename a playlist and edit its description | `F2` |
| Earlier search terms (in the search field) | `Up` / `Down` |

The media keys on a keyboard or headset work while SpotiFlix is in the background: play/pause, next, previous and stop. If another application has already claimed a key, SpotiFlix leaves it alone and says nothing about it.

## Queue

The queue tab has two views:

**My list** collects everything added through `Add to queue` (`Ctrl+Q`) and is editable: reorder with `Ctrl+Up` / `Ctrl+Down`, remove with `Del`, clear it completely. `Enter` starts playback from the marked track, and Spotify plays the list in exactly that order.

**Spotify queue** shows what Spotify itself will play next, including whatever autoplay or another device queued, with the current track first. This view is read-only, because the Web API can neither remove nor reorder entries there. `F5` reloads it, `Enter` plays the selected track.

Adding to the queue sends one request per track, because that is all the API offers. The announcement therefore reports the number that actually went through and says so if it stopped early.

## Playlists

Open a playlist and you can edit it in place:

| Function | Shortcut |
|---|---|
| Rename and edit the description | `F2` |
| Remove the marked tracks | `Del` |
| Move a track up or down | `Ctrl+Up` / `Ctrl+Down` |

Tracks are removed by position, so if the same track appears twice in a playlist, only the marked one disappears. Removing asks first, and the view reloads afterwards. This works in the library, in Discover and in search results alike, and only for playlists you own or that are collaborative.

`New playlist …` in the "add to playlist" dialog (`Ctrl+Shift+P`) creates a new private playlist and selects it right away.

## Downloads

Two methods, selectable in the settings:

| Method | Source | Result |
|---|---|---|
| spotdl | audio from YouTube | MP3 |
| librespot | the native Spotify stream | OGG, optionally MP3 or M4A through ffmpeg |

The librespot method tags the files with mutagen, including cover art, and uses the login described under [Local playback](#local-playback).

Downloads run through a queue: only as many as configured run at once (1–4, two by default), the rest wait. `Ctrl+Shift+L` opens it, where jobs can be cancelled, failed ones retried and finished ones cleared. Tracks, episodes, albums, artists and playlists can all be downloaded, and a multi-selection queues every marked item.

The folder structure is configurable with placeholders:

```text
%artist%/%album%/%num,2% - %title%
```

Available placeholders are `%artist%`, `%artists%`, `%album%`, `%title%`, `%num%`, `%num,2%`, `%disc%` and `%year%`. Paths that would exceed the Windows limit of 260 characters are shortened per segment instead of failing when the file is written.

## Data locations

| Data | Location |
|---|---|
| Client ID and secret | Windows Credential Manager (service `SpotiFlix`) |
| Settings | `%USERPROFILE%\.spotiflix-settings.json` |
| Spotify token | `%USERPROFILE%\.spotify-token.json` |
| Application log | `%USERPROFILE%\.spotiflix.log` |
| librespot login | `%USERPROFILE%\.spotiflix-librespot-creds.json` |
| librespot cache | `%USERPROFILE%\.spotiflix-librespot-cache\` |
| librespot log | `%USERPROFILE%\.spotiflix-librespot.log` |
| Downloads | `%USERPROFILE%\Music\SpotiFlix` by default |

Both logs are rotated instead of growing without limit. `Ctrl+Shift+G` shows the collected errors and events with timestamps and copies them to the clipboard for a bug report; announcements only carry the first line of an error and point to the log for the rest.

## Languages

The interface ships in German and English. **German is the source language**: the
texts in the code are the msgid keys, and English is a gettext catalog under
`locale/en/LC_MESSAGES/`. German therefore can never be missing or out of date.

The language follows the system by default and can be set explicitly under
`Edit > Settings`. A change takes effect after a restart, because labels are
built when the windows are created.

Windows usually has no GNU gettext, so the project brings its own tool:

```powershell
py tools/i18n_tool.py extract   # collect texts from the source into locale/spotiflix.pot
py tools/i18n_tool.py update    # merge new texts into locale/en/LC_MESSAGES/spotiflix.po
py tools/i18n_tool.py compile   # .po to .mo, which is what the application reads
py tools/i18n_tool.py check     # report missing translations, broken shortcuts, bad placeholders
```

`check` is the useful one: it verifies that every menu accelerator behind a tab
character survived translation and that no placeholder such as `{count}` went
missing. Run `compile` after changing a catalog — the application reads the
`.mo`, not the `.po`.

Another language needs a folder `locale/<code>/LC_MESSAGES/`, an entry in
`i18n.LANGUAGES` and `CATALOG_LANGUAGES` in the tool.

## Building the Windows version

For a plain application build:

```powershell
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --clean SpotiFlix.spec
```

The result is a one-dir build in `dist\SpotiFlix\`. Pass the whole folder on when sharing it, not just the executable.

For a full release – portable archive and installer – use:

```powershell
py build_release.py
```

That compiles the translation catalogs, runs PyInstaller, packs `dist\SpotiFlix` into `SpotiFlix-<version>-portable-win64.zip`, builds the installer with [Inno Setup](https://jrsoftware.org/isinfo.php) and prints the SHA-256 of both files. Useful variants:

```powershell
py build_release.py --skip-installer   # only the portable archive
py build_release.py --skip-build       # only repackage what is in dist
```

Inno Setup is optional; without it you get the portable archive and a note why the installer is missing (`winget install JRSoftware.InnoSetup`). The version number lives in `version.py` and feeds the About dialog, the file names and the installer at once.

Always build from `SpotiFlix.spec`. It produces a windowless build and bundles `librespot.exe`, the NVDA controller DLLs and the `locale` folder, which `nvda.py`, `librespot_manager.py` and `i18n.py` look for in exactly that place. Run `py tools/i18n_tool.py compile` before building if you changed a catalog. No SpotiFlix instance may be running, or the executable is locked.

spotdl and ffmpeg are deliberately not bundled; they are external programs and are located through `PATH`.

## Project structure

```text
main.py                 entry point
config.py               settings and credentials
spotify_client.py       Web API, token handling, playback control
librespot_manager.py    the local player as a Connect device
librespot_download.py   downloads as the native Spotify stream
download_manager.py     download methods and the queue
nvda.py                 speech and braille output
applog.py               log and short error messages
i18n.py                 translations (German source, English catalog)
version.py              the version number, used everywhere

ui/
  main_window.py        menu, tabs, playback control, timers
  browse_panel.py       shared base for the browsing panels
  library_panel.py      library
  discover_panel.py     discover
  search_panel.py       search
  queue_panel.py        queue
  browse_common.py      row builders and loaders
  panel_helpers.py      announcements, focus, sorting, selection
  context_actions.py    context menu and its actions
  playlist_edit.py      editing playlists
  list_io.py            export and import
  shortcuts.py          shortcut overview
  downloads_dialog.py   download queue
  log_dialog.py         log
  config_dialog.py      settings

locale/
  spotiflix.pot         extracted texts
  en/LC_MESSAGES/       English catalog (.po and compiled .mo)

tools/i18n_tool.py      extract, merge, compile and check catalogs
packaging/spotiflix.iss Inno Setup installer
build_release.py        portable archive and installer
SpotiFlix.spec          Windows build
```

## Known limitations

- **Spotify Premium is required.** The Web API playback endpoints and Spotify Connect do not work with a free account.
- Changing the interface language needs a restart.
- Spotify's own queue can only be read. Removing and reordering only works in the app's own list.
- Playback starts at most 100 tracks in one go; that is the API limit. The announcement says so instead of silently truncating.
- Recommendations, related artists, featured playlists and browse categories are not used: Spotify closed those endpoints for applications registered after November 2024. The artist view therefore finds matching playlists through a normal search.
- librespot ships generated protobuf files from an old protoc version. SpotiFlix sets `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` before loading it, which is slower but keeps it working with protobuf 4 and newer.
- The bundled NVDA controller DLLs are old. An installed NVDA is preferred, so this only matters on machines without NVDA.
- There is no automated test suite in the repository yet; changes are verified by hand and against the live API.
- Only Windows is tested. The application is close to platform-independent, but the local player, the media keys and the speech output are built for Windows.

If you find another limitation or bug, please open an issue.

## AI-assisted development

Most of the code in SpotiFlix has been written with the help of AI coding agents. I use them for implementation, refactoring and diagnosis, while I decide what the application should do, review the changes and test the result in actual use, especially with NVDA and keyboard-only workflows.

This note is here simply to be transparent about how the project is developed.

## Contributing

Bug reports and pull requests are welcome.

Accessibility reports are especially useful. If possible, mention your screen reader, its version and what SpotiFlix announced or failed to announce. For playback and download problems, `Ctrl+Shift+G` copies the log, and `%USERPROFILE%\.spotiflix-librespot.log` holds what the local player itself reported.

## License

SpotiFlix is released under the **GNU General Public License, version 3 or
later**. See [LICENSE](LICENSE) for the full text.

That choice follows from what the packages bundle rather than from taste:
**mutagen** is GPL-2.0-or-later, which makes the whole package a GPL work, while
**requests** and **librespot-python** are Apache-2.0, which is incompatible with
GPL-2 but compatible with GPL-3. GPL-2-only would break against the Apache
parts, and a permissive license such as MIT would break against mutagen — so
GPL-3.0-or-later is the one combination that fits.

Every bundled component and its license is listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Both files are shipped inside
the portable archive and the installer.
