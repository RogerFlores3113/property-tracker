"""The user's own Anthropic key: where it is kept and whether one is set. Never the key itself in a page or a log.

The key lives in ``ai.key`` (owner-only) in the data folder, or comes from ``ANTHROPIC_API_KEY``. It is never in the
database, so it is never in a backup. The AI features themselves (calls to Anthropic, prompts) are built on top of
this by ``ai.py``.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from . import paths

ENV_KEY = "ANTHROPIC_API_KEY"


def key_path() -> Path:
    return paths.data_dir() / "ai.key"


def _clean_key(key: str) -> str:
    return re.sub(r"\s+", "", key or "")


def get_key() -> str:
    """The saved key, else ANTHROPIC_API_KEY, else ''."""
    try:
        saved = _clean_key(key_path().read_text(encoding="utf-8"))
    except OSError:
        saved = ""
    return saved or _clean_key(os.environ.get(ENV_KEY, ""))


def save_key(key: str) -> None:
    """Keep the key in ``ai.key`` (0600 where the OS has file modes). Raises ValueError for something that can't be a key."""
    key = _clean_key(key)
    if len(key) < 20 or not re.fullmatch(r"[\x21-\x7e]+", key):
        raise ValueError("That doesn't look like an API key. Copy the whole key from console.anthropic.com (it starts with sk-).")
    path = key_path()
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key)
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def remove_key() -> bool:
    """Delete the saved key file. A key in the environment is not ours to remove."""
    try:
        key_path().unlink()
        return True
    except FileNotFoundError:
        return False


def key_status() -> dict[str, Any]:
    """``{"set", "source" ('file', 'env' or ''), "hint" ('ending in ...abcd' or '')}``. Never the key itself."""
    try:
        saved = _clean_key(key_path().read_text(encoding="utf-8"))
    except OSError:
        saved = ""
    env = _clean_key(os.environ.get(ENV_KEY, ""))
    key = saved or env
    return {"set": bool(key), "source": "file" if saved else ("env" if env else ""),
            "hint": f"ending in ...{key[-4:]}" if key else ""}
