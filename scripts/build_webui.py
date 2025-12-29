from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "apps" / "web"
DIST_DIR = WEB_DIR / "dist"
TARGET_DIR = ROOT / "optaic" / "webui_dist"


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)

def _run_npm(args: list[str]) -> None:
    if shutil.which("npm") is None:
        raise FileNotFoundError(
            "npm not found on PATH. Install Node.js to build the web UI."
        )

    if os.name == "nt":
        command = ["cmd", "/c", "npm", *args]
    else:
        command = ["npm", *args]

    _run(command, WEB_DIR)

def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return result.stdout.strip() or None


def main() -> None:
    if not WEB_DIR.is_dir():
        raise FileNotFoundError(f"Web app directory not found: {WEB_DIR}")

    _run_npm(["ci"])
    _run_npm(["run", "build"])

    if not DIST_DIR.is_dir():
        raise FileNotFoundError(f"Expected build output at: {DIST_DIR}")

    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(DIST_DIR, TARGET_DIR)

    build_info = {
        "commit": _git_commit(ROOT),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (TARGET_DIR / ".buildinfo.json").write_text(
        json.dumps(build_info, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
