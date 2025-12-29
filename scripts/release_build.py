from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import tomllib


def _run(cmd: list[str]) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _read_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data["project"]["version"]


def main() -> None:
    _run([sys.executable, "-m", "ruff", "check", "."])
    _run([sys.executable, "-m", "pytest"])
    _run([sys.executable, "-m", "build"])
    version = _read_version()
    print(f"Built OptAIC version {version}")


if __name__ == "__main__":
    main()
