# SPDX-License-Identifier: Apache-2.0
"""``python -m hl3 run`` -- correlate an image sequence from the shell.

    python -m hl3 run reference.npy deformed.npy --out fields.npz
    python -m hl3 run --synthetic --frames 4 --summary run.json
    python -m hl3 run frames/*.pgm --subset 31 --step 10 --out u.npy --field u

Two ways in, one way through. Either the images are files on disk, or
``--synthetic`` builds them with :class:`hl3.capture.MockCapture`; from there
both paths hand the same object to :func:`hl3.pipeline.run_sequence` and the
same :class:`hl3.pipeline.Dic2DRun` comes back. ``--synthetic`` therefore
exercises the real chain rather than a demo of it, which is what makes it
usable as a smoke test on a machine with no data on it -- and CPU-only CI has
no data on it.

**No mathematics lives here.** Grid construction, seeding, reference updates,
strain hand-off and every number in the output belong to
:mod:`hl3.pipeline.dic2d` and :mod:`hl3.correlate`; this module parses flags
into a :class:`hl3.pipeline.Dic2DConfig`, reads images, and serialises what it
is handed. The same rule the validate command follows for conformance
(``.agent_workspace/s1s4/IR2-F4-validate-cli.md`` section 1) applies here for
correlation: a CLI that computes anything of its own becomes a second, informal
implementation that can disagree with the library.

Image input needs no third-party package for the formats HL3 itself writes:
``.npy`` / ``.npz`` and Netpbm (``.pgm``, ``.pnm``) are read here. PNG and TIFF
go through Pillow when it is installed, and say so plainly when it is not.
Colour images are refused rather than silently converted, because the
RGB-to-grey weighting changes the correlated signal and picking one for the
user would be a measurement decision taken in an argument parser.

Exit codes match the rest of the CLI:

===== ===========================================================
    0 the run finished and met the ``--min-valid-fraction`` gate
    1 the run finished but missed the gate
    2 the run could not be made -- usage error, unreadable image,
      an impossible configuration, or ``--strain required`` with
      no strain backend
===== ===========================================================

Output is deterministic in the sense the kernels are: same inputs and flags,
same numbers, and the JSON summary is byte-for-byte identical between runs. The
``.npz`` container is a zip and carries file timestamps, so its *bytes* differ
between runs even though its arrays do not.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hl3.capture import MockCapture
from hl3.correlate import ICGNParams, Status
from hl3.pipeline import (
    Dic2DConfig,
    Dic2DRun,
    ReferenceMode,
    SeedMode,
    StrainMode,
    StrainUnavailableError,
    run_sequence,
)

__all__ = [
    "ImageLoadError",
    "UsageError",
    "build_parser",
    "load_image",
    "main",
    "summary_dict",
]

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_NOT_RUN = 2

#: Version of the JSON summary layout. Bumped only when a key changes meaning
#: or disappears; new keys are additive and do not bump it.
SUMMARY_SCHEMA = 1

DEFAULT_PROG = "python -m hl3 run"

_NETPBM_SUFFIXES = frozenset({".pgm", ".pnm"})


class UsageError(Exception):
    """The command cannot be carried out as asked. Reported as exit code 2."""


class ImageLoadError(UsageError):
    """An image could not be read as a 2-D greyscale array."""


# --------------------------------------------------------------------------
# Image input
# --------------------------------------------------------------------------


def load_image(path: str | Path) -> np.ndarray:
    """Read one greyscale image as a 2-D ``float64`` array.

    ``.npy`` and ``.npz`` (single array) and Netpbm are handled here; anything
    else is offered to Pillow. Grey *levels are not rescaled*: a 16-bit file
    keeps its 0..65535 range, because ZNSSD is invariant to affine intensity
    changes and a helpful normalisation here would only make the numbers in a
    log harder to recognise.
    """
    path = Path(path)
    if not path.exists():
        raise ImageLoadError(f"no such image file: {path}")

    suffix = path.suffix.lower()
    if suffix == ".npy":
        array = _load_npy(path)
    elif suffix == ".npz":
        array = _load_npz(path)
    elif suffix in _NETPBM_SUFFIXES:
        array = _load_netpbm(path)
    else:
        array = _load_with_pillow(path)

    array = np.asarray(array)
    if array.ndim != 2:
        raise ImageLoadError(
            f"{path}: expected a 2-D greyscale image, got shape {array.shape}. "
            "Convert colour or stacked data to a single grey plane first; the "
            "RGB weighting is a measurement choice HL3 will not make for you."
        )
    result = array.astype(np.float64)
    if not np.all(np.isfinite(result)):
        raise ImageLoadError(f"{path}: image contains NaN or infinity")
    return result


def _load_npy(path: Path) -> np.ndarray:
    try:
        # allow_pickle stays off: an image file must not be able to execute code.
        return np.load(path, allow_pickle=False)
    except Exception as error:  # noqa: BLE001
        raise ImageLoadError(f"{path}: {type(error).__name__}: {error}") from error


def _load_npz(path: Path) -> np.ndarray:
    try:
        with np.load(path, allow_pickle=False) as handle:
            names = list(handle.files)
            if len(names) != 1:
                raise ImageLoadError(
                    f"{path}: an .npz input must hold exactly one array, found "
                    f"{len(names)} ({', '.join(names) or 'none'}); extract the "
                    "one you mean into an .npy"
                )
            return handle[names[0]]
    except ImageLoadError:
        raise
    except Exception as error:  # noqa: BLE001
        raise ImageLoadError(f"{path}: {type(error).__name__}: {error}") from error


def _load_netpbm(path: Path) -> np.ndarray:
    """Read a binary (P5) or ASCII (P2) greyscale Netpbm image.

    Netpbm is here because it is the one real image format that can be written
    with the standard library alone, which keeps the file-input path of this
    command testable in an environment with no image library at all.
    """
    data = path.read_bytes()
    magic = data[:2]
    if magic not in (b"P2", b"P5"):
        raise ImageLoadError(
            f"{path}: expected a greyscale Netpbm image (P2 or P5), got "
            f"{magic!r}. Colour Netpbm (P3/P6) must be converted to grey first."
        )

    fields: list[int] = []
    position = 2
    while len(fields) < 3:
        while position < len(data) and data[position : position + 1].isspace():
            position += 1
        if position >= len(data):
            raise ImageLoadError(f"{path}: truncated Netpbm header")
        if data[position : position + 1] == b"#":
            while position < len(data) and data[position : position + 1] not in (
                b"\n",
                b"\r",
            ):
                position += 1
            continue
        start = position
        while position < len(data) and not data[position : position + 1].isspace():
            position += 1
        try:
            fields.append(int(data[start:position]))
        except ValueError as error:
            raise ImageLoadError(f"{path}: bad Netpbm header field") from error

    width, height, maxval = fields
    if width <= 0 or height <= 0 or not 0 < maxval <= 65535:
        raise ImageLoadError(
            f"{path}: implausible Netpbm header {width}x{height} maxval {maxval}"
        )

    if magic == b"P2":
        values = np.array(data[position:].split(), dtype=np.float64)
    else:
        # Exactly one whitespace byte separates a P5 header from its raster.
        dtype = np.dtype(">u2") if maxval > 255 else np.dtype(np.uint8)
        values = np.frombuffer(data, dtype=dtype, offset=position + 1)
    if values.size < width * height:
        raise ImageLoadError(
            f"{path}: truncated Netpbm raster, expected {width * height} "
            f"samples, found {values.size}"
        )
    return values[: width * height].reshape(height, width)


def _load_with_pillow(path: Path) -> np.ndarray:
    try:
        from PIL import Image
    except ImportError as error:
        raise ImageLoadError(
            f"{path}: reading '{path.suffix or 'this format'}' needs Pillow, "
            "which is not installed (pip install pillow). Formats that need no "
            "dependency: .npy, .npz, .pgm, .pnm"
        ) from error

    try:
        with Image.open(path) as image:
            mode = image.mode
            if mode not in ("L", "I", "I;16", "I;16B", "F", "1"):
                raise ImageLoadError(
                    f"{path}: image mode {mode!r} is not greyscale. Convert it "
                    "outside HL3 -- the RGB-to-grey weighting changes the "
                    "correlated signal and is a measurement decision."
                )
            return np.asarray(image)
    except ImageLoadError:
        raise
    except Exception as error:  # noqa: BLE001
        raise ImageLoadError(f"{path}: {type(error).__name__}: {error}") from error


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def build_parser(prog: str = DEFAULT_PROG) -> argparse.ArgumentParser:
    """The ``run`` command line. Separated out so ``--help`` is testable."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Correlate an image sequence with the CPU reference IC-GN solver "
            "and write displacement fields. Give two or more image files, or "
            "--synthetic for a hardware-free demo sequence."
        ),
        epilog=(
            "exit codes: 0 ran and met --min-valid-fraction; 1 ran and missed "
            "it; 2 could not run.\n"
            "image formats: .npy, .npz (one array), .pgm/.pnm always; PNG and "
            "TIFF when Pillow is installed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "images",
        nargs="*",
        metavar="IMAGE",
        help="two or more greyscale image files, in acquisition order",
    )

    source = parser.add_argument_group("synthetic source (no files, no cameras)")
    source.add_argument(
        "--synthetic",
        action="store_true",
        help=(
            "generate the sequence with hl3.capture.MockCapture instead of "
            "reading files; frame i is the reference shifted by (2i, i) px"
        ),
    )
    source.add_argument(
        "--frames", type=int, default=3, metavar="N",
        help="synthetic frame count, including the reference (default: %(default)s)",
    )
    source.add_argument(
        "--size", default="64x64", metavar="HxW",
        help="synthetic image size in pixels (default: %(default)s)",
    )
    source.add_argument(
        "--seed", type=int, default=0, metavar="N",
        help="synthetic speckle seed (default: %(default)s)",
    )
    source.add_argument(
        "--noise", type=float, default=0.0, metavar="SIGMA",
        help="synthetic Gaussian noise in grey levels (default: %(default)s)",
    )

    correlation = parser.add_argument_group("correlation (hl3.correlate.ICGNParams)")
    correlation.add_argument(
        "--subset", type=int, default=2 * ICGNParams().subset_radius + 1, metavar="PX",
        help="subset size in pixels, odd and >= 5 (default: %(default)s)",
    )
    correlation.add_argument(
        "--step", type=int, default=ICGNParams().step, metavar="PX",
        help="POI grid spacing in pixels (default: %(default)s)",
    )
    correlation.add_argument(
        "--search-radius", type=int, default=ICGNParams().search_radius, metavar="PX",
        help="FFT-CC integer search half-width; 0 disables it (default: %(default)s)",
    )
    correlation.add_argument(
        "--zncc-min", type=float, default=ICGNParams().zncc_min, metavar="F",
        help="reject a point below this ZNCC (default: %(default)s)",
    )
    correlation.add_argument(
        "--max-iter", type=int, default=ICGNParams().max_iter, metavar="N",
        help="IC-GN iteration cap per point (default: %(default)s)",
    )
    correlation.add_argument(
        "--conv-tol", type=float, default=ICGNParams().conv_tol, metavar="PX",
        help="convergence tolerance on the scaled step (default: %(default)s)",
    )
    correlation.add_argument(
        "--shape-order", type=int, choices=(1, 2), default=1,
        help="shape function: 1 = affine, 2 = quadratic (default: %(default)s)",
    )
    correlation.add_argument(
        "--margin", type=int, default=None, metavar="PX",
        help="border kept free of POIs (default: subset radius + search radius + 2)",
    )

    sequence = parser.add_argument_group("sequence")
    sequence.add_argument(
        "--reference-index", type=int, default=0, metavar="N",
        help="which frame is the reference (default: %(default)s)",
    )
    sequence.add_argument(
        "--reference-mode",
        choices=[mode.value for mode in ReferenceMode],
        default=ReferenceMode.FIXED.value,
        help="when to adopt a new reference (default: %(default)s)",
    )
    sequence.add_argument(
        "--every-n", type=int, default=Dic2DConfig().reference_every_n, metavar="N",
        help="frames per reference under --reference-mode every_n (default: %(default)s)",
    )
    sequence.add_argument(
        "--reference-zncc", type=float, default=Dic2DConfig().reference_zncc,
        metavar="F",
        help=(
            "median ZNCC below which --reference-mode incremental updates "
            "(default: %(default)s)"
        ),
    )
    sequence.add_argument(
        "--seed-mode",
        choices=[mode.value for mode in SeedMode],
        default=SeedMode.PREV_FRAME.value,
        help="where each point's initial guess comes from (default: %(default)s)",
    )

    strain = parser.add_argument_group("strain")
    strain.add_argument(
        "--strain",
        choices=[mode.value for mode in StrainMode],
        default=StrainMode.AUTO.value,
        help=(
            "off: never call hl3.strain; auto: use it when available; "
            "required: fail the run without it (default: %(default)s)"
        ),
    )
    strain.add_argument(
        "--strain-window", type=int, default=Dic2DConfig().strain_window, metavar="N",
        help="strain fit window in data points, odd and >= 3 (default: %(default)s)",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "--out", metavar="PATH",
        help=(
            "write fields to PATH; .npz holds every field plus the JSON "
            "summary, .npy holds the single field named by --field"
        ),
    )
    output.add_argument(
        "--field", default="u", metavar="NAME",
        help="field written by '--out PATH.npy' (default: %(default)s)",
    )
    output.add_argument(
        "--summary", metavar="PATH",
        help="write the JSON summary to PATH, or to stdout with '-'",
    )
    output.add_argument(
        "--min-valid-fraction", type=float, default=0.0, metavar="F",
        help=(
            "exit 1 when any frame converges on a smaller fraction of points "
            "than this (default: %(default)s, i.e. no gate)"
        ),
    )
    output.add_argument(
        "--quiet", action="store_true",
        help="suppress the human-readable report on stdout",
    )
    return parser


