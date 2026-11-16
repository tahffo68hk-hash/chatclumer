#!/usr/bin/env python3
"""Build versioned release archives. Does not publish, tag, or talk to the network.

Outputs, under --out:
  chatclumer-<version>.zip            app source bundle
  chatclumer-extension-<version>.zip  Chrome-loadable extension (manifest at the zip root)
  SHA256SUMS                          checksums of those two zips

The app zip also contains its own SHA256SUMS of the packed files.
Secrets, local data, virtualenvs, and dependency folders are left out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".next",
    ".run",
    "dom-dumps",
    ".cursor",
    "release",
}
SKIP_FILE_SUFFIXES = (".pyc", ".db", ".db-journal", ".pem")


def version_from_manifest(root: Path) -> str:
    manifest = json.loads((root / "extension" / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise SystemExit("extension/manifest.json 没有 version")
    return version


def clean_version(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("v") and len(text) > 1 and text[1].isdigit():
        text = text[1:]
    if not text or any(ch not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._-" for ch in text):
        raise SystemExit(f"版本号不合法：{raw!r}")
    return text


def skip_dir(rel: Path) -> bool:
    if rel.name in SKIP_DIR_NAMES:
        return True
    posix = rel.as_posix()
    if posix == "backend/data" or posix.startswith("backend/data/"):
        return True
    if rel.parts and rel.parts[0] == "dist":
        return True
    return False


def skip_file(rel: Path) -> bool:
    name = rel.name
    if name in {".DS_Store", "Thumbs.db", "secrets.json"}:
        return True
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if name.endswith(SKIP_FILE_SUFFIXES):
        return True
    return False


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        kept = []
        for name in sorted(dirnames):
            rel = (rel_dir / name) if rel_dir != Path(".") else Path(name)
            if skip_dir(rel):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root)
            if skip_file(rel):
                continue
            if not path.is_file():
                continue
            # 归档名按 UTF-8 取，不跟当前 locale。LANG=C 时 os.walk 会给出 surrogate，直接 encode 会失败。
            arc = "/".join(os.fsencode(part).decode("utf-8") for part in rel.parts)
            yield path, arc


def zip_info(arcname: str, path: Path) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname)
    info.date_time = time.localtime(path.stat().st_mtime)[:6]
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if arcname.endswith(".sh") else 0o644
    info.external_attr = mode << 16
    return info


def write_zip(destination: Path, items: list[tuple[Path, str]], extra: list[tuple[str, bytes]] | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w") as archive:
        for path, arcname in items:
            archive.writestr(zip_info(arcname, path), path.read_bytes())
        for arcname, payload in extra or []:
            info = zipfile.ZipInfo(arcname)
            info.date_time = time.gmtime()[:6]
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)


def file_checksums(items: list[tuple[Path, str]]) -> str:
    lines = []
    for path, arcname in items:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {arcname}")
    return "\n".join(lines) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release(root: Path, out: Path, version: str | None = None) -> dict:
    root = root.resolve()
    out = out.resolve()
    if not (root / "extension" / "manifest.json").is_file():
        raise SystemExit(f"找不到扩展清单：{root / 'extension' / 'manifest.json'}")
    version = clean_version(version or version_from_manifest(root))
    app_items = [(path, arc) for path, arc in iter_files(root) if out not in path.parents and path != out]
    extension_root = root / "extension"
    extension_items = []
    for path, arc in iter_files(extension_root):
        # iter_files yields paths relative to extension_root; drop the leading name by re-walking.
        extension_items.append((path, arc))
    # iter_files on extension_root already returns paths relative to that root, so the
    # archive names are manifest.json, adapters/registry.json, and so on.
    checksums = file_checksums(app_items)
    app_zip = out / f"chatclumer-{version}.zip"
    extension_zip = out / f"chatclumer-extension-{version}.zip"
    sums_path = out / "SHA256SUMS"
    write_zip(app_zip, app_items, extra=[("SHA256SUMS", checksums.encode("utf-8"))])
    write_zip(extension_zip, extension_items)
    sums = "\n".join(
        [
            f"{sha256_file(app_zip)}  {app_zip.name}",
            f"{sha256_file(extension_zip)}  {extension_zip.name}",
        ]
    ) + "\n"
    sums_path.write_text(sums, encoding="utf-8")
    return {
        "version": version,
        "app": app_zip,
        "extension": extension_zip,
        "sums": sums_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包 ChatClumer 发布文件（不发布、不打 tag）")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", default=None, help="默认用 extension/manifest.json 的 version；可传入 tag（v 前缀会去掉）")
    args = parser.parse_args(argv)
    built = build_release(args.root, args.out, args.version)
    print(built["version"])
    print(built["app"])
    print(built["extension"])
    print(built["sums"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
