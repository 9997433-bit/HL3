# SPDX-License-Identifier: Apache-2.0
"""Image file writers with no dependency beyond the standard library.

This module exists so that ``hl3.viz`` can put a picture on disk on a machine
that has nothing but Python and NumPy. Everything here works on an ``uint8``
array that is already the finished picture -- colour mapping, scaling and
annotation happen in :mod:`hl3.viz.plot2d`, and by the time an array reaches
this module the only remaining question is byte layout.

Three formats, chosen for what they cost to write correctly:

* **PNG** -- the format the rest of the world expects. Written with ``zlib``
  from the standard library: an 8-bit IHDR, one IDAT holding filter-0
  scanlines, IEND. No interlacing, no palette, no ancillary chunks. It is a
  small subset of the specification, but it is a *conforming* subset, so the
  files open in browsers, image viewers and Pillow alike.
* **PPM / PGM** (Netpbm ``P6``/``P5``, and the ASCII ``P3``/``P2``) -- a
  header and raw bytes. There is no compressor and no checksum to get wrong,
  which makes them the format to reach for when a PNG comes out wrong and the
  question is whether the pixels or the encoder are at fault.

Encoding is deterministic: the same array and the same ``compress_level``
produce byte-identical files, so a rendering can be diffed or hashed in a
regression test instead of eyeballed.

Grayscale ``(h, w)``, RGB ``(h, w, 3)`` and RGBA ``(h, w, 4)`` arrays are all
accepted by :func:`write_png`; Netpbm has no alpha channel and rejects RGBA
rather than silently dropping it.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "IMAGE_FORMATS",
    "PNG_MAGIC",
    "encode_png",
    "encode_pnm",
    "format_for_path",
    "png_size",
    "write_image",
    "write_pgm",
    "write_png",
    "write_ppm",
]

#: Formats this module can write, as lowercase names without the dot.
IMAGE_FORMATS: tuple[str, ...] = ("png", "pgm", "ppm")

#: The eight-byte PNG signature (PNG spec 5.2).
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# PNG colour types (spec 11.2.2), keyed by channel count.
_COLOR_TYPE = {1: 0, 3: 2, 4: 6}

# Netpbm magic numbers, keyed by (channels, ascii).
_PNM_MAGIC = {(1, False): b"P5", (1, True): b"P2", (3, False): b"P6", (3, True): b"P3"}

_MAX_COMPRESS_LEVEL = 9


def _as_image(image: Any, name: str = "image") -> np.ndarray:
    """Validate a finished picture: ``uint8``, 2D grayscale or 3D with 1/3/4 bands.

    ``uint8`` is required rather than converted. A float array here is almost
    always a normalised field that skipped the colour mapping step, and
    guessing whether it is on ``[0, 1]`` or ``[0, 255]`` would turn that
    mistake into a plausible-looking but wrong image.
    """
    array = np.asarray(image)
    if array.dtype != np.uint8:
        raise TypeError(
            f"{name} must be uint8 (a finished picture), got dtype {array.dtype}; "
            "use hl3.viz.plot2d.render_field to turn a data field into one"
        )
    if array.ndim == 3 and array.shape[2] == 1:
        array = array[:, :, 0]
    if array.ndim not in (2, 3):
        raise ValueError(
            f"{name} must be (h, w) or (h, w, channels), got shape {array.shape}"
        )
    if array.ndim == 3 and array.shape[2] not in _COLOR_TYPE:
        raise ValueError(
            f"{name} must have 1, 3 or 4 channels, got {array.shape[2]}"
        )
    if array.shape[0] < 1 or array.shape[1] < 1:
        raise ValueError(f"{name} must have a non-zero height and width, got {array.shape}")
    return np.ascontiguousarray(array)


def _channels(array: np.ndarray) -> int:
    return 1 if array.ndim == 2 else int(array.shape[2])


def _chunk(tag: bytes, payload: bytes) -> bytes:
    """One PNG chunk: length, type, payload, CRC-32 over type and payload."""
    crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)


def encode_png(image: Any, *, compress_level: int = 6) -> bytes:
    """Encode a finished picture as PNG bytes.

    Every scanline uses filter type 0 (None). Filtering exists to make the
    deflate stream smaller, and the adaptive heuristic that chooses per-line
    filters is where a hand-written encoder usually goes wrong; a colour-mapped
    field of a few hundred pixels a side compresses well enough without it.
    """
    array = _as_image(image)
    if isinstance(compress_level, bool) or compress_level != int(compress_level):
        raise ValueError(f"compress_level must be an integer, got {compress_level!r}")
    level = int(compress_level)
    if not 0 <= level <= _MAX_COMPRESS_LEVEL:
        raise ValueError(f"compress_level must be in 0..9, got {level}")

    height, width = int(array.shape[0]), int(array.shape[1])
    channels = _channels(array)
    rows = array.reshape(height, width * channels)
    # Prepend the per-scanline filter byte in one allocation.
    raw = np.zeros((height, width * channels + 1), dtype=np.uint8)
    raw[:, 1:] = rows

    ihdr = struct.pack(">IIBBBBB", width, height, 8, _COLOR_TYPE[channels], 0, 0, 0)
    return b"".join(
        (
            PNG_MAGIC,
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", zlib.compress(raw.tobytes(), level)),
            _chunk(b"IEND", b""),
        )
    )


def encode_pnm(image: Any, *, ascii_format: bool = False) -> bytes:
    """Encode as Netpbm: ``P5``/``P6`` binary, or ``P2``/``P3`` ASCII.

    Grayscale gives PGM, RGB gives PPM; the format follows the array rather
    than the file name so that a three-channel picture never lands in a
    single-channel file.
    """
    array = _as_image(image)
    channels = _channels(array)
    if channels == 4:
        raise ValueError(
            "Netpbm has no alpha channel; drop it or write PNG instead"
        )
    magic = _PNM_MAGIC[(channels, bool(ascii_format))]
    header = b"%s\n%d %d\n255\n" % (magic, int(array.shape[1]), int(array.shape[0]))
    if ascii_format:
        flat = array.reshape(int(array.shape[0]), -1)
        body = b"\n".join(b" ".join(b"%d" % v for v in row) for row in flat) + b"\n"
        return header + body
    return header + array.tobytes()


def format_for_path(path: str | Path) -> str:
    """The format name implied by a file suffix, lowercased and without the dot."""
    suffix = Path(path).suffix.lower().lstrip(".")
    if not suffix:
        raise ValueError(
            f"cannot tell the image format from {str(path)!r}: it has no suffix; "
            f"expected one of {', '.join(IMAGE_FORMATS)}"
        )
    return suffix


def _write_bytes(path: str | Path, payload: bytes) -> Path:
    target = Path(path)
    parent = target.parent
    if str(parent) and not parent.is_dir():
        raise FileNotFoundError(
            f"directory {str(parent)!r} does not exist; create it before writing "
            f"{target.name!r}"
        )
    target.write_bytes(payload)
    return target


def write_png(path: str | Path, image: Any, *, compress_level: int = 6) -> Path:
    """Write a PNG and return the path written."""
    return _write_bytes(path, encode_png(image, compress_level=compress_level))


def write_ppm(path: str | Path, image: Any, *, ascii_format: bool = False) -> Path:
    """Write an RGB Netpbm (``P6``, or ``P3`` when ``ascii_format``)."""
    array = _as_image(image)
    if _channels(array) != 3:
        raise ValueError(
            f"write_ppm needs a 3-channel RGB image, got {_channels(array)} channel(s); "
            "use write_pgm for grayscale"
        )
    return _write_bytes(path, encode_pnm(array, ascii_format=ascii_format))


def write_pgm(path: str | Path, image: Any, *, ascii_format: bool = False) -> Path:
    """Write a grayscale Netpbm (``P5``, or ``P2`` when ``ascii_format``)."""
    array = _as_image(image)
    if _channels(array) != 1:
        raise ValueError(
            f"write_pgm needs a single-channel image, got {_channels(array)}; "
            "use write_ppm for RGB"
        )
    return _write_bytes(path, encode_pnm(array, ascii_format=ascii_format))


def write_image(
    path: str | Path,
    image: Any,
    *,
    image_format: str | None = None,
    compress_level: int = 6,
    ascii_format: bool = False,
) -> Path:
    """Write PNG, PPM or PGM, choosing the encoder from the suffix by default."""
    fmt = (image_format or format_for_path(path)).lower().lstrip(".")
    if fmt not in IMAGE_FORMATS:
        raise ValueError(
            f"unsupported image format {fmt!r}; this writer handles "
            f"{', '.join(IMAGE_FORMATS)}"
        )
    array = _as_image(image)
    if fmt == "png":
        return write_png(path, array, compress_level=compress_level)
    if fmt == "ppm":
        return write_ppm(path, array, ascii_format=ascii_format)
    return write_pgm(path, array, ascii_format=ascii_format)


def png_size(payload: bytes) -> tuple[int, int]:
    """``(width, height)`` from a PNG header, for checking what was written.

    Reads only the signature and IHDR, so it works on any PNG, not just the
    ones :func:`encode_png` produced.
    """
    if len(payload) < 24 or not payload.startswith(PNG_MAGIC):
        raise ValueError("not a PNG file: signature missing")
    if payload[12:16] != b"IHDR":
        raise ValueError("not a PNG file: first chunk is not IHDR")
    width, height = struct.unpack(">II", payload[16:24])
    return int(width), int(height)
