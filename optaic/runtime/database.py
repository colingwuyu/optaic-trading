from __future__ import annotations

from pathlib import Path

from optaic.config import Settings


def resolve_database_url(settings: Settings, data_dir: Path) -> str | None:
    if settings.mode == "embedded" and not settings.database_url:
        db_path = (data_dir / "db" / "optaic.sqlite").resolve()
        return f"sqlite+aiosqlite:///{db_path.as_posix()}"
    return settings.database_url
