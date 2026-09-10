"""
Werkzeug für die Übersetzungskataloge – ohne GNU gettext.

Auf Windows ist gettext normalerweise nicht installiert, darum bringt das
Projekt Extraktion, Abgleich und Kompilierung selbst mit:

    py tools/i18n_tool.py extract    # Texte aus dem Quellcode -> locale/spotiflix.pot
    py tools/i18n_tool.py update     # neue Texte in locale/en/.../spotiflix.po übernehmen
    py tools/i18n_tool.py compile    # .po -> .mo (das liest die Anwendung)
    py tools/i18n_tool.py check      # fehlende Übersetzungen und Kürzel prüfen

Gefunden werden Aufrufe von ``_()`` und ``N_()`` mit einer Zeichenkette als
erstem Argument. Quellsprache ist Deutsch: Die msgid ist der deutsche Text,
Deutsch braucht daher keinen Katalog.
"""
import argparse
import ast
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAIN = "spotiflix"
LOCALE_DIR = os.path.join(ROOT, "locale")
POT_PATH = os.path.join(LOCALE_DIR, f"{DOMAIN}.pot")
#: Sprachen mit Katalog (Deutsch ist die Quellsprache und braucht keinen).
CATALOG_LANGUAGES = ("en",)
SKIP_DIRS = {"build", "dist", "__pycache__", ".git", ".venv", "tools"}


# ----------------------------------------------------------------- Extraktion

def source_files() -> list[str]:
    """Alle Python-Dateien des Projekts (ohne Build- und Werkzeugordner)."""
    found = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(base, name))
    return found


def extract_file(path: str) -> list[tuple[str, int]]:
    """Liefert (Text, Zeile) für jeden ``_()``- oder ``N_()``-Aufruf."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in ("_", "N_"):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append((first.value, node.lineno))
    return found


def extract() -> dict[str, list[str]]:
    """Sammelt alle Texte samt Herkunft (msgid -> ["datei:zeile", …])."""
    catalog: dict[str, list[str]] = {}
    for path in source_files():
        relative = os.path.relpath(path, ROOT).replace("\\", "/")
        for message, line in extract_file(path):
            catalog.setdefault(message, []).append(f"{relative}:{line}")
    return catalog


# ------------------------------------------------------------ .po lesen/schreiben

def po_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\t", "\\t"))


def po_unescape(text: str) -> str:
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def write_po(path: str, entries: dict[str, str], references: dict[str, list[str]],
             language: str | None = None):
    """Schreibt eine .po/.pot-Datei (msgid -> msgstr)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        'msgid ""',
        'msgstr ""',
        '"Project-Id-Version: SpotiFlix\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
    ]
    if language:
        lines.append(f'"Language: {language}\\n"')
    lines.append("")
    for message in sorted(entries):
        for reference in references.get(message, []):
            lines.append(f"#: {reference}")
        lines.append(f'msgid "{po_escape(message)}"')
        lines.append(f'msgstr "{po_escape(entries[message])}"')
        lines.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))


def read_po(path: str) -> dict[str, str]:
    """Liest eine .po-Datei als msgid -> msgstr."""
    if not os.path.isfile(path):
        return {}
    entries: dict[str, str] = {}
    msgid = msgstr = None
    target = None
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("#") or not line:
                continue
            if line.startswith("msgid "):
                if msgid is not None and msgstr is not None:
                    entries[msgid] = msgstr
                msgid = po_unescape(line[6:].strip().strip('"'))
                msgstr = None
                target = "id"
            elif line.startswith("msgstr "):
                msgstr = po_unescape(line[7:].strip().strip('"'))
                target = "str"
            elif line.startswith('"') and target:
                piece = po_unescape(line.strip().strip('"'))
                if target == "id":
                    msgid = (msgid or "") + piece
                else:
                    msgstr = (msgstr or "") + piece
    if msgid is not None and msgstr is not None:
        entries[msgid] = msgstr
    entries.pop("", None)
    return entries


# ------------------------------------------------------------------ .mo bauen