# --------------------------------------------------------------------------
# Flags -> configuration
# --------------------------------------------------------------------------


def _config(args: argparse.Namespace) -> Dic2DConfig:
    if args.subset < 5 or args.subset % 2 == 0:
        raise UsageError(
            f"--subset must be an odd number of pixels >= 5, got {args.subset}"
        )
    if not 0.0 <= args.min_valid_fraction <= 1.0:
        raise UsageError(
            "--min-valid-fraction must lie in [0, 1], got "
            f"{args.min_valid_fraction}"
        )
    try:
        icgn = ICGNParams(
            subset_radius=args.subset // 2,
            step=args.step,
            search_radius=args.search_radius,
            zncc_min=args.zncc_min,
            max_iter=args.max_iter,
            conv_tol=args.conv_tol,
            shape_order=args.shape_order,
        )
        return Dic2DConfig(
            icgn=icgn,
            reference_index=args.reference_index,
            reference_mode=ReferenceMode(args.reference_mode),
            reference_every_n=args.every_n,
            reference_zncc=args.reference_zncc,
            seed_mode=SeedMode(args.seed_mode),
            margin=args.margin,
            strain_mode=StrainMode(args.strain),
            strain_window=args.strain_window,
        )
    except (TypeError, ValueError) as error:
        # The kernel and the pipeline own the validity rules; the CLI just
        # reports their verdict with the flag names the user typed.
        raise UsageError(str(error)) from error


