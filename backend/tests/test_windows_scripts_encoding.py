"""Windows PowerShell 5.1 reads a .ps1 without a BOM as the ANSI code page, which breaks Chinese strings."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_powershell_script_with_non_ascii_text_has_a_utf8_bom():
    scripts = sorted((ROOT / "scripts").glob("*.ps1"))
    assert scripts
    for script in scripts:
        raw = script.read_bytes()
        if any(byte > 0x7F for byte in raw):
            assert raw.startswith(b"\xef\xbb\xbf"), f"{script.name} needs a UTF-8 BOM for Windows PowerShell 5.1"
