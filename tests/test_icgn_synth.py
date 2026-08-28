"""Accuracy tests for the CPU reference first-order IC-GN solver.

The synthetic pairs follow the same recipe as
``.agent_workspace/round1/scripts/synth_speckle.py``: random impulses on an
oversampled canvas, Gaussian-blurred in the Fourier domain, translated by the
Fourier shift theorem, then block-averaged down to sensor pixels. Shifting a
band-limited texture in the Fourier domain is analytically exact, so the only
interpolation in the loop is the solver's own -- the generator never uses the
interpolant under test, which is what makes the measured error a genuine
accuracy figure rather than a self-consistency check.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from hl3.correlate import (
    BSplineInterpolator,
    ICGNParams,
    Status,
    compose_inverse,
    icgn_first_order,
    integer_search_fftcc,
    make_grid,
    reference_gradients,
    warp_matrix,
    warp_params,
)

ROUND1_SYNTH = (
    Path(__file__).resolve().parents[1]
    / ".agent_workspace"
    / "round1"
    / "scripts"
    / "synth_speckle.py"
)


# --------------------------------------------------------------------------
# Synthetic speckle generation
# --------------------------------------------------------------------------


def _speckle_spectrum(
    height: int,
    width: int,
    oversample: int,
    speckle_sigma: float,
    density: float,
    seed: int,
) -> np.ndarray:
    """Fourier spectrum of a continuous Gaussian-speckle texture."""
    canvas_h = height * oversample
    canvas_w = width * oversample
    count = max(1, round(density * height * width))

    rng = np.random.default_rng(seed)
    ys = rng.uniform(0.0, canvas_h, count)
    xs = rng.uniform(0.0, canvas_w, count)
    amplitudes = rng.uniform(0.75, 1.25, count)

    y0 = np.floor(ys).astype(np.int64)
    x0 = np.floor(xs).astype(np.int64)
    fy_frac = ys - y0
    fx_frac = xs - x0
    y1 = (y0 + 1) % canvas_h
    x1 = (x0 + 1) % canvas_w

    impulses = np.zeros((canvas_h, canvas_w), dtype=np.float64)
    np.add.at(impulses, (y0, x0), amplitudes * (1 - fy_frac) * (1 - fx_frac))
    np.add.at(impulses, (y0, x1), amplitudes * (1 - fy_frac) * fx_frac)
    np.add.at(impulses, (y1, x0), amplitudes * fy_frac * (1 - fx_frac))
    np.add.at(impulses, (y1, x1), amplitudes * fy_frac * fx_frac)

    fy = np.fft.fftfreq(canvas_h)[:, None]
    fx = np.fft.fftfreq(canvas_w)[None, :]
    sigma_hr = speckle_sigma * oversample
    blur = np.exp(-2.0 * math.pi**2 * sigma_hr**2 * (fx * fx + fy * fy))
    return np.fft.fft2(impulses) * blur


def _render(
    spectrum: np.ndarray,
    height: int,
    width: int,
    oversample: int,
    shift: tuple[float, float],
) -> np.ndarray:
    """Fourier-shift the texture by ``(u, v)`` px and integrate over pixels."""
    u, v = shift
    fy = np.fft.fftfreq(spectrum.shape[0])[:, None]
    fx = np.fft.fftfreq(spectrum.shape[1])[None, :]
    phase = np.exp(
        -2.0j * math.pi * (fx * (u * oversample) + fy * (v * oversample))
    )
    field = np.fft.ifft2(spectrum * phase).real
    return field.reshape(height, oversample, width, oversample).mean(axis=(1, 3))


def speckle_pair(
    shift: tuple[float, float],
    size: int = 192,
    oversample: int = 8,
    speckle_sigma: float = 1.4,
    density: float = 0.08,
    seed: int = 20260828,
    noise_sigma: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Reference/deformed pair for a known rigid translation, 0..255 grey."""
    spectrum = _speckle_spectrum(size, size, oversample, speckle_sigma, density, seed)
    reference = _render(spectrum, size, size, oversample, (0.0, 0.0))
    deformed = _render(spectrum, size, size, oversample, shift)

    low, high = np.percentile(reference, (0.5, 99.5))

    def normalise(image: np.ndarray) -> np.ndarray:
        return 255.0 - 255.0 * np.clip((image - low) / (high - low), 0.0, 1.0)

    reference = normalise(reference)
    deformed = normalise(deformed)

    if noise_sigma > 0.0:
        rng = np.random.default_rng(seed + 1)
        reference = np.clip(reference + rng.normal(0, noise_sigma, reference.shape), 0, 255)
        deformed = np.clip(deformed + rng.normal(0, noise_sigma, deformed.shape), 0, 255)

    return reference, deformed


