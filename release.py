#!/usr/bin/env python3
"""
D&D Notes — Release Helper
Run this script before tagging a new release. It:
  1. Reads APP_VERSION from app.py
  2. Prompts you to enter changelog bullet points
  3. SHA256-hashes app.py and generate_notes.py
  4. Writes manifest.json
  5. Prints the git commands to run next

Usage:  python release.py
"""

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def read_version() -> str:
    src = (HERE / "app.py").read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*["\'](.+?)["\']', src, re.MULTILINE)
    if not m:
        print("ERROR: Could not find APP_VERSION in app.py")
        sys.exit(1)
    return m.group(1)


def main():
    version = read_version()
    print(f"\n  D&D Notes Release Helper")
    print(f"  ========================")
    print(f"  Version from app.py: {version}\n")

    # Collect changelog
    print("  Enter changelog items (one per line, blank line to finish):")
    changelog = []
    while True:
        line = input("  > ").strip()
        if not line:
            break
        changelog.append(line)

    if not changelog:
        print("\n  WARNING: No changelog entered. Continuing anyway.\n")

    # Hash the distributable files
    files_to_hash = ["app.py", "generate_notes.py"]
    file_entries = {}
    for name in files_to_hash:
        p = HERE / name
        if not p.exists():
            print(f"ERROR: {name} not found in {HERE}")
            sys.exit(1)
        digest = sha256(p)
        file_entries[name] = {"sha256": digest}
        print(f"  {name}: {digest[:16]}...")

    manifest = {
        "version": version,
        "changelog": changelog,
        "files": file_entries,
    }

    manifest_path = HERE / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n  manifest.json written.\n")

    print("  Next steps:")
    print(f"    git add manifest.json")
    print(f"    git commit -m \"v{version}: <short description>\"")
    print(f"    git tag v{version}")
    print(f"    git push && git push --tags")
    print()


if __name__ == "__main__":
    main()
