#!/usr/bin/env python3
from __future__ import annotations

import getpass
import re
import shutil
from pathlib import Path


def main() -> int:
    config_path = Path("config.yaml")
    if not config_path.exists():
        print("config.yaml not found. Run this from /Users/tristanzh/agent/agent06-pka")
        return 1

    text = config_path.read_text()
    new_key = getpass.getpass("New DeepSeek API key: ").strip()
    if not new_key:
        print("No key entered; config unchanged.")
        return 1

    match = re.search(r"(?ms)^deepseek:\n(?:^[ \t]+.*\n)+", text)
    if not match:
        print("Could not find deepseek block; config unchanged.")
        return 1

    block = match.group(0)
    replacement = "'" + new_key.replace("'", "''") + "'"
    new_block, count = re.subn(
        r"(?m)^([ \t]+api_key:[ \t]*).*$",
        lambda m: m.group(1) + replacement,
        block,
        count=1,
    )
    if count != 1:
        print("Could not find deepseek.api_key; config unchanged.")
        return 1

    backup_path = config_path.with_suffix(".yaml.bak.deepseek-rotate")
    shutil.copy2(config_path, backup_path)
    config_path.write_text(text[: match.start()] + new_block + text[match.end() :])
    print("DeepSeek api_key updated. OCR/Doubao config was not changed.")
    print(f"Backup written to {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