def write_mo(path: str, entries: dict[str, str], language: str = ""):
    """Schreibt einen gettext-Binärkatalog (.mo).

    Format: Magic, Version, Anzahl, Offsets der Tabellen, dann die
    nullterminierten Zeichenketten – wie in der gettext-Dokumentation
    beschrieben. Nur übersetzte Einträge kommen hinein.

    Der Eintrag mit leerer msgid trägt die Kopfdaten. Ohne ihn liest gettext
    den Katalog als ASCII und scheitert am ersten Umlaut.
    """
    metadata = (
        "Content-Type: text/plain; charset=UTF-8\n"
        "Content-Transfer-Encoding: 8bit\n"
    )
    if language:
        metadata += f"Language: {language}\n"
    items = [("", metadata)] + sorted((k, v) for k, v in entries.items() if k and v)
    ids = b"\x00".join(k.encode("utf-8") for k, _v in items) + b"\x00"
    strs = b"\x00".join(v.encode("utf-8") for _k, v in items) + b"\x00"
    count = len(items)
    key_table_offset = 7 * 4
    value_table_offset = key_table_offset + count * 8
    ids_offset = value_table_offset + count * 8
    strs_offset = ids_offset + len(ids)

    key_table, value_table = b"", b""
    position = 0
    for key, _value in items:
        encoded = key.encode("utf-8")
        key_table += struct.pack("<II", len(encoded), ids_offset + position)
        position += len(encoded) + 1
    position = 0
    for _key, value in items:
        encoded = value.encode("utf-8")
        value_table += struct.pack("<II", len(encoded), strs_offset + position)
        position += len(encoded) + 1

    # Kopf: Magic, Revision, Anzahl, Offset der Original- und der
    # Übersetzungstabelle, Größe und Offset der Hash-Tabelle (ungenutzt).
    binary_header = struct.pack(
        "<Iiiiiii",
        0x950412DE,
        0,
        count,
        key_table_offset,
        value_table_offset,
        0,
        0,
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(binary_header + key_table + value_table + ids + strs)


# ------------------------------------------------------------------- Befehle

def po_path(language: str) -> str:
    return os.path.join(LOCALE_DIR, language, "LC_MESSAGES", f"{DOMAIN}.po")


def mo_path(language: str) -> str:
    return os.path.join(LOCALE_DIR, language, "LC_MESSAGES", f"{DOMAIN}.mo")


def command_extract() -> int:
    catalog = extract()
    write_po(POT_PATH, {message: "" for message in catalog}, catalog)
    print(f"{len(catalog)} Texte -> {os.path.relpath(POT_PATH, ROOT)}")
    return 0


def command_update() -> int:
    catalog = extract()
    for language in CATALOG_LANGUAGES:
        existing = read_po(po_path(language))
        merged = {message: existing.get(message, "") for message in catalog}
        kept = sum(1 for message in merged if merged[message])
        removed = [message for message in existing if message not in catalog]
        write_po(po_path(language), merged, catalog, language=language)
        print(f"{language}: {len(merged)} Texte, {kept} übersetzt, "
              f"{len(merged) - kept} offen, {len(removed)} veraltet entfernt")
    return 0


def command_compile() -> int:
    for language in CATALOG_LANGUAGES:
        entries = read_po(po_path(language))
        translated = {k: v for k, v in entries.items() if v}
        write_mo(mo_path(language), translated, language=language)
        print(f"{language}: {len(translated)} Übersetzungen -> "
              f"{os.path.relpath(mo_path(language), ROOT)}")
    return 0


def command_check() -> int:
    catalog = extract()
    problems = 0
    for language in CATALOG_LANGUAGES:
        entries = read_po(po_path(language))
        missing = [m for m in catalog if not entries.get(m)]
        # Menütexte tragen ihr Tastenkürzel hinter einem Tabulator. Bleibt es
        # in der Übersetzung nicht gleich, funktioniert die Taste nicht mehr.
        broken = []
        for message, translation in entries.items():
            if "\t" not in message or not translation:
                continue
            if message.split("\t", 1)[1] != translation.split("\t", 1)[-1]:
                broken.append(message.split("\t", 1)[0])
        placeholder = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*")
        mismatched = []
        for message, translation in entries.items():
            if not translation:
                continue
            if set(placeholder.findall(message)) != set(placeholder.findall(translation)):
                mismatched.append(message[:60])
        print(f"--- {language}")
        print(f"    Texte insgesamt : {len(catalog)}")
        print(f"    ohne Übersetzung: {len(missing)}")
        print(f"    Kürzel kaputt   : {len(broken)}")
        print(f"    Platzhalter falsch: {len(mismatched)}")
        for entry in (missing[:10] + broken[:10] + mismatched[:10]):
            print("      *", entry.replace("\n", " ")[:70])
        problems += len(broken) + len(mismatched)
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Übersetzungskataloge pflegen")
    parser.add_argument("command", choices=("extract", "update", "compile", "check"))
    arguments = parser.parse_args()
    return {
        "extract": command_extract,
        "update": command_update,
        "compile": command_compile,
        "check": command_check,
    }[arguments.command]()


if __name__ == "__main__":
    sys.exit(main())
