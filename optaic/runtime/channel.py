from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.parse

from optaic.config import Settings

CHANNEL_PORTS = {
    "staging": 8081,
    "uat": 8082,
    "prod": 8083,
}
DEFAULT_CHANNEL = "prod"


def resolve_channel(
    settings: Settings,
    data_dir: Path,
    override: str | None = None,
) -> str:
    if override:
        return _normalize_channel(override)
    stored = read_channel_state(data_dir)
    if stored:
        return stored
    return _normalize_channel(settings.channel)


def resolve_package_index_url(
    settings: Settings,
    data_dir: Path,
    *,
    channel: str | None = None,
) -> str | None:
    if settings.package_index_url:
        return settings.package_index_url
    if not settings.artifactory_base_url:
        return None
    resolved_channel = resolve_channel(settings, data_dir, channel)
    return derive_lane_url(settings.artifactory_base_url, resolved_channel)


def derive_lane_url(base_url: str, channel: str) -> str:
    normalized_channel = _normalize_channel(channel)
    port = CHANNEL_PORTS[normalized_channel]
    base = base_url.strip().rstrip("/")
    if "://" not in base:
        base = f"http://{base}"
    parsed = urllib.parse.urlparse(base)
    host = parsed.hostname or parsed.netloc or base_url
    scheme = parsed.scheme or "http"
    return f"{scheme}://{host}:{port}/simple"


def read_channel_state(data_dir: Path) -> str | None:
    path = data_dir / "state" / "channel.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    channel = payload.get("channel")
    if not isinstance(channel, str):
        return None
    channel = channel.strip().lower()
    if channel in CHANNEL_PORTS:
        return channel
    return None


def write_channel_state(
    data_dir: Path,
    channel: str,
    *,
    actor_principal_id: str | None = None,
) -> Path:
    normalized = _normalize_channel(channel)
    path = data_dir / "state" / "channel.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "channel": normalized,
        "saved_at": _utc_now(),
        "actor_principal_id": actor_principal_id,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _normalize_channel(channel: str | None) -> str:
    if not channel:
        return DEFAULT_CHANNEL
    normalized = channel.strip().lower()
    if normalized in CHANNEL_PORTS:
        return normalized
    raise ValueError(f"Invalid channel '{channel}'. Expected staging, uat, or prod.")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
