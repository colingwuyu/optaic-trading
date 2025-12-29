from __future__ import annotations

import json

from optaic.config import Settings
from optaic.runtime.channel import (
    derive_lane_url,
    read_channel_state,
    resolve_channel,
    resolve_package_index_url,
    write_channel_state,
)


def test_derive_lane_url_infers_scheme() -> None:
    url = derive_lane_url("artifactory.local", "staging")
    assert url == "http://artifactory.local:8081/simple"


def test_channel_resolution_precedence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPTAIC_CHANNEL", "uat")
    settings = Settings()
    assert resolve_channel(settings, tmp_path) == "uat"

    write_channel_state(tmp_path, "staging")
    assert resolve_channel(settings, tmp_path) == "staging"
    assert resolve_channel(settings, tmp_path, override="prod") == "prod"


def test_read_channel_state_invalid(tmp_path) -> None:
    path = tmp_path / "state" / "channel.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"channel": "invalid"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_channel_state(tmp_path) is None


def test_resolve_package_index_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPTAIC_CHANNEL", "prod")
    monkeypatch.setenv("OPTAIC_ARTIFACTORY_BASE_URL", "http://host")
    settings = Settings()
    assert resolve_package_index_url(settings, tmp_path) == "http://host:8083/simple"

    monkeypatch.setenv("OPTAIC_PACKAGE_INDEX_URL", "http://override/simple")
    settings = Settings()
    assert resolve_package_index_url(settings, tmp_path) == "http://override/simple"
