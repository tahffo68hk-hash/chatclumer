"""Write extension/adapters/registry.js from registry.json (the JSON file is the source of truth).

Content scripts cannot read a JSON file synchronously, so the bundled copy is also shipped as a
plain data assignment. Run after editing registry.json; test_adapter_registry checks they match.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "extension" / "adapters" / "registry.json"
OUT = ROOT / "extension" / "adapters" / "registry.js"


def render() -> str:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return (
        "// 由 scripts/build_registry.py 从 registry.json 生成，不要手改。只是数据，没有逻辑。\n"
        f"globalThis.CHATCLUMER_REGISTRY = {body};\n"
    )


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
