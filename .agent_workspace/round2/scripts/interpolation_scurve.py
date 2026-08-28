#!/usr/bin/env python3
"""Measure one-pixel-period interpolation bias without requiring an ICGN kernel.

The benchmark creates exact, continuously shifted sinusoidal images and
oversampled Gaussian-speckle images.  A subset ZNSSD translation search then
warps the sampled deformed image with the interpolation method under test.
Generation never uses either tested interpolator.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class BenchmarkConfig:
    size: int
    subset: int
    poi_step: int
    oversample: int
    margin: int
    speckle_sigma: float
    density: float
    seed: int
    search_step: float
    search_half_width: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=96, help="square image size")
    parser.add_argument("--subset", type=int, default=31, help="odd subset width")
    parser.add_argument("--poi-step", type=int, default=16)
    parser.add_argument("--oversample", type=int, default=8)
    parser.add_argument("--margin", type=int, default=16)
    parser.add_argument("--speckle-sigma", type=float, default=1.25)
    parser.add_argument("--density", type=float, default=0.08)
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--phase-step", type=float, default=0.05)
    parser.add_argument("--search-step", type=float, default=0.01)
    parser.add_argument("--search-half-width", type=float, default=0.60)
    parser.add_argument(
        "--patterns",
        nargs="+",
        choices=("sinusoid", "speckle"),
        default=("sinusoid", "speckle"),
    )
    parser.add_argument(
        "--interpolators",
        nargs="+",
        choices=("bilinear", "keys_bicubic"),
        default=("bilinear", "keys_bicubic"),
    )
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-csv", type=Path)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.size < 32:
        raise ValueError("size must be at least 32")
    if args.subset < 7 or args.subset % 2 != 1 or args.subset >= args.size:
        raise ValueError("subset must be odd, at least 7, and smaller than size")
    for name in ("poi_step", "oversample", "margin"):
        if getattr(args, name) <= 0:
            raise ValueError(f"{name.replace('_', '-')} must be positive")
    for name in (
        "speckle_sigma",
        "density",
        "phase_step",
        "search_step",
        "search_half_width",
    ):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name.replace('_', '-')} must be finite and positive")
    if args.phase_step >= 1.0:
        raise ValueError("phase-step must be less than one pixel")
    if args.search_half_width <= args.phase_step:
        raise ValueError("search-half-width is too narrow for the phase sweep")


def normalize_from_reference(
    reference: np.ndarray, deformed: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    low, high = np.percentile(reference, (0.5, 99.5))
    if not high > low:
        raise RuntimeError("synthetic pattern has zero dynamic range")

    def normalize(image: np.ndarray) -> np.ndarray:
        scaled = 255.0 * np.clip((image - low) / (high - low), 0.0, 1.0)
        return scaled.astype(np.float64)

    return normalize(reference), normalize(deformed)


def sinusoid_pair(size: int, shift: float) -> tuple[np.ndarray, np.ndarray]:
    """Return pixel-area-integrated samples of a continuous Fourier texture."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float64)
    components = (
        (0.071, 0.037, 1.00, 0.20),
        (0.113, -0.061, 0.72, 1.30),
        (0.183, 0.049, 0.51, 2.10),
        (0.267, -0.029, 0.34, 0.70),
    )

    def render(x_shift: float) -> np.ndarray:
        result = np.zeros((size, size), dtype=np.float64)
        for fx, fy, amplitude, phase in components:
            # np.sinc(f) is the exact unit-pixel box-integration attenuation.
            integrated_amplitude = amplitude * np.sinc(fx) * np.sinc(fy)
            angle = 2.0 * math.pi * (fx * (x - x_shift) + fy * y) + phase
            result += integrated_amplitude * np.cos(angle)
        return result

    return normalize_from_reference(render(0.0), render(shift))


