from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from utils.env_loader import load_dotenv_file

BASE_DIR = Path(__file__).resolve().parent
CLERK_RUNTIME_KEYS = ("CLERK_ISSUER", "CLERK_AUDIENCE", "CLERK_JWKS_URL")
VENV_PYTHON_CANDIDATES = [
    BASE_DIR / "venv" / "Scripts" / "python.exe",
    BASE_DIR / ".venv" / "Scripts" / "python.exe",
]


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _find_project_python() -> Path | None:
    for candidate in VENV_PYTHON_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _ensure_project_python() -> None:
    current_python = Path(sys.executable)
    if any(_is_within(current_python, candidate.parent.parent) for candidate in VENV_PYTHON_CANDIDATES if candidate.exists()):
        return

    project_python = _find_project_python()
    if not project_python:
        raise SystemExit(
            "Project virtualenv not found. Create it with `python -m venv venv` and install requirements first."
        )

    child = subprocess.Popen(
        [str(project_python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )
    try:
        raise SystemExit(child.wait())
    except KeyboardInterrupt:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        raise SystemExit(130)


def main() -> None:
    _ensure_project_python()
    load_dotenv_file(BASE_DIR / ".env", override_keys=CLERK_RUNTIME_KEYS, clear_missing_keys=CLERK_RUNTIME_KEYS)

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[
            str(BASE_DIR / "backend"),
            str(BASE_DIR / "frontend"),
            str(BASE_DIR / "utils"),
        ],
        reload_excludes=[
            "venv/*",
            ".venv/*",
            "outputs/*",
            "*.log",
        ],
        reload_includes=[
            "*.py",
            ".env",
        ],
    )


if __name__ == "__main__":
    main()
