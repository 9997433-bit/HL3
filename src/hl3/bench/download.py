# SPDX-License-Identifier: Apache-2.0
"""Fetch official DIC Challenge archives into a gitignored cache.

URLs come from https://idics.org/challenge/ (Google Drive folders named there).
The SEM-DIC round-robin folder is refused (RUL-04). Images are never written
into git; this module only fills ``benchmarks/challenge/cache/``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_NOT_RUN = 2

_DENIED_FOLDER_IDS = frozenset(
    {
        "1w0f7g6Jshbwl0k6mXwu3GjBd5hWUuGKH",  # SEM-DIC Round Robin
    }
)

__all__ = [
    "EXIT_NOT_RUN",
    "EXIT_OK",
    "EXIT_PROBLEM",
    "cache_root",
    "download",
    "download_drive_file",
    "load_manifest",
    "main",
]


def cache_root() -> Path:
    """Directory that holds unpacked Challenge files.

    ``HL3_CHALLENGE_ROOT`` overrides the in-tree cache so a machine can keep
    the multi-gigabyte Stereo Sample 1 zip off the working copy.
    """
    override = os.environ.get("HL3_CHALLENGE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (
        Path(__file__).resolve().parents[3] / "benchmarks" / "challenge" / "cache"
    )


def _manifest_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "challenge"
        / "manifest.json"
    )


def load_manifest() -> dict[str, Any]:
    path = _manifest_path()
    return json.loads(path.read_text(encoding="utf-8"))


def download_drive_file(file_id: str, dest: Path) -> Path:
    """Download one Google Drive file by id into ``dest``."""
    if file_id in _DENIED_FOLDER_IDS:
        raise PermissionError(f"refusing to download denied Drive id {file_id}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    try:
        import gdown
    except ImportError as error:
        raise RuntimeError(
            "downloading Challenge archives needs gdown; "
            "pip install 'hl3[bench]' or pip install gdown"
        ) from error
    gdown.download(id=file_id, output=str(dest), quiet=True)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError(f"download produced no bytes: {dest}")
    return dest


def _unzip(archive: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(target)
    return target


def download(what: str = "2d") -> dict[str, Path]:
    """Fetch the default archives for ``2d`` or ``stereo`` into the cache."""
    key = what.strip().lower()
    if key in {"sem", "sem-dic", "sem_dic"}:
        raise PermissionError(
            "SEM-DIC Challenge data is not fetched (RUL-04 microscope block)"
        )
    manifest = load_manifest()
    root = cache_root()
    written: dict[str, Path] = {}
    if key in {"2d", "2d-1.0", "sample14", "sample15"}:
        files = manifest["datasets"]["2d_challenge_1.0"]["files"]
        dest_dir = root / "2d"
        wanted = files
        if key == "sample14":
            wanted = {"Sample14.zip": files["Sample14.zip"]}
        elif key == "sample15":
            wanted = {"Sample15.zip": files["Sample15.zip"]}
        for name, file_id in wanted.items():
            archive = download_drive_file(file_id, dest_dir / name)
            written[name] = _unzip(archive, dest_dir / Path(name).stem)
        return written
    if key in {"stereo", "stereo-1.0", "sample1"}:
        files = manifest["datasets"]["stereo_challenge_1.0"]["files"]
        dest_dir = root / "stereo" / "sample1"
        for name, file_id in files.items():
            dest = dest_dir / name
            written[name] = download_drive_file(file_id, dest)
        return written
    raise ValueError(
        f"unknown dataset {what!r}; expected 2d, sample14, sample15, or stereo"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hl3.bench.download")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the official Drive ids from the manifest and exit",
    )
    parser.add_argument(
        "--fetch",
        metavar="NAME",
        help="2d | sample14 | sample15 | stereo",
    )
    args = parser.parse_args(argv)
    if args.list:
        manifest = load_manifest()
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return EXIT_OK
    if not args.fetch:
        print("error: pass --list or --fetch NAME", file=sys.stderr)
        return EXIT_NOT_RUN
    try:
        written = download(args.fetch)
    except PermissionError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_NOT_RUN
    except (RuntimeError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_PROBLEM
    for name, path in written.items():
        print(f"{name}\t{path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