class SpeckleRenderer:
    """Reusable oversampled continuous-speckle renderer for a phase sweep."""

    def __init__(
        self,
        size: int,
        oversample: int,
        margin: int,
        sigma: float,
        density: float,
        seed: int,
    ) -> None:
        self.size = size
        self.oversample = oversample
        self.margin = margin
        canvas_size = (size + 2 * margin) * oversample
        physical_area = (canvas_size / oversample) ** 2
        count = max(1, round(density * physical_area))
        rng = np.random.default_rng(seed)

        ys = rng.uniform(0.0, canvas_size, count)
        xs = rng.uniform(0.0, canvas_size, count)
        amplitudes = rng.uniform(0.75, 1.25, count)
        y0 = np.floor(ys).astype(np.int64)
        x0 = np.floor(xs).astype(np.int64)
        dy = ys - y0
        dx = xs - x0
        y1 = (y0 + 1) % canvas_size
        x1 = (x0 + 1) % canvas_size

        impulses = np.zeros((canvas_size, canvas_size), dtype=np.float64)
        np.add.at(impulses, (y0, x0), amplitudes * (1.0 - dy) * (1.0 - dx))
        np.add.at(impulses, (y0, x1), amplitudes * (1.0 - dy) * dx)
        np.add.at(impulses, (y1, x0), amplitudes * dy * (1.0 - dx))
        np.add.at(impulses, (y1, x1), amplitudes * dy * dx)

        self.fy = np.fft.fftfreq(canvas_size)[:, None]
        self.fx = np.fft.fftfreq(canvas_size)[None, :]
        sigma_hr = sigma * oversample
        gaussian = np.exp(
            -2.0 * math.pi**2 * sigma_hr**2 * (self.fx**2 + self.fy**2)
        )
        self.spectrum = np.fft.fft2(impulses) * gaussian
        self.reference_raw = self._raw_frame(0.0)
        self.low, self.high = np.percentile(self.reference_raw, (0.5, 99.5))
        if not self.high > self.low:
            raise RuntimeError("synthetic speckle has zero dynamic range")

    def _raw_frame(self, shift: float) -> np.ndarray:
        phase = np.exp(
            -2.0j * math.pi * self.fx * (shift * self.oversample)
        )
        field = np.fft.ifft2(self.spectrum * phase).real
        first = self.margin * self.oversample
        last = first + self.size * self.oversample
        cropped = field[first:last, first:last]
        return cropped.reshape(
            self.size,
            self.oversample,
            self.size,
            self.oversample,
        ).mean(axis=(1, 3))

    def frame(self, shift: float) -> np.ndarray:
        raw = self.reference_raw if shift == 0.0 else self._raw_frame(shift)
        return (
            255.0 * np.clip((raw - self.low) / (self.high - self.low), 0.0, 1.0)
        ).astype(np.float64)

    def pair(self, shift: float) -> tuple[np.ndarray, np.ndarray]:
        return self.frame(0.0), self.frame(shift)


def keys_kernel(distance: np.ndarray, a: float = -0.5) -> np.ndarray:
    absolute = np.abs(distance)
    result = np.zeros_like(absolute, dtype=np.float64)
    inner = absolute <= 1.0
    outer = (absolute > 1.0) & (absolute < 2.0)
    t = absolute[inner]
    result[inner] = (a + 2.0) * t**3 - (a + 3.0) * t**2 + 1.0
    t = absolute[outer]
    result[outer] = a * t**3 - 5.0 * a * t**2 + 8.0 * a * t - 4.0 * a
    return result


def sample_horizontal(image: np.ndarray, shift: float, method: str) -> np.ndarray:
    """Sample D(x + shift, y); clamping is unused by guarded POI subsets."""
    width = image.shape[1]
    coordinates = np.arange(width, dtype=np.float64) + shift
    base = np.floor(coordinates).astype(np.int64)
    fraction = coordinates - base

    if method == "bilinear":
        left = np.clip(base, 0, width - 1)
        right = np.clip(base + 1, 0, width - 1)
        return image[:, left] * (1.0 - fraction) + image[:, right] * fraction

    if method == "keys_bicubic":
        result = np.zeros_like(image, dtype=np.float64)
        for offset in (-1, 0, 1, 2):
            index = base + offset
            weight = keys_kernel(coordinates - index)
            result += image[:, np.clip(index, 0, width - 1)] * weight
        return result

    raise ValueError(f"unknown interpolation method: {method}")