def _source(args: argparse.Namespace) -> tuple[Any, dict[str, Any]]:
    """Return ``(images, description)`` for either input path."""
    if args.synthetic:
        if args.images:
            raise UsageError(
                "--synthetic generates its own frames; drop the image "
                f"arguments ({len(args.images)} given) or drop --synthetic"
            )
        height, width = _parse_size(args.size)
        if args.frames < 2:
            raise UsageError(f"--frames must be at least 2, got {args.frames}")
        try:
            capture = MockCapture(
                frame_count=args.frames,
                shape=(height, width),
                seed=args.seed,
                noise_sigma=args.noise,
            )
        except ValueError as error:
            raise UsageError(str(error)) from error
        return capture, {
            "kind": "synthetic",
            "generator": "hl3.capture.MockCapture",
            "frames": args.frames,
            "shape": [height, width],
            "seed": args.seed,
            "noise_sigma": args.noise,
            "paths": [],
        }

    if len(args.images) < 2:
        raise UsageError(
            "give at least two image files (reference first), or --synthetic "
            f"for a generated sequence; got {len(args.images)}"
        )
    images = [load_image(path) for path in args.images]
    return images, {
        "kind": "files",
        "frames": len(images),
        "shape": [int(n) for n in images[0].shape],
        "paths": [str(path) for path in args.images],
    }


