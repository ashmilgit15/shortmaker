from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


_MANAGED_ENV_VARS: set[str] = set()


def load_dotenv_file(
    dotenv_path: str | Path | None,
    *,
    override_keys: Iterable[str] | None = None,
    clear_missing_keys: Iterable[str] | None = None,
) -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ.

    `override_keys` forces selected keys to refresh from the dotenv file even if
    they are already present in the current process environment. If
    `clear_missing_keys` is provided, managed keys absent from the dotenv file
    are removed from `os.environ`.
    """
    if not dotenv_path:
        return

    path = Path(dotenv_path)
    if not path.exists():
        return

    override_key_set = {str(key).strip() for key in (override_keys or ()) if str(key).strip()}
    clear_missing_key_set = {
        str(key).strip() for key in (clear_missing_keys or ()) if str(key).strip()
    }

    try:
        loaded_values: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if not key or key in os.environ:
                continue

            if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]

            loaded_values[key] = value

        for key, value in loaded_values.items():
            if key in override_key_set or key not in os.environ:
                os.environ[key] = value
                _MANAGED_ENV_VARS.add(key)

        for key in clear_missing_key_set:
            if key not in loaded_values and key in _MANAGED_ENV_VARS:
                os.environ.pop(key, None)
                _MANAGED_ENV_VARS.discard(key)
    except OSError:
        return