# The images are periodic on the oversampled canvas, so the Fourier shift wraps
# texture across the border. Points are kept well inside to avoid it.
INTERIOR_MARGIN = 40


@pytest.fixture(scope="module")
def base_pair() -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    shift = (0.37, -0.42)
    reference, deformed = speckle_pair(shift)
    return reference, deformed, shift


def _solve(reference, deformed, params=None, **kwargs):
    params = params or ICGNParams(subset_radius=10, step=8)
    points = make_grid(reference.shape, params, margin=INTERIOR_MARGIN)
    return points, icgn_first_order(reference, deformed, points, params, **kwargs)


# --------------------------------------------------------------------------
# Interpolation / gradient / algebra unit tests
# --------------------------------------------------------------------------


def test_bspline_interpolates_sample_points():
    rng = np.random.default_rng(7)
    image = rng.normal(128.0, 30.0, (48, 53))
    interp = BSplineInterpolator(image)
    ys, xs = np.mgrid[0:48, 0:53]
    recovered = interp.sample(xs.astype(float), ys.astype(float))
    assert np.max(np.abs(recovered - image)) < 1e-9


def test_bspline_reproduces_linear_ramp():
    """Cubic B-splines reproduce low-order polynomials exactly.

    Only away from the border: mirroring a ramp creates a kink at the edge,
    and the prefilter pole (|z| ~ 0.27) carries that a few pixels inwards.
    """
    ys, xs = np.mgrid[0:40, 0:40]
    image = 3.0 * xs - 2.0 * ys + 17.0
    interp = BSplineInterpolator(image.astype(float))
    x = np.array([15.25, 20.75, 24.5])
    y = np.array([18.5, 14.25, 23.125])
    assert np.allclose(interp.sample(x, y), 3.0 * x - 2.0 * y + 17.0, atol=1e-8)


def test_fourth_order_gradient_is_exact_on_cubic():
    ys, xs = np.mgrid[0:24, 0:24].astype(float)
    image = 0.01 * xs**3 - 0.02 * ys**3 + 0.5 * xs * ys
    fx, fy = reference_gradients(image)
    expected_x = 0.03 * xs**2 + 0.5 * ys
    expected_y = -0.06 * ys**2 + 0.5 * xs
    assert np.max(np.abs(fx[2:-2, 2:-2] - expected_x[2:-2, 2:-2])) < 1e-9
    assert np.max(np.abs(fy[2:-2, 2:-2] - expected_y[2:-2, 2:-2])) < 1e-9


def test_warp_roundtrip_and_inverse_composition():
    p = np.array([1.3, 0.01, -0.004, -0.7, 0.002, 0.008])
    assert np.allclose(warp_params(warp_matrix(p)), p)
    # Composing with its own increment must cancel exactly for a first-order
    # (affine) shape function: W(p) . W(p)^-1 = I.
    assert np.allclose(compose_inverse(p, p), np.zeros(6), atol=1e-12)


# --------------------------------------------------------------------------
# Accuracy on synthetic translation
# --------------------------------------------------------------------------