def _parse_size(text: str) -> tuple[int, int]:
    parts = text.lower().replace("*", "x").split("x")
    try:
        if len(parts) != 2:
            raise ValueError
        height, width = (int(part) for part in parts)
    except ValueError:
        raise UsageError(f"--size must look like HxW, got {text!r}") from None
    if height < 8 or width < 8:
        raise UsageError(f"--size must be at least 8x8, got {text!r}")
    return height, width


# --------------------------------------------------------------------------
# Results -> files
# --------------------------------------------------------------------------


def _fields(run: Dic2DRun) -> dict[str, np.ndarray]:
    """Every array a caller could want, keyed by the name used in the npz.

    Displacement fields are masked (non-converged points are NaN) exactly as
    :meth:`hl3.pipeline.Dic2DRun.field` masks them; ``status`` and
    ``iterations`` are not, because NaN would erase what they are for.
    """
    fields: dict[str, np.ndarray] = {
        "x": run.points[:, 0],
        "y": run.points[:, 1],
    }
    for name in ("u", "v", "u_x", "u_y", "v_x", "v_y", "zncc", "status", "iterations"):
        fields[name] = run.field(name)
    fields["valid"] = run.valid_mask()
    if run.strain.available:
        for name in run.strain.names:
            fields[name] = run.strain_field(name)
    return fields


