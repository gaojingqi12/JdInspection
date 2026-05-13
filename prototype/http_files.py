from __future__ import annotations

from pathlib import Path


def path_is_within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True
