# SPDX-License-Identifier: Apache-2.0
"""Run 2D-DIC Challenge Sample 14 / 15 through the HL3 2D pipeline.

Sample 14/15 are the image sets used in Reu et al., Exp. Mech. 58:1067 (2018).
Metrics here are an independent Python implementation of a line-cut comparison
against the published commanded-displacement spreadsheet for Sample 15, plus
field-level diagnostics for Sample 14 (no spreadsheet ships in that zip).

This is a Challenge *score attempt*, not a VIC comparison.
"""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np

from hl3.bench.download import EXIT_NOT_RUN, EXIT_OK, EXIT_PROBLEM, cache_root
from hl3.correlate import ICGNParams
from hl3.pipeline import Dic2DConfig, StrainMode, run_sequence, vsg_size_px

__all__ = [
    "load_greyscale",
    "read_sample15_linecut",
    "run_sample14",
    "run_sample15",
    "sample14_dir",
    "sample15_dir",
]


def sample14_dir() -> Path | None:
    root = cache_root() / "2d"
    for candidate in (root / "Sample14", root / "Sample14.zip"):
        if candidate.is_dir():
            return candidate
        if candidate.is_file() and candidate.suffix == ".zip":
            dest = root / "Sample14"
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(candidate) as handle:
                handle.extractall(dest)
            return dest
    return None


def sample15_dir() -> Path | None:
    root = cache_root() / "2d"
    for candidate in (root / "Sample15", root / "Sample15.zip"):
        if candidate.is_dir():
            return candidate
        if candidate.is_file() and candidate.suffix == ".zip":
            dest = root / "Sample15"
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(candidate) as handle:
                handle.extractall(dest)
            return dest
    return None


def load_greyscale(path: Path) -> np.ndarray:
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError(
            "Challenge TIFFs need Pillow; pip install 'hl3[bench]'"
        ) from error
    array = np.asarray(Image.open(path), dtype=np.float64)
    if array.ndim != 2:
        raise ValueError(f"{path} is not a 2-D greyscale image: {array.shape}")
    return array


def _crop_common(images: list[np.ndarray]) -> list[np.ndarray]:
    height = min(image.shape[0] for image in images)
    width = min(image.shape[1] for image in images)
    return [image[:height, :width].copy() for image in images]


def _config(subset: int, step: int, strain: bool, search_radius: int = 4) -> Dic2DConfig:
    radius = subset // 2
    return Dic2DConfig(
        icgn=ICGNParams(
            subset_radius=radius,
            step=step,
            search_radius=search_radius,
        ),
        strain_mode=StrainMode.AUTO if strain else StrainMode.OFF,
    )