def _write_out(path: Path, field: str, fields: Mapping[str, np.ndarray],
               summary: Mapping[str, Any]) -> None:
    if path.suffix == ".npz":
        np.savez(
            path,
            summary_json=np.array(_dumps(summary)),
            **{name: value for name, value in fields.items()},
        )
        return
    if path.suffix == ".npy":
        if field not in fields:
            raise UsageError(
                f"--field {field!r} is not one of the computed fields: "
                + ", ".join(sorted(fields))
            )
        np.save(path, fields[field], allow_pickle=False)
        return
    raise UsageError(
        f"--out must end in .npz (all fields) or .npy (one field), got "
        f"{path.suffix or path.name!r}"
    )


def summary_dict(
    run: Dic2DRun,
    source: Mapping[str, Any],
    *,
    min_valid_fraction: float,
    outputs: Mapping[str, Any],
) -> dict[str, Any]:
    """The JSON summary: what was run, what came out, and how good it is.

    ``config`` is generated from the dataclasses rather than listed here, so a
    new kernel parameter appears in the summary of every future run without an
    edit to this command.
    """
    valid = [frame.valid_fraction for frame in run.frames]
    zncc = [frame.zncc_median for frame in run.frames]
    passed = bool(valid) and min(valid) >= min_valid_fraction
    return {
        "tool": "hl3 run",
        "schema": SUMMARY_SCHEMA,
        "source": dict(source),
        "config": {
            "icgn": dataclasses.asdict(run.config.icgn),
            "subset_size": run.config.subset_size,
            "reference_index": run.config.reference_index,
            "reference_mode": run.config.reference_mode.value,
            "reference_every_n": run.config.reference_every_n,
            "reference_zncc": run.config.reference_zncc,
            "seed_mode": run.config.seed_mode.value,
            "margin": run.config.margin,
            "strain_mode": run.config.strain_mode.value,
            "strain_window": run.config.strain_window,
            "l_vsg_px": run.config.l_vsg_px,
        },
        "provenance": run.provenance,
        "frames": [_frame_summary(frame) for frame in run.frames],
        "quality": {
            "n_frames": run.n_frames,
            "n_points": run.n_points,
            "grid_shape": run.grid_shape,
            "valid_fraction_min": min(valid) if valid else 0.0,
            "valid_fraction_mean": float(np.mean(valid)) if valid else 0.0,
            "zncc_median_min": min(zncc) if zncc else math.nan,
            "gate": {
                "min_valid_fraction": min_valid_fraction,
                "passed": passed,
            },
        },
        "strain": {
            "available": run.strain.available,
            "backend": run.strain.backend,
            "reason": run.strain.reason,
            "fields": list(run.strain.names),
        },
        "outputs": dict(outputs),
    }


