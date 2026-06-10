"""Persistent jieba dictionary cache for FunASR punctuation."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_configured = False


def cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "wav2chat" / "jieba"
    return Path.home() / ".cache" / "wav2chat" / "jieba"


def _dict_source_path() -> Path:
    import jieba

    return Path(jieba.__file__).resolve().parent / "dict.txt"


def _dict_fingerprint() -> str:
    import jieba

    dict_path = _dict_source_path()
    digest = hashlib.sha256()
    with dict_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"{jieba.__version__}\n{digest.hexdigest()}\n"


def configure_jieba_cache(*, prewarm: bool = True) -> Path:
    """Point jieba at a persistent cache; rebuild when dict.txt changes."""
    global _configured

    import jieba

    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    cache_file = root / "jieba.cache"
    tag_file = root / "jieba.dict.tag"

    fingerprint = _dict_fingerprint()
    tag_matches = tag_file.exists() and tag_file.read_text(encoding="utf-8") == fingerprint
    if not tag_matches:
        cache_file.unlink(missing_ok=True)
        logger.info("jieba dictionary changed; rebuilding cache at %s", cache_file)

    jieba.dt.tmp_dir = str(root)
    jieba.dt.cache_file = str(cache_file)
    jieba.setLogLevel(logging.WARNING)
    logging.getLogger("jieba").setLevel(logging.WARNING)

    if prewarm and not jieba.dt.initialized:
        jieba.dt.initialize()

    if not tag_matches:
        tag_file.write_text(fingerprint, encoding="utf-8")

    if not _configured:
        logger.debug("jieba cache directory: %s", root)
        _configured = True

    return root
