from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def doc_id_from_sha256(sha256: str, length: int = 16) -> str:
    if len(sha256) < length:
        raise ValueError("sha256 value is shorter than requested doc_id length")
    return sha256[:length]