def _frame_summary(frame: Any) -> dict[str, Any]:
    u = frame.u[frame.valid]
    v = frame.v[frame.valid]
    return {
        "index": frame.index,
        "frame_index": frame.frame_index,
        "reference_index": frame.reference_index,
        "reference_updated": frame.reference_updated,
        "timestamp_s": frame.timestamp_s,
        "valid_fraction": frame.valid_fraction,
        "zncc_median": frame.zncc_median,
        "u_mean": float(np.mean(u)) if u.size else math.nan,
        "v_mean": float(np.mean(v)) if v.size else math.nan,
        "u_range": [float(np.min(u)), float(np.max(u))] if u.size else [None, None],
        "v_range": [float(np.min(v)), float(np.max(v))] if v.size else [None, None],
        "status_counts": {
            status.name: count for status, count in frame.status_counts().items()
        },
    }


def _dumps(payload: Mapping[str, Any]) -> str:
    """Serialise deterministically and, above all, validly.

    ``allow_nan=False`` is the point: Python's json module happily writes a
    bare ``NaN``, which is not JSON and which half the readers downstream will
    reject. Non-finite values -- an all-rejected frame's median ZNCC, say --
    become ``null`` in :func:`_jsonable` before they get here.
    """
    return json.dumps(
        _jsonable(payload),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (bool, str)) or value is None:
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, Status):
        return value.name
    return str(value)


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    """Run one sequence. Returns the exit code instead of calling ``sys.exit``."""
    args = build_parser(prog).parse_args(argv)
    try:
        return _execute(args)
    except UsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_NOT_RUN
    except StrainUnavailableError as error:
        # Asked for with --strain required, so its absence is a failure to run
        # rather than a poor result: no output would answer the question asked.
        print(f"error: strain was required but unavailable: {error}", file=sys.stderr)
        return EXIT_NOT_RUN
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_NOT_RUN


def _execute(args: argparse.Namespace) -> int:
    config = _config(args)
    images, source = _source(args)
    # Destinations are checked before the correlation, not after it: a run is
    # the expensive part and must not be thrown away over a typo in a path.
    out_path = _writable(args.out, "--out", suffixes=(".npz", ".npy"))
    summary_path = None if args.summary == "-" else _writable(args.summary, "--summary")
    # A summary on stdout must be the only thing on stdout, or it is not JSON.
    verbose = not args.quiet and args.summary != "-"

    try:
        run = run_sequence(images, config)
    except (TypeError, ValueError) as error:
        raise UsageError(str(error)) from error

    fields = _fields(run)
    if out_path is not None and out_path.suffix == ".npy" and args.field not in fields:
        # Checked before the summary claims an output that will not be written.
        raise UsageError(
            f"--field {args.field!r} is not one of the computed fields: "
            + ", ".join(sorted(fields))
        )

    outputs: dict[str, Any] = {
        "npz": str(out_path) if out_path and out_path.suffix == ".npz" else None,
        "npy": (
            {"path": str(out_path), "field": args.field}
            if out_path and out_path.suffix == ".npy"
            else None
        ),
        "summary": "-" if args.summary == "-" else (
            str(summary_path) if summary_path else None
        ),
    }
    summary = summary_dict(
        run, source, min_valid_fraction=args.min_valid_fraction, outputs=outputs
    )

    if out_path is not None:
        _write_out(out_path, args.field, fields, summary)
    text = _dumps(summary)
    if args.summary == "-":
        print(text)
    elif summary_path is not None:
        summary_path.write_text(text + "\n", encoding="utf-8")

    if verbose:
        _report(run, source, summary, out_path, summary_path)

    if not summary["quality"]["gate"]["passed"]:
        print(
            "gate: worst frame converged on "
            f"{summary['quality']['valid_fraction_min']:.1%} of points, below "
            f"the --min-valid-fraction of {args.min_valid_fraction:.1%}",
            file=sys.stderr,
        )
        return EXIT_PROBLEM
    return EXIT_OK


