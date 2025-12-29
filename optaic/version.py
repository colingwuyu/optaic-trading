from __future__ import annotations

from importlib import metadata


def get_version() -> str:
    try:
        dist_names = metadata.packages_distributions().get("optaic", [])
        for dist in dist_names:
            return metadata.version(dist)
    except Exception:
        pass

    for candidate in ("optaic", "resource-activity-platform"):
        try:
            return metadata.version(candidate)
        except metadata.PackageNotFoundError:
            continue
    return "0.0.0"
