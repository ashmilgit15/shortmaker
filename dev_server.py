from __future__ import annotations

from pathlib import Path

import uvicorn


BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
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
            str(BASE_DIR / "venv" / "*"),
            str(BASE_DIR / ".venv" / "*"),
            str(BASE_DIR / "outputs" / "*"),
            str(BASE_DIR / "*.log"),
        ],
    )


if __name__ == "__main__":
    main()
