"""Build the two submission archives required by the CS239 submission guidelines.

    python3 scripts/package_submission.py

Creates in submission/:
    GuangwenXiong-BankAssist-406999164-requirements.tar.gz   (BankAssist/ only)
    GuangwenXiong-BankAssist-406999164-whole.tar.gz          (code, requirements, tests, traces)

It also refreshes the top-level policies.md from BankAssist/policy.md so the two never drift apart.
"""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

NAME, APP, UID = "GuangwenXiong", "BankAssist", "406999164"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission"

SKIP_DIRS = {"__pycache__", ".pytest_cache", "interactive", ".git"}


def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(info.name).parts
    if any(p in SKIP_DIRS for p in parts) or info.name.endswith(".pyc"):
        return None
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def build() -> list[Path]:
    OUT.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / APP / "policy.md", ROOT / "policies.md")

    req = OUT / f"{NAME}-{APP}-{UID}-requirements.tar.gz"
    with tarfile.open(req, "w:gz") as tar:
        tar.add(ROOT / APP, arcname=APP, filter=_filter)

    whole = OUT / f"{NAME}-{APP}-{UID}-whole.tar.gz"
    with tarfile.open(whole, "w:gz") as tar:
        for item in (APP, "src", "tests", "traces", "scripts", "README.md", "requirements.md",
                     "policies.md", "LICENSE"):
            tar.add(ROOT / item, arcname=item, filter=_filter)
    return [req, whole]


if __name__ == "__main__":
    for path in build():
        with tarfile.open(path) as tar:
            names = tar.getnames()
        print(f"{path.relative_to(ROOT)}  ({path.stat().st_size:,} bytes, {len(names)} entries)")
