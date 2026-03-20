from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

_DOTENV_LOADED_KEYS_ENV = "__SHORTMAKER_DOTENV_KEYS"


def _get_loaded_keys() -> set[str]:
    raw = os.environ.get(_DOTENV_LOADED_KEYS_ENV, "")
    return {
        item.strip()
        for item in raw.split(",")
        if item.strip()
    }


def _set_loaded_keys(keys: set[str]) -> None:
    os.environ[_DOTENV_LOADED_KEYS_ENV] = ",".join(sorted(keys))


def load_dotenv_file(
    dotenv_path: str | Path | None,
    *,
    override: bool = False,
    override_keys: Iterable[str] | None = None,
    clear_missing_keys: Iterable[str] | None = None,
) -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ."""
    if not dotenv_path:
        return

    path = Path(dotenv_path)
    if not path.exists():
        return

    try:
        loaded_keys = _get_loaded_keys()
        override_key_set = {item.strip() for item in (override_keys or []) if str(item).strip()}
        clear_missing_key_set = {item.strip() for item in (clear_missing_keys or []) if str(item).strip()}
        seen_keys: set[str] = set()
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            seen_keys.add(key)

            if not key:
                continue

            should_override_key = key in override_key_set
            if not override and not should_override_key and key in os.environ and key not in loaded_keys:
                continue

            if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]

            os.environ[key] = value
            loaded_keys.add(key)
        for key in clear_missing_key_set:
            if key in seen_keys:
                continue
            if key in os.environ:
                del os.environ[key]
            loaded_keys.discard(key)
        _set_loaded_keys(loaded_keys)
    except OSError:
        return
