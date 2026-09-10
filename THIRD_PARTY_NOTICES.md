# Third-party components

SpotiFlix itself is licensed under the **GNU General Public License v3.0 or
later** (see [LICENSE](LICENSE)). The Windows packages on the
[Releases page](https://github.com/FelixSteindorff/SpotiFlix/releases) bundle the
components below. Their licenses are listed here as required; each component
stays under its own license.

## Why GPL-3.0-or-later

The choice is not arbitrary, it follows from what is bundled:

* **mutagen** is GPL-2.0-**or-later**. Distributing it inside one binary makes
  the whole package a GPL work.
* **requests** and **librespot-python** are Apache-2.0, which is incompatible
  with GPL-2 but compatible with GPL-3.

GPL-2-only would therefore break against the Apache-2.0 parts, and a permissive
license such as MIT would break against mutagen. GPL-3.0-or-later is the one
combination that fits.

## Bundled in the Windows packages

| Component | License | Project |
|---|---|---|
| librespot (`librespot.exe`) | MIT | https://github.com/librespot-org/librespot |
| librespot-python | Apache-2.0 | https://github.com/kokarare1212/librespot-python |
| mutagen | GPL-2.0-or-later | https://github.com/quodlibet/mutagen |
| wxPython / wxWidgets | wxWindows Library Licence (LGPL-2.1 with exception) | https://www.wxpython.org/ |
| spotipy | MIT | https://github.com/spotipy-dev/spotipy |
| requests | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | MIT | https://github.com/urllib3/urllib3 |
| charset-normalizer | MIT | https://github.com/jawah/charset_normalizer |
| idna | BSD-3-Clause | https://github.com/kjd/idna |
| certifi | MPL-2.0 | https://github.com/certifi/python-certifi |
| keyring | MIT | https://github.com/jaraco/keyring |
| protobuf (Python runtime) | BSD-3-Clause | https://github.com/protocolbuffers/protobuf |
| pycryptodomex | BSD-2-Clause and public domain | https://github.com/Legrandin/pycryptodome |
| python-zeroconf | LGPL-2.1-or-later | https://github.com/python-zeroconf/python-zeroconf |
| defusedxml | PSF-2.0 | https://github.com/tiran/defusedxml |
| pywin32 | PSF-2.0 | https://github.com/mhammond/pywin32 |
| CPython runtime | PSF-2.0 | https://www.python.org/ |
| NVDA Controller Client (`nvdaControllerClient32/64.dll`) | LGPL-2.1 | https://github.com/nvaccess/nvda |

## Not bundled

These are optional external programs that SpotiFlix locates through `PATH`; they
are never shipped with it and keep their own licenses:

* [spotdl](https://github.com/spotDL/spotify-downloader) – MIT
* [ffmpeg](https://ffmpeg.org/) – LGPL-2.1-or-later or GPL-2.0-or-later,
  depending on the build

## Source code

The corresponding source of SpotiFlix is this repository, tagged per release.
The bundled components are unmodified upstream releases and can be obtained from
the project pages above; the exact versions of the Python packages are the ones
resolved from [requirements.txt](requirements.txt) at build time.

For the LGPL parts (wxWidgets, python-zeroconf, NVDA Controller Client) that
means: they are used as unmodified libraries, and their sources are available
from the projects linked above.

## Spotify

SpotiFlix is an independent third-party client. It is not affiliated with,
endorsed by or supported by Spotify. "Spotify" is a trademark of Spotify AB;
using the name here refers to the service the application talks to.