def point_centers(size: int, subset: int, step: int) -> list[tuple[int, int]]:
    half = subset // 2
    # Three extra pixels protect bicubic support and the +/- 0.6 px search.
    first = half + 3
    last = size - half - 4
    coordinates = list(range(first, last + 1, step))
    if len(coordinates) < 2:
        raise ValueError("configuration leaves fewer than two POIs per axis")
    return [(y, x) for y in coordinates for x in coordinates]


def parabolic_minimum(
    candidates: np.ndarray, objective: np.ndarray
) -> tuple[float, bool]:
    index = int(np.argmin(objective))
    if index == 0 or index == len(candidates) - 1:
        return float("nan"), False
    left, center, right = objective[index - 1 : index + 2]
    denominator = left - 2.0 * center + right
    delta = 0.0
    if denominator > np.finfo(np.float64).eps:
        delta = 0.5 * (left - right) / denominator
        delta = float(np.clip(delta, -1.0, 1.0))
    spacing = candidates[index + 1] - candidates[index]
    return float(candidates[index] + delta * spacing), True


def estimate_subsets(
    reference: np.ndarray,
    deformed: np.ndarray,
    candidates: np.ndarray,
    method: str,
    centers: list[tuple[int, int]],
    subset: int,
) -> np.ndarray:
    warped = np.stack(
        [sample_horizontal(deformed, float(candidate), method) for candidate in candidates]
    )
    half = subset // 2
    estimates: list[float] = []
    for y, x in centers:
        reference_patch = reference[
            y - half : y + half + 1,
            x - half : x + half + 1,
        ].reshape(-1)
        reference_zero_mean = reference_patch - reference_patch.mean()
        reference_norm = np.linalg.norm(reference_zero_mean)

        candidate_patches = warped[
            :,
            y - half : y + half + 1,
            x - half : x + half + 1,
        ].reshape(len(candidates), -1)
        candidate_zero_mean = candidate_patches - candidate_patches.mean(
            axis=1, keepdims=True
        )
        denominator = reference_norm * np.linalg.norm(
            candidate_zero_mean, axis=1
        )
        correlation = np.divide(
            candidate_zero_mean @ reference_zero_mean,
            denominator,
            out=np.full(len(candidates), -1.0, dtype=np.float64),
            where=denominator > 0.0,
        )
        estimate, valid = parabolic_minimum(candidates, 1.0 - correlation)
        estimates.append(estimate if valid else float("nan"))
    return np.asarray(estimates, dtype=np.float64)


