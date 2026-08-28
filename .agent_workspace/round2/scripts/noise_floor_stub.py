#!/usr/bin/env python3
"""Measure a synthetic static-pair noise floor without requiring ICGN.

Each trial observes the same clean speckle image twice with independent
Gaussian read noise.  The script reports intensity-difference noise and a
clearly labelled linearized subset-translation displacement stub.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np

from interpolation_scurve import SpeckleRenderer, point_centers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=96)
    parser.add_argument("--subset", type=int, default=31)
    parser.add_argument("--poi-step", type=int, default=16)
    parser.add_argument("--oversample", type=int, default=8)
    parser.add_argument("--margin", type=int, default=16)
    parser.add_argument("--speckle-sigma", type=float, default=1.25)
    parser.add_argument("--density", type=float, default=0.08)
    parser.add_argument("--noise-sigmas", type=float, nargs="+", default=(1.0,))
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--output-json", type=Path)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.size < 32:
        raise ValueError("size must be at least 32")
    if args.subset < 7 or args.subset % 2 != 1 or args.subset >= args.size:
        raise ValueError("subset must be odd, at least 7, and smaller than size")
    for name in ("poi_step", "oversample", "margin", "trials"):
        if getattr(args, name) <= 0:
            raise ValueError(f"{name.replace('_', '-')} must be positive")
    for name in ("speckle_sigma", "density"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name.replace('_', '-')} must be finite and positive")
    if not args.noise_sigmas:
        raise ValueError("at least one noise sigma is required")
    if any(not math.isfinite(value) or value < 0.0 for value in args.noise_sigmas):
        raise ValueError("noise sigmas must be finite and non-negative")


def local_linearized_translation(
    first: np.ndarray,
    second: np.ndarray,
    centers: list[tuple[int, int]],
    subset: int,
) -> tuple[np.ndarray, np.ndarray]:
    """One Gauss-Newton translation step around the known zero-shift state."""
    average = 0.5 * (first + second)
    gradient_y, gradient_x = np.gradient(average)
    difference = second - first
    half = subset // 2
    estimates: list[np.ndarray] = []
    conditions: list[float] = []

    for y, x in centers:
        region = np.s_[
            y - half : y + half + 1,
            x - half : x + half + 1,
        ]
        design = np.column_stack(
            (gradient_x[region].reshape(-1), gradient_y[region].reshape(-1))
        )
        residual = difference[region].reshape(-1)
        residual = residual - residual.mean()
        hessian = design.T @ design
        conditions.append(float(np.linalg.cond(hessian)))
        # D(x)=R(x-u), so D-R=-grad(R).[u,v] at first order.
        estimate, *_ = np.linalg.lstsq(design, -residual, rcond=None)
        estimates.append(estimate)
    return np.asarray(estimates), np.asarray(conditions)


def component_metrics(values: np.ndarray) -> dict[str, float]:
    flattened = values.reshape(-1)
    pooled_std = float(np.std(flattened, ddof=1))
    spatial_std = np.std(values, axis=1, ddof=1)
    temporal_std = np.std(values, axis=0, ddof=1)
    return {
        "bias_px": float(np.mean(flattened)),
        "pooled_std_px": pooled_std,
        "spatial_std_mean_px": float(np.mean(spatial_std)),
        "temporal_std_mean_px": float(np.mean(temporal_std)),
        "rmse_px": float(np.sqrt(np.mean(flattened**2))),
        "three_sigma_px": 3.0 * pooled_std,
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, object]:
    renderer = SpeckleRenderer(
        args.size,
        args.oversample,
        args.margin,
        args.speckle_sigma,
        args.density,
        args.seed,
    )
    clean = renderer.frame(0.0)
    centers = point_centers(args.size, args.subset, args.poi_step)
    sigma_seed_sequences = np.random.SeedSequence(args.seed).spawn(
        len(args.noise_sigmas)
    )
    results: list[dict[str, object]] = []

    for sigma, sigma_seed in zip(args.noise_sigmas, sigma_seed_sequences):
        trial_seeds = sigma_seed.spawn(args.trials * 2)
        trial_estimates: list[np.ndarray] = []
        condition_numbers: list[np.ndarray] = []
        difference_samples: list[np.ndarray] = []
        noise_samples: list[np.ndarray] = []
        saturated_count = 0
        sample_count = 0

        for trial in range(args.trials):
            first_noise = np.random.default_rng(
                trial_seeds[2 * trial]
            ).normal(0.0, sigma, clean.shape)
            second_noise = np.random.default_rng(
                trial_seeds[2 * trial + 1]
            ).normal(0.0, sigma, clean.shape)
            first_unclipped = clean + first_noise
            second_unclipped = clean + second_noise
            saturated_count += int(
                np.count_nonzero(
                    (first_unclipped < 0.0)
                    | (first_unclipped > 255.0)
                    | (second_unclipped < 0.0)
                    | (second_unclipped > 255.0)
                )
            )
            sample_count += 2 * clean.size
            first = np.clip(first_unclipped, 0.0, 255.0)
            second = np.clip(second_unclipped, 0.0, 255.0)
            estimates, conditions = local_linearized_translation(
                first, second, centers, args.subset
            )
            trial_estimates.append(estimates)
            condition_numbers.append(conditions)
            difference_samples.append((second - first).reshape(-1))
            noise_samples.extend(
                ((first - clean).reshape(-1), (second - clean).reshape(-1))
            )

        estimates_array = np.stack(trial_estimates)
        difference_array = np.concatenate(difference_samples)
        noise_array = np.concatenate(noise_samples)
        expected_difference_std = math.sqrt(2.0) * sigma
        measured_difference_std = float(np.std(difference_array, ddof=1))
        result: dict[str, object] = {
            "input_noise_sigma_gray": float(sigma),
            "single_observation_noise_std_gray": float(
                np.std(noise_array, ddof=1)
            ),
            "difference_std_gray": measured_difference_std,
            "expected_unclipped_difference_std_gray": expected_difference_std,
            "difference_std_relative_error": (
                (measured_difference_std - expected_difference_std)
                / expected_difference_std
                if expected_difference_std > 0.0
                else 0.0
            ),
            "saturated_sample_fraction": saturated_count / sample_count,
            "u": component_metrics(estimates_array[:, :, 0]),
            "v": component_metrics(estimates_array[:, :, 1]),
            "median_normal_matrix_condition": float(
                np.median(np.concatenate(condition_numbers))
            ),
        }
        results.append(result)

    return {
        "schema": "hl3.round2.noise-floor-stub.v1",
        "method": {
            "images": (
                "two independent noisy observations per trial of one identical "
                "oversampled synthetic speckle image"
            ),
            "noise": "independent additive Gaussian gray-count noise, then [0,255] clip",
            "displacement_estimator": (
                "one linearized subset-translation least-squares step at known "
                "zero displacement; diagnostic stub, not production ICGN"
            ),
            "true_displacement_px": [0.0, 0.0],
        },
        "config": {
            "size": args.size,
            "subset": args.subset,
            "poi_step": args.poi_step,
            "poi_count": len(centers),
            "oversample": args.oversample,
            "margin": args.margin,
            "speckle_sigma": args.speckle_sigma,
            "density": args.density,
            "noise_sigmas": list(args.noise_sigmas),
            "trials": args.trials,
            "seed": args.seed,
        },
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "results": results,
    }


def main() -> None:
    args = parse_args()
    validate_args(args)
    result = run_benchmark(args)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result["results"], indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