def test_subpixel_translation_recovered(base_pair):
    reference, deformed, (u_true, v_true) = base_pair
    _, result = _solve(reference, deformed)

    assert np.all(result.status == int(Status.CONVERGED))
    assert result.zncc.min() > 0.999

    err_u = result.u - u_true
    err_v = result.v - v_true
    mean_abs = float(np.mean(np.abs(np.concatenate((err_u, err_v)))))

    assert mean_abs < 0.05, f"mean |error| = {mean_abs:.5f} px"
    # The kernel is expected to be far better than the acceptance bar; keep a
    # tight guard so a regression is caught rather than silently absorbed.
    assert mean_abs < 5e-3
    assert abs(float(np.mean(err_u))) < 5e-3
    assert abs(float(np.mean(err_v))) < 5e-3


@pytest.mark.parametrize("u_true", [0.0, 0.1, 0.25, 0.5, 0.75, 0.9])
def test_subpixel_phase_sweep(u_true):
    """Bias must stay small across the whole subpixel phase (the S-curve)."""
    reference, deformed = speckle_pair((u_true, 0.0), size=160)
    params = ICGNParams(subset_radius=10, step=12)
    points = make_grid(reference.shape, params, margin=INTERIOR_MARGIN)
    result = icgn_first_order(reference, deformed, points, params)

    assert np.all(result.status == int(Status.CONVERGED))
    bias_u = float(np.mean(result.u - u_true))
    bias_v = float(np.mean(result.v))
    assert abs(bias_u) < 0.01, f"u={u_true}: bias_u = {bias_u:.5f} px"
    assert abs(bias_v) < 0.01, f"u={u_true}: bias_v = {bias_v:.5f} px"


def test_zero_displacement_is_exact():
    reference, deformed = speckle_pair((0.0, 0.0), size=128)
    params = ICGNParams(subset_radius=10, step=16)
    points = make_grid(reference.shape, params, margin=INTERIOR_MARGIN)
    result = icgn_first_order(reference, deformed, points, params)
    assert np.all(result.status == int(Status.CONVERGED))
    assert np.max(np.abs(result.u)) < 1e-6
    assert np.max(np.abs(result.v)) < 1e-6
    assert np.max(np.abs(result.p[:, [1, 2, 4, 5]])) < 1e-6


def test_first_order_shape_function_recovers_uniform_strain():
    """A pure translation must leave the displacement-gradient terms at zero."""
    reference, deformed = speckle_pair((0.37, -0.42), size=160)
    params = ICGNParams(subset_radius=12, step=16)
    points = make_grid(reference.shape, params, margin=INTERIOR_MARGIN)
    result = icgn_first_order(reference, deformed, points, params)
    gradients = result.p[:, [1, 2, 4, 5]]
    assert np.max(np.abs(gradients)) < 2e-3


def test_invariant_to_gain_and_offset(base_pair):
    """ZNSSD absorbs g = a f + b exactly; the solution must not move."""
    reference, deformed, _ = base_pair
    _, plain = _solve(reference, deformed)
    _, scaled = _solve(reference, np.clip(0.7 * deformed + 30.0, 0, 255))
    assert np.max(np.abs(plain.u - scaled.u)) < 1e-6
    assert np.max(np.abs(plain.v - scaled.v)) < 1e-6


def test_large_displacement_needs_fftcc_seed():
    u_true, v_true = 7.35, -5.6
    reference, deformed = speckle_pair((u_true, v_true), size=192)
    params = ICGNParams(subset_radius=10, step=16, search_radius=12)
    points = make_grid(reference.shape, params, margin=60)

    seeded = icgn_first_order(reference, deformed, points, params)
    assert np.all(seeded.status == int(Status.CONVERGED))
    assert np.max(np.abs(seeded.u - u_true)) < 0.05
    assert np.max(np.abs(seeded.v - v_true)) < 0.05

    # Without a seed the same points must not be silently wrong: they either
    # fail to converge or land on the wrong speckle, never quietly succeed.
    unseeded = icgn_first_order(
        reference, deformed, points, ICGNParams(subset_radius=10, step=16)
    )
    good = unseeded.valid & (np.abs(unseeded.u - u_true) < 0.05)
    assert not np.all(good)