def finite_metrics(errors: np.ndarray) -> dict[str, float | int]:
    finite = errors[np.isfinite(errors)]
    if len(finite) == 0:
        return {
            "count": 0,
            "bias_px": float("nan"),
            "std_px": float("nan"),
            "rmse_px": float("nan"),
        }
    return {
        "count": int(len(finite)),
        "bias_px": float(np.mean(finite)),
        "std_px": float(np.std(finite, ddof=1)) if len(finite) > 1 else 0.0,
        "rmse_px": float(np.sqrt(np.mean(finite**2))),
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, object]:
    config = BenchmarkConfig(
        size=args.size,
        subset=args.subset,
        poi_step=args.poi_step,
        oversample=args.oversample,
        margin=args.margin,
        speckle_sigma=args.speckle_sigma,
        density=args.density,
        seed=args.seed,
        search_step=args.search_step,
        search_half_width=args.search_half_width,
    )
    phases = np.arange(0.0, 1.0 - args.phase_step / 2.0, args.phase_step)
    centers = point_centers(args.size, args.subset, args.poi_step)
    speckle_renderer = None
    if "speckle" in args.patterns:
        speckle_renderer = SpeckleRenderer(
            args.size,
            args.oversample,
            args.margin,
            args.speckle_sigma,
            args.density,
            args.seed,
        )

    pair_factories: dict[
        str, Callable[[float], tuple[np.ndarray, np.ndarray]]
    ] = {"sinusoid": lambda shift: sinusoid_pair(args.size, shift)}
    if speckle_renderer is not None:
        pair_factories["speckle"] = speckle_renderer.pair

    per_phase: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for pattern in args.patterns:
        for method in args.interpolators:
            combination_errors: list[np.ndarray] = []
            phase_biases: list[float] = []
            valid_count = 0
            requested_count = 0
            for phase in phases:
                reference, deformed = pair_factories[pattern](float(phase))
                integer_initial = math.floor(float(phase) + 0.5)
                radius_steps = round(args.search_half_width / args.search_step)
                candidates = integer_initial + np.arange(
                    -radius_steps, radius_steps + 1, dtype=np.float64
                ) * args.search_step
                estimates = estimate_subsets(
                    reference,
                    deformed,
                    candidates,
                    method,
                    centers,
                    args.subset,
                )
                errors = estimates - phase
                metrics = finite_metrics(errors)
                metrics.update(
                    {
                        "pattern": pattern,
                        "interpolator": method,
                        "phase_px": float(phase),
                        "requested": int(len(errors)),
                    }
                )
                per_phase.append(metrics)
                combination_errors.append(errors)
                phase_biases.append(float(metrics["bias_px"]))
                valid_count += int(metrics["count"])
                requested_count += len(errors)

            all_errors = np.concatenate(combination_errors)
            aggregate = finite_metrics(all_errors)
            bias_array = np.asarray(phase_biases, dtype=np.float64)
            harmonic = 2.0 / len(phases) * abs(
                np.sum(bias_array * np.exp(-2.0j * math.pi * phases))
            )
            aggregate.update(
                {
                    "pattern": pattern,
                    "interpolator": method,
                    "phase_bias_peak_to_peak_px": float(
                        np.max(bias_array) - np.min(bias_array)
                    ),
                    "phase_bias_first_harmonic_amplitude_px": float(harmonic),
                    "max_abs_phase_bias_px": float(np.max(np.abs(bias_array))),
                    "valid_rate": valid_count / requested_count,
                }
            )
            summaries.append(aggregate)

    repo_root = Path(__file__).resolve().parents[3]
    icgn_path = repo_root / "src" / "hl3" / "correlate" / "icgn.py"
    return {
        "schema": "hl3.round2.interpolation-scurve.v1",
        "method": {
            "generator": (
                "exact box-integrated continuous sinusoids and oversampled "
                "Fourier-shifted Gaussian speckle"
            ),
            "estimator": (
                "local subset ZNSSD scalar translation search; nearest-integer "
                "coarse initialization; three-point parabolic refinement"
            ),
            "tested_motion": "horizontal translation only",
            "boundary": "clamped sampler, with all measured subsets guard-excluded",
            "icgn_available": icgn_path.exists(),
            "icgn_used": False,
        },
        "config": {
            **config.__dict__,
            "phase_step": args.phase_step,
            "phases_px": phases.tolist(),
            "patterns": list(args.patterns),
            "interpolators": list(args.interpolators),
            "poi_count": len(centers),
        },
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "summary": summaries,
        "per_phase": per_phase,
    }


def write_outputs(
    result: dict[str, object], output_json: Path | None, output_csv: Path | None
) -> None:
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        rows = result["per_phase"]
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("benchmark produced no per-phase rows")
        with output_csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main() -> None:
    args = parse_args()
    validate_args(args)
    result = run_benchmark(args)
    write_outputs(result, args.output_json, args.output_csv)
    print(json.dumps(result["summary"], indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
