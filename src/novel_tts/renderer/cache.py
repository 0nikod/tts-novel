from __future__ import annotations

import shutil
from pathlib import Path

from .audio import validate_canonical_wave
from .models import OutputConfig


def cache_path(render_root: Path, cache_key: str) -> Path:
    return render_root / "cache" / f"{cache_key}.wav"


def is_cache_hit(path: Path, output: OutputConfig) -> bool:
    try:
        validate_canonical_wave(path, output)
    except (FileNotFoundError, OSError, ValueError):
        return False
    return True


def copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)
