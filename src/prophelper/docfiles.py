"""Safe handling of the files a person adds to a place (leases, applications, photos). No web code here.

* The file on disk gets a generated name (random hex plus a short, plain extension), so nothing a person typed ever
  becomes a path. The name they gave is kept only for display, cleaned of folders and control characters.
* Files live in ``<data folder>/files/<place id>/``. :func:`stored_path` refuses anything that resolves outside that
  folder, anything that is a symbolic link, and any name that is not one of ours.
* The size limit is ``store.UPLOAD_LIMIT_BYTES`` (20 MB).
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path
from urllib.parse import quote

from . import helpers, paths
from .store import UPLOAD_LIMIT_BYTES

LIMIT_BYTES = UPLOAD_LIMIT_BYTES
LIMIT_TEXT = "20 MB"
NAME_MAX = 200
STORED_RE = re.compile(r"^[0-9a-f]{32}(\.[a-z0-9]{1,8})?$")  # what stored_name() makes, and the only names we read back


def display_name(raw: str | None) -> str:
    """The name to show: no folders, no control characters, trimmed, at most 200 characters. '' when nothing is left."""
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>"|?*:').strip().strip(".")
    if len(name) > NAME_MAX:
        stem, dot, ext = name.rpartition(".")
        keep = NAME_MAX - len(ext) - 1 if dot and len(ext) <= 10 else NAME_MAX
        name = (stem[:keep] + "." + ext) if dot and len(ext) <= 10 else name[:NAME_MAX]
    return name


def extension(name: str) -> str:
    """A lower-case extension of letters and digits only (up to 8), with its dot, or ''."""
    ext = Path(name).suffix.lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{1,8}", ext) else ""


def stored_name(original: str) -> str:
    """A new random file name that keeps only a plain extension."""
    return secrets.token_hex(16) + extension(original)


def place_folder(place_id: int) -> Path:
    return paths.files_dir() / str(int(place_id))


def too_big_text() -> str:
    """The one sentence shown for a file over the limit."""
    return f"That file is too big (limit {LIMIT_TEXT})."


def check_upload(name: str, size: int) -> str:
    """'' when the upload is fine, else one plain sentence saying why not."""
    if not display_name(name):
        return "Choose a file first."
    if size <= 0:
        return "That file is empty."
    if size > LIMIT_BYTES:
        return too_big_text()
    return ""


def save(place_id: int, original: str, data: bytes) -> str:
    """Write ``data`` into the place's folder under a new generated name and return the stored name.
    Raises ValueError when the upload breaks the rules above."""
    problem = check_upload(original, len(data))
    if problem:
        raise ValueError(problem)
    folder = paths.private_dir(place_folder(place_id))
    written = helpers.write_new_file(folder / stored_name(original), data)
    return written.name


def stored_path(place_id: int, stored: str) -> Path | None:
    """The file for a stored name, or None when the name isn't one of ours, the file is missing or a link, or it
    would be outside the place's folder."""
    if not STORED_RE.fullmatch(stored or ""):
        return None
    folder = place_folder(place_id)
    path = folder / stored
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if folder.resolve() not in path.resolve().parents:
            return None
    except OSError:
        return None
    return path


def remove(place_id: int, stored: str) -> bool:
    """Delete one stored file (only a safe path). True when a file was removed."""
    path = stored_path(place_id, stored)
    if path is None:
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def attachment_headers(original: str, size: int) -> dict[str, str]:
    """Headers for a download: always an attachment, always opaque bytes, never shown in the page, never sniffed."""
    shown = display_name(original) or "file"
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", shown).strip() or "file"
    return {
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(shown, safe='')}",
        "Content-Length": str(size),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
        "Cache-Control": "no-store",
    }
