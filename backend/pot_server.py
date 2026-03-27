"""PO Token HTTP server manager.

Manages the bgutil-ytdlp-pot-provider HTTP server as a background process
to automatically generate YouTube Proof-of-Origin tokens. This is the
recommended approach by yt-dlp maintainers and used by cobalt.tools.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PORT = 4416
DEFAULT_TOKEN_TTL_HOURS = 6
_HEALTH_CHECK_INTERVAL = 30
_CONTAINER_NAME = "shortmaker-bgutil-pot"

_server_lock = threading.Lock()
_server_process: subprocess.Popen | None = None
_server_port: int = 0
_server_started = False


def _get_docker_path() -> str | None:
    return shutil.which("docker")


def _get_node_path() -> str | None:
    return shutil.which("node")


def _get_bgutil_install_dir() -> Path:
    return Path.home() / "bgutil-ytdlp-pot-provider"


def bgutil_installed() -> bool:
    """Check if bgutil-ytdlp-pot-provider is installed locally."""
    install_dir = _get_bgutil_install_dir()
    server_dir = install_dir / "server"
    build_dir = server_dir / "build" / "main.js"
    return build_dir.exists()


def bgutil_docker_available() -> bool:
    """Check if the bgutil Docker image is available or Docker is present."""
    docker = _get_docker_path()
    if not docker:
        return False
    try:
        result = subprocess.run(
            [docker, "images", "-q", "brainicism/bgutil-ytdlp-pot-provider"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def docker_available() -> bool:
    return _get_docker_path() is not None


def is_server_running() -> bool:
    """Check if a PO Token server process is active."""
    global _server_process
    if _server_process is None:
        return False
    return _server_process.poll() is None


def check_server_health(base_url: str) -> bool | None:
    """Ping the PO Token server. Returns True/False/None if not configured."""
    if not base_url:
        return None
    try:
        import urllib.request

        health_url = base_url.rstrip("/") + "/ping"
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_server_docker(port: int = DEFAULT_PORT) -> bool:
    """Start the bgutil PO Token server via Docker."""
    global _server_process, _server_port, _server_started

    docker = _get_docker_path()
    if not docker:
        logger.warning("Docker is not available for PO Token server.")
        return False

    # Stop any existing container
    try:
        subprocess.run(
            [docker, "rm", "-f", _CONTAINER_NAME],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass

    cmd = [
        docker,
        "run",
        "--name",
        _CONTAINER_NAME,
        "-d",
        "--init",
        "-p",
        f"{port}:{DEFAULT_PORT}",
        "brainicism/bgutil-ytdlp-pot-provider",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            _server_port = port
            _server_started = True
            logger.info(
                "PO Token server started via Docker on port %d (container: %s).",
                port,
                _CONTAINER_NAME,
            )
            return True
        logger.warning("Docker PO Token server failed: %s", result.stderr.strip())
        return False
    except Exception as exc:
        logger.warning("Failed to start Docker PO Token server: %s", exc)
        return False


def start_server_native(port: int = DEFAULT_PORT) -> bool:
    """Start the bgutil PO Token server via Node.js directly."""
    global _server_process, _server_port, _server_started

    node = _get_node_path()
    if not node:
        logger.warning("Node.js is not available for PO Token server.")
        return False

    install_dir = _get_bgutil_install_dir()
    server_js = install_dir / "server" / "build" / "main.js"
    if not server_js.exists():
        logger.warning("bgutil server not found at %s. Install it first.", server_js)
        return False

    env = os.environ.copy()
    env["TOKEN_TTL"] = str(DEFAULT_TOKEN_TTL_HOURS)

    try:
        proc = subprocess.Popen(
            [node, str(server_js), "--port", str(port)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _server_process = proc
        _server_port = port
        _server_started = True
        logger.info(
            "PO Token server started via Node.js on port %d (PID %d).",
            port,
            proc.pid,
        )
        return True
    except Exception as exc:
        logger.warning("Failed to start native PO Token server: %s", exc)
        return False


def stop_server() -> None:
    """Stop the running PO Token server."""
    global _server_process, _server_started

    # Try Docker first
    docker = _get_docker_path()
    if docker:
        try:
            subprocess.run(
                [docker, "stop", _CONTAINER_NAME],
                capture_output=True,
                timeout=15,
            )
            subprocess.run(
                [docker, "rm", _CONTAINER_NAME],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

    # Stop native process
    if _server_process and _server_process.poll() is None:
        try:
            _server_process.terminate()
            _server_process.wait(timeout=5)
        except Exception:
            try:
                _server_process.kill()
            except Exception:
                pass
        _server_process = None

    _server_started = False
    logger.info("PO Token server stopped.")


def ensure_server_started(port: int = DEFAULT_PORT) -> dict[str, Any]:
    """Start the PO Token server if not already running.

    Tries Docker first, then falls back to native Node.js.
    Returns a status dict.
    """
    with _server_lock:
        # Check if already running
        base_url = f"http://127.0.0.1:{port}"
        if is_server_running() or check_server_health(base_url):
            return {
                "started": True,
                "method": "already_running",
                "port": port,
                "base_url": base_url,
                "message": "PO Token server is already running.",
            }

        # Try Docker first
        if bgutil_docker_available() or docker_available():
            if start_server_docker(port):
                return {
                    "started": True,
                    "method": "docker",
                    "port": port,
                    "base_url": base_url,
                    "message": "PO Token server started via Docker.",
                }

        # Try native Node.js
        if bgutil_installed() and _get_node_path():
            if start_server_native(port):
                return {
                    "started": True,
                    "method": "native",
                    "port": port,
                    "base_url": base_url,
                    "message": "PO Token server started via Node.js.",
                }

        return {
            "started": False,
            "method": None,
            "port": port,
            "base_url": base_url,
            "message": (
                "Could not start PO Token server. Install bgutil-ytdlp-pot-provider:\n"
                "  Option A (Docker): docker pull brainicism/bgutil-ytdlp-pot-provider\n"
                "  Option B (Node.js): git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "
                "&& cd bgutil-ytdlp-pot-provider/server && npm ci && npx tsc"
            ),
        }


def get_server_status(port: int = DEFAULT_PORT) -> dict[str, Any]:
    """Get the current status of the PO Token server."""
    base_url = f"http://127.0.0.1:{port}"
    running = is_server_running()
    healthy = check_server_health(base_url)

    return {
        "process_running": running,
        "healthy": healthy,
        "port": port,
        "base_url": base_url,
        "docker_image_available": bgutil_docker_available(),
        "native_installed": bgutil_installed(),
        "docker_available": docker_available(),
        "node_available": _get_node_path() is not None,
    }
