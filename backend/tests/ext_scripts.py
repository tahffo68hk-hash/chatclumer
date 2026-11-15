"""Script tags the content scripts need before guest.js / site adapters (0.5.0 registry)."""

from pathlib import Path

EXT = Path(__file__).resolve().parents[2] / "extension"
ADAPTER_FILES = ("adapters/schema.js", "adapters/registry.js", "adapters/runtime.js")


def add_adapters(page) -> None:
    for name in ADAPTER_FILES:
        page.add_script_tag(path=str(EXT / name))