def _writable(
    path: str | None, flag: str, *, suffixes: tuple[str, ...] | None = None
) -> Path | None:
    """Reject an unusable destination before spending the correlation on it."""
    if path is None:
        return None
    resolved = Path(path)
    if suffixes is not None and resolved.suffix not in suffixes:
        raise UsageError(
            f"{flag} must end in {' or '.join(suffixes)}, got "
            f"{resolved.suffix or resolved.name!r}"
        )
    parent = resolved.parent if str(resolved.parent) else Path(".")
    if not parent.is_dir():
        raise UsageError(f"{flag}: directory does not exist: {parent}")
    if resolved.is_dir():
        raise UsageError(f"{flag}: {resolved} is a directory")
    return resolved


def _report(
    run: Dic2DRun,
    source: Mapping[str, Any],
    summary: Mapping[str, Any],
    out_path: Path | None,
    summary_path: Path | None,
) -> None:
    quality = summary["quality"]
    grid = (
        f"{run.grid_shape[0]} x {run.grid_shape[1]} grid"
        if run.grid_shape
        else "scattered"
    )
    if source["kind"] == "synthetic":
        origin = (
            f"MockCapture(frames={source['frames']}, "
            f"size={source['shape'][0]}x{source['shape'][1]}, "
            f"seed={source['seed']}, noise={source['noise_sigma']})"
        )
    else:
        origin = f"{len(source['paths'])} files, first {source['paths'][0]}"

    print(f"source     {origin}")
    print(
        f"images     {run.n_frames} frames of "
        f"{source['shape'][0]}x{source['shape'][1]} px"
    )
    print(
        f"points     {run.n_points} ({grid}), subset "
        f"{run.config.subset_size} px, step {run.config.step} px, "
        f"L_VSG {run.config.l_vsg_px} px"
    )
    strain = summary["strain"]
    print(
        "strain     "
        + (
            f"{strain['backend']} -> " + ", ".join(strain["fields"])
            if strain["available"]
            else f"unavailable ({strain['reason']})"
        )
    )
    print()
    print("frame   valid     zncc      u_mean      v_mean  reference")
    for frame in summary["frames"]:
        print(
            f"{frame['index']:>5}"
            f"  {frame['valid_fraction']:>6.1%}"
            f"  {_number(frame['zncc_median'], 7, '>7.4f')}"
            f"  {_number(frame['u_mean'], 10, '>+10.4f')}"
            f"  {_number(frame['v_mean'], 10, '>+10.4f')}"
            f"  {frame['reference_index']:>9}"
            + ("  (updated)" if frame["reference_updated"] else "")
        )
    print()
    print(
        f"quality    valid fraction min {quality['valid_fraction_min']:.3f}, "
        f"mean {quality['valid_fraction_mean']:.3f}"
    )
    for path in (out_path, summary_path):
        if path is not None:
            print(f"wrote      {path}")


def _number(value: float | None, width: int, spec: str) -> str:
    """Non-finite numbers print as a dash rather than as ``nan`` in a column.

    A frame where nothing converged has no median ZNCC and no mean
    displacement; ``nan`` in the column reads like a computed value, a dash
    does not.
    """
    if value is None or not math.isfinite(value):
        return "-".rjust(width)
    return format(value, spec)


if __name__ == "__main__":
    raise SystemExit(main(prog="python -m hl3.cli.run"))