def test_integer_search_hits_exact_shift():
    u_true, v_true = 6.0, -4.0
    reference, deformed = speckle_pair((u_true, v_true), size=160)
    u0, v0, zncc = integer_search_fftcc(reference, deformed, (80.0, 80.0), 10, 12)
    assert (u0, v0) == (u_true, v_true)
    assert zncc > 0.99


def test_noise_degrades_precision_gracefully():
    u_true, v_true = 0.37, -0.42
    reference, deformed = speckle_pair((u_true, v_true), size=192, noise_sigma=2.0)
    params = ICGNParams(subset_radius=15, step=10)
    points = make_grid(reference.shape, params, margin=INTERIOR_MARGIN)
    result = icgn_first_order(reference, deformed, points, params)

    assert np.mean(result.valid) > 0.99
    err_u = result.u[result.valid] - u_true
    err_v = result.v[result.valid] - v_true
    assert float(np.mean(np.abs(np.concatenate((err_u, err_v))))) < 0.05
    assert float(np.std(err_u)) < 0.05


def test_out_of_bounds_is_reported():
    reference, deformed = speckle_pair((0.3, 0.3), size=64)
    params = ICGNParams(subset_radius=10, step=5)
    points = np.array([[2.0, 2.0]])
    result = icgn_first_order(reference, deformed, points, params)
    assert result.status[0] == int(Status.OUT_OF_BOUNDS)


def test_masked_accessor_blanks_failures():
    reference, deformed = speckle_pair((0.3, 0.3), size=64)
    params = ICGNParams(subset_radius=10, step=5)
    points = np.array([[2.0, 2.0], [32.0, 32.0]])
    result = icgn_first_order(reference, deformed, points, params)
    masked = result.masked("u")
    assert np.isnan(masked[0])
    assert np.isfinite(masked[1])


def test_covariance_scales_with_noise():
    reference, deformed = speckle_pair((0.37, -0.42), size=128)
    params = ICGNParams(
        subset_radius=10, step=16, compute_covariance=True, image_noise_sigma=2.0
    )
    points = make_grid(reference.shape, params, margin=INTERIOR_MARGIN)
    result = icgn_first_order(reference, deformed, points, params)
    assert result.covariance is not None
    sigma_u = np.sqrt(result.covariance[:, 0, 0])
    # sigma_u = sqrt(2) sigma_n / sqrt(sum f_x^2): sub-pixel, but not absurd.
    assert np.all(sigma_u > 0.0)
    assert np.all(sigma_u < 0.05)


@pytest.mark.skipif(
    not ROUND1_SYNTH.exists(), reason="round1 synth_speckle.py not present"
)
def test_matches_round1_generator(tmp_path):
    """Cross-check against the Round 1 benchmark generator, unmodified."""
    spec = importlib.util.spec_from_file_location("synth_speckle", ROUND1_SYNTH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    args = module.build_parser().parse_args(
        [
            "--output",
            str(tmp_path),
            "--width",
            "192",
            "--height",
            "192",
            "--tx",
            "0.37",
            "--ty",
            "-0.42",
            "--oversample",
            "8",
        ]
    )
    module.validate(args)
    raw_ref, raw_def, _ = module.render_pair(args)
    reference, deformed, _ = module.normalize_pair(raw_ref, raw_def, args.polarity)

    params = ICGNParams(subset_radius=10, step=8)
    points = make_grid(reference.shape, params, margin=INTERIOR_MARGIN)
    result = icgn_first_order(
        reference.astype(np.float64), deformed.astype(np.float64), points, params
    )

    assert np.all(result.status == int(Status.CONVERGED))
    errors = np.concatenate((result.u - args.tx, result.v - args.ty))
    assert float(np.mean(np.abs(errors))) < 0.05
