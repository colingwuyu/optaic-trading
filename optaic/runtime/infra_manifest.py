from __future__ import annotations

import json
from importlib import resources
from typing import Any


def load_manifest() -> dict[str, Any]:
    manifest_path = resources.files("optaic.infra") / "versions.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def get_tool(manifest: dict[str, Any], tool: str) -> dict[str, Any]:
    tools = manifest.get("tools", {})
    if tool not in tools:
        raise KeyError(f"Tool '{tool}' not found in infra manifest.")
    return tools[tool]


def get_default_version(manifest: dict[str, Any], tool: str) -> str:
    entry = get_tool(manifest, tool)
    version = entry.get("default_version")
    if not version:
        raise KeyError(f"Default version missing for tool '{tool}'.")
    return version


def get_asset(manifest: dict[str, Any], tool: str, asset_key: str) -> dict[str, str]:
    entry = get_tool(manifest, tool)
    assets = entry.get("assets", {})
    asset = assets.get(asset_key)
    if not asset:
        raise KeyError(f"Asset '{asset_key}' not found for tool '{tool}'.")
    url = asset.get("url")
    sha256 = asset.get("sha256")
    if not url or not sha256:
        raise KeyError(f"Asset '{asset_key}' missing url/sha256 for tool '{tool}'.")
    return {"url": url, "sha256": sha256}
