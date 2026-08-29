# SPDX-License-Identifier: Apache-2.0
"""Stereo-DIC Challenge 1.0 runner.

Translate.zip from Sample 1 (experimental, 16 mm / 35 mm rigs) is official
iDICs data. Without a parsed stereo calibration this module only runs a
left-camera 2D diagnostic on two stage steps. That is **not** a Stereo
Challenge score and is not comparable to the <80 µm 3D residual in
Ahmad et al., Exp. Mech. 64:1073 (2024).
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from hl3.bench.challenge2d import load_greyscale
from hl3.bench.download import EXIT_NOT_RUN, EXIT_OK, EXIT_PROBLEM, cache_root
from hl3.correlate import ICGNParams
from hl3.pipeline import Dic2DConfig, StrainMode, run_sequence

__all__ = ["extract_step_pair", "run_left_camera_diagnostic", "translate_zip"]


def translate_zip() -> Path | None:
    path = cache_root() / "stereo" / "sample1" / "Translate.zip"
    return path if path.is_file() else None


def extract_step_pair(
    archive: Path,
    *,
    lens: str = "35-mm",
    reference_step: str = "Step01",
    deformed_step: str = "Step02",
    dest: Path | None = None,
) -> dict[str, Path]:
    """Pull one left/right pair per step out of Translate.zip (≈5 MB each)."""
    dest = dest or (archive.parent / "extract" / lens)
    dest.mkdir(parents=True, exist_ok=True)
    chosen: dict[str, Path] = {}
    with zipfile.ZipFile(archive) as handle:
        names = handle.namelist()
        for role, step in (("reference", reference_step), ("deformed", deformed_step)):
            matches = [
                name
                for name in names
                if f"/{lens}/" in name.replace("\\", "/")
                and step in name
                and name.lower().endswith(".tif")
                and "0000_0" in name
            ]
            if not matches:
                raise FileNotFoundError(
                    f"{archive} has no {lens} {step} left-camera 0000_0 frame"
                )
            name = sorted(matches)[0]
            target = dest / Path(name).name
            if not target.is_file():
                target.write_bytes(handle.read(name))
            chosen[role] = target
            right_name = name.rsplit("_0.tif", 1)[0] + "_1.tif"
            if right_name in handle.namelist():
                right = dest / Path(right_name).name
                if not right.is_file():
                    right.write_bytes(handle.read(right_name))
                chosen[f"{role}_right"] = right
    return chosen


def run_left_camera_diagnostic(
    *,
    subset: int = 21,
    step: int = 40,
    lens: str = "35-mm",
    write: bool = True,
) -> dict[str, Any]:
    archive = translate_zip()
    if archive is None:
        raise FileNotFoundError("Stereo Sample 1 Translate.zip is not in the cache")
    files = extract_step_pair(archive, lens=lens)
    images = [load_greyscale(files["reference"]), load_greyscale(files["deformed"])]
    config = Dic2DConfig(
        icgn=ICGNParams(
            subset_radius=subset // 2,
            step=step,
            search_radius=48,
        ),
        strain_mode=StrainMode.OFF,
    )
    run = run_sequence(images, config)
    frame = run.frames[-1]
    u = run.field("u")[-1]
    v = run.field("v")[-1]
    payload = {
        "sample": "stereo-challenge-1.0-sample1-translate",
        "paper": "https://doi.org/10.1007/s11340-024-01077-7",
        "lens": lens,
        "reference": str(files["reference"]),
        "deformed": str(files["deformed"]),
        "image_shape": list(images[0].shape),
        "subset_px": subset,
        "step_px": step,
        "search_radius_px": 48,
        "n_points": run.n_points,
        "valid_fraction": frame.valid_fraction,
        "zncc_median": frame.zncc_median,
        "u_mean_px": float(np.nanmean(u)),
        "v_mean_px": float(np.nanmean(v)),
        "calibration": "missing",
        "claim": (
            "Left-camera 2D diagnostic on official Translate.zip. "
            "Not a Stereo-DIC Challenge 3D score: no Zhang/Brown ingest, "
            "no triangulation, not comparable to the paper's <80 µm figure."
        ),
    }
    if write:
        out = (
            Path(__file__).resolve().parents[3]
            / "benchmarks"
            / "challenge"
            / "results"
            / "stereo_sample1_left2d.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hl3.bench stereo")
    parser.add_argument("--subset", type=int, default=21)
    parser.add_argument("--step", type=int, default=40)
    parser.add_argument("--lens", default="35-mm")
    args = parser.parse_args(argv)
    try:
        payload = run_left_camera_diagnostic(
            subset=args.subset, step=args.step, lens=args.lens
        )
    except FileNotFoundError as error:
        print(f"error: {error}", file=__import__("sys").stderr)
        return EXIT_NOT_RUN
    except Exception as error:  # noqa: BLE001
        print(f"error: {type(error).__name__}: {error}", file=__import__("sys").stderr)
        return EXIT_PROBLEM
    print(json.dumps(payload, indent=2, sort_keys=True))
    return EXIT_OK
