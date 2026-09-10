# SpotiFlix – ein barrierefreier Spotify-Player für Windows.
# Copyright (C) 2026 Felix Steindorff
#
# Dieses Programm ist freie Software: Sie können es unter den Bedingungen
# der GNU General Public License, Version 3 oder (nach Ihrer Wahl) einer
# neueren Version, weitergeben und/oder verändern. Es wird ohne jede
# Gewährleistung bereitgestellt; siehe LICENSE für den vollen Text.

"""
Mehrsprachige Oberfläche (Deutsch und Englisch).

Quellsprache ist **Deutsch**: Die Texte im Quellcode sind zugleich die
msgid-Schlüssel. Deutsch braucht darum keinen Katalog und kann nie fehlen;
für Englisch liegt ein gettext-Katalog unter ``locale/en/LC_MESSAGES/``.

Benutzung im Code::

    from i18n import _, N_

    announce(self, _("Wiedergabe gestartet"))
    announce(self, _("{count} Einträge geladen").format(count=len(rows)))

``_()`` übersetzt sofort, ``N_()`` markiert einen Text nur für die Extraktion –
für Tabellen mit Beschriftungen, die erst beim Anzeigen übersetzt werden.
Platzhalter werden immer benannt (``{count}``), nie positionell: Übersetzer
sehen so, was gemeint ist, und die Reihenfolge darf sich ändern.

Die Sprache wird beim Start gesetzt (siehe ``main.py``). Ein Wechsel wirkt nach
einem Neustart, weil Beschriftungen beim Aufbau der Fenster entstehen.
"""
import gettext
import locale
import os
import sys

DOMAIN = "spotiflix"

#: Auswahl in den Einstellungen: Schlüssel → Anzeigename (bewusst nicht übersetzt).
LANGUAGES = {
    "system": "Automatisch (Systemsprache) / Automatic",
    "de": "Deutsch",
    "en": "English",
}

_translation: gettext.NullTranslations = gettext.NullTranslations()
_current = "de"


def locale_dir() -> str:
    """Verzeichnis mit den Katalogen – im PyInstaller-Bundle im _MEIPASS-Ordner."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "locale")


def system_language() -> str:
    """Ermittelt die Sprache des Systems ('de' oder 'en')."""
    tag = ""
    try:
        if hasattr(locale, "getlocale"):
            tag = (locale.getlocale()[0] or "")
        if not tag:
            tag = os.environ.get("LANG", "")
    except (ValueError, TypeError):
        tag = ""
    tag = tag.replace("-", "_").lower()
    # Deutsch ist die Quellsprache; alles andere bekommt Englisch, weil das
    # verständlicher ist als eine fremde Sprache.
    if tag.startswith("de") or "german" in tag:
        return "de"
    return "en"


def install(language: str = "system") -> str:
    """Lädt den passenden Katalog; liefert die tatsächlich benutzte Sprache."""
    global _translation, _current
    wanted = language if language in LANGUAGES else "system"
    resolved = system_language() if wanted == "system" else wanted

    if resolved == "de":
        # Quellsprache: die Texte im Code sind schon Deutsch.
        _translation = gettext.NullTranslations()
        _current = "de"
        return _current

    try:
        _translation = gettext.translation(DOMAIN, locale_dir(), languages=[resolved])
        _current = resolved
    except OSError:
        # Kein Katalog vorhanden – dann bleibt es bei der Quellsprache.
        _translation = gettext.NullTranslations()
        _current = "de"
    return _current


def current_language() -> str:
    """Gibt die aktive Sprache zurück ('de' oder 'en')."""
    return _current


def _(message: str) -> str:
    """Übersetzt einen Text in die aktive Sprache."""
    return _translation.gettext(message)


def N_(message: str) -> str:
    """Markiert einen Text für die Extraktion, ohne ihn zu übersetzen."""
    return message