def _results_dir() -> Path:
    path = (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "challenge"
        / "results"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(name: str, payload: dict[str, Any]) -> Path:
    target = _results_dir() / name
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return target


def read_sample15_linecut(path: Path) -> dict[str, np.ndarray]:
    """Commanded vertical displacement vs row index, one column per K value."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as handle:
        shared = ET.fromstring(handle.read("xl/sharedStrings.xml"))
        strings: list[str] = []
        for item in shared.findall("m:si", ns):
            texts = list(
                item.iter(
                    "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
                )
            )
            strings.append("".join(node.text or "" for node in texts))
        sheet = ET.fromstring(handle.read("xl/worksheets/sheet1.xml"))
    rows = sheet.findall("m:sheetData/m:row", ns)
    header: list[str] = []
    columns: dict[str, list[float]] = {}
    for index, row in enumerate(rows):
        values: list[str] = []
        for cell in row.findall("m:c", ns):
            kind = cell.get("t")
            node = cell.find("m:v", ns)
            raw = "" if node is None or node.text is None else node.text
            if kind == "s":
                raw = strings[int(raw)]
            values.append(raw)
        if index == 0:
            header = values
            columns = {name: [] for name in header}
            continue
        for name, raw in zip(header, values):
            columns[name].append(float(raw))
    return {name: np.asarray(values, dtype=np.float64) for name, values in columns.items()}


def _center_line_v(run: Any, frame: int = -1) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(y_px, v_px)`` along the grid column nearest image centre."""
    points = run.points
    xs = np.unique(points[:, 0])
    ys = np.unique(points[:, 1])
    x_mid = 0.5 * (xs.min() + xs.max())
    x_col = xs[np.argmin(np.abs(xs - x_mid))]
    mask = np.isclose(points[:, 0], x_col)
    order = np.argsort(points[mask, 1])
    y = points[mask, 1][order]
    field = run.field("v")[frame]
    if field.ndim == 2:
        # lattice (ny, nx) matching unique ys/xs order from make_grid
        ix = int(np.argmin(np.abs(xs - x_col)))
        v = field[:, ix]
        y = ys
    else:
        v = field[mask][order]
    return np.asarray(y, dtype=np.float64), np.asarray(v, dtype=np.float64)


def run_sample14(
    *,
    subset: int = 21,
    step: int = 16,
    which: str = "L1",
) -> dict[str, Any]:
    folder = sample14_dir()
    if folder is None:
        raise FileNotFoundError("Sample 14 is not in the Challenge cache")
    reference = next(folder.rglob("*Reference.tif"))
    deformed = next(
        path
        for path in folder.rglob("*.tif")
        if which.upper() in path.name.upper() and "Reference" not in path.name
    )
    images = _crop_common([load_greyscale(reference), load_greyscale(deformed)])
    config = _config(subset, step, strain=False)
    run = run_sequence(images, config)
    frame = run.frames[-1]
    v = run.field("v")[-1]
    finite = np.isfinite(v)
    payload = {
        "sample": "2d-challenge-1.0-sample14",
        "paper": "https://doi.org/10.1007/s11340-017-0349-0",
        "reference": str(reference),
        "deformed": str(deformed),
        "image_shape": list(images[0].shape),
        "subset_px": subset,
        "step_px": step,
        "l_vsg_px": vsg_size_px(subset, step, config.strain_window),
        "n_points": run.n_points,
        "valid_fraction": frame.valid_fraction,
        "zncc_median": frame.zncc_median,
        "v_rms_px": float(np.sqrt(np.nanmean(v[finite] ** 2))) if np.any(finite) else math.nan,
        "v_peak_abs_px": float(np.nanmax(np.abs(v))) if np.any(finite) else math.nan,
        "filename_amplitude_px": 0.1,
        "ground_truth": "none-in-zip; filename claims Amp0.1 px. Not a published 12-code table entry.",
        "claim": "HL3 Sample 14 diagnostic. Not a VIC comparison.",
    }
    _write_json("sample14.json", payload)
    return payload


def run_sample15(
    *,
    subset: int = 21,
    step: int = 16,
    k: int = 200,
    search_radius: int = 16,
) -> dict[str, Any]:
    folder = sample15_dir()
    if folder is None:
        raise FileNotFoundError("Sample 15 is not in the Challenge cache")
    reference = next(folder.rglob("Reference.tif"))
    deformed = next(folder.rglob(f"P200_K{k}_N2.tif"))
    linecut_path = next(folder.rglob("CommandedDisplacementLineCut.xlsx"))
    images = _crop_common([load_greyscale(reference), load_greyscale(deformed)])
    # Sample 15 commanded |v| reaches ~10 px; a 4 px FFT window silently
    # drops the high-gradient end and makes the line-cut look too good.
    config = _config(subset, step, strain=False, search_radius=search_radius)
    run = run_sequence(images, config)
    frame = run.frames[-1]
    y_grid, v_grid = _center_line_v(run, frame=-1)
    table = read_sample15_linecut(linecut_path)
    key = f"k{k}"
    if key not in table:
        raise KeyError(f"{linecut_path} has no column {key!r}")
    commanded = np.interp(y_grid, table["y"], table[key])
    valid = np.isfinite(v_grid) & np.isfinite(commanded)
    residual = v_grid[valid] - commanded[valid]
    rmse = float(np.sqrt(np.mean(residual ** 2))) if residual.size else math.nan
    bias = float(np.mean(residual)) if residual.size else math.nan
    payload = {
        "sample": "2d-challenge-1.0-sample15",
        "paper": "https://doi.org/10.1007/s11340-017-0349-0",
        "reference": str(reference),
        "deformed": str(deformed),
        "k": k,
        "image_shape": list(images[0].shape),
        "subset_px": subset,
        "step_px": step,
        "search_radius_px": search_radius,
        "l_vsg_px": vsg_size_px(subset, step, 5),
        "n_points": run.n_points,
        "valid_fraction": frame.valid_fraction,
        "zncc_median": frame.zncc_median,
        "linecut_n": int(residual.size),
        "linecut_rmse_px": rmse,
        "linecut_bias_px": bias,
        "commanded_mid_px": float(np.interp(500.0, table["y"], table[key])),
        "measured_mid_px": float(np.interp(500.0, y_grid, np.nan_to_num(v_grid, nan=np.nan))),
        "ground_truth": str(linecut_path.name),
        "claim": (
            "HL3 vs Sample 15 commanded line cut (independent Python). "
            "Not a VIC/MatchID comparison and not the official MATLAB scorer."
        ),
    }
    _write_json(f"sample15_k{k}.json", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hl3.bench 2d")
    parser.add_argument("--sample", choices=("14", "15", "both"), default="15")
    parser.add_argument("--subset", type=int, default=21)
    parser.add_argument("--step", type=int, default=16)
    parser.add_argument("--search-radius", type=int, default=16)
    parser.add_argument("--k", type=int, default=200)
    args = parser.parse_args(argv)
    try:
        payloads = []
        if args.sample in {"14", "both"}:
            payloads.append(run_sample14(subset=args.subset, step=args.step))
        if args.sample in {"15", "both"}:
            payloads.append(
                run_sample15(
                    subset=args.subset,
                    step=args.step,
                    k=args.k,
                    search_radius=args.search_radius,
                )
            )
    except FileNotFoundError as error:
        print(f"error: {error}; run python -m hl3.bench download --fetch 2d", file=__import__("sys").stderr)
        return EXIT_NOT_RUN
    except Exception as error:  # noqa: BLE001
        print(f"error: {type(error).__name__}: {error}", file=__import__("sys").stderr)
        return EXIT_PROBLEM
    for payload in payloads:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return EXIT_OK
