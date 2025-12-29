from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "OptAIC"


def default_data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False, roaming=False)) / "data"


def resolve_data_dir(cli_value: Path | None = None) -> Path:
    if cli_value is not None:
        return Path(cli_value)
    env_value = os.environ.get("OPTAIC_DATA_DIR")
    if env_value:
        return Path(env_value)
    return default_data_dir()
