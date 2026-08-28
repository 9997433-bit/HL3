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

import functools
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from hl3.correlate import (
    BSplineInterpolator,
    ICGNParams,
    ICGNResult,
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


@functools.lru_cache(maxsize=32)
def shared_pair(
    shift: tuple[float, float], size: int = 192, noise_sigma: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """Cached :func:`speckle_pair`; generating the texture dominates test time.

    The arrays are handed out read-only because they are shared: a test that
    wants to paint a flat patch into one must copy it first.
    """
    reference, deformed = speckle_pair(shift, size=size, noise_sigma=noise_sigma)
    reference.setflags(write=False)
    deformed.setflags(write=False)
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


# --------------------------------------------------------------------------
# Zero contrast
#
# Every test in this block asks the same question: when a subset carries no
# information, does the solver say so, or does it return a number? The
# threshold under test is relative to the *image's* contrast, which is what
# makes it survive both halves of the trap -- a flat subset that is bright
# enough for its resampling residue to clear an absolute floor, and a real
# texture faint enough to fall below one.
# --------------------------------------------------------------------------


def _solve_points(reference, deformed, points, **kwargs) -> ICGNResult:
    params = ICGNParams(subset_radius=kwargs.pop("subset_radius", 10), **kwargs)
    return icgn_first_order(reference, deformed, np.asarray(points, float), params)


def _status_of(result: ICGNResult, index: int = 0) -> Status:
    return Status(int(result.status[index]))


@pytest.mark.parametrize("level", [0.0, 1.0, 128.0, 255.0, 1.0e6])
def test_flat_pair_is_singular_at_every_grey_level(level):
    """A subset with no contrast has no solution, however bright it is.

    Resampling residue scales with the grey level, so a fixed threshold on
    the subset norm lets a bright flat patch through; measured against the
    image's own contrast, all five levels are equally empty.
    """
    flat = np.full((64, 64), level)
    result = _solve_points(flat, flat, [[32.0, 32.0]])
    assert _status_of(result) is Status.SINGULAR_HESSIAN
    assert result.zncc[0] == -1.0
    assert not result.valid[0]
    assert result.iterations[0] == 0
    assert np.all(result.p == 0.0)


@pytest.mark.parametrize("patch_level", [0.0, 255.0])
def test_flat_patch_inside_texture_fails_only_inside_the_patch(patch_level):
    """Crushed black and blown-out white, the two ways a sensor loses texture.

    Such a patch has almost no grey level of its own, so judged against
    itself the tail the B-spline prefilter leaks in from the surrounding
    speckle looks like full-scale texture.
    """
    reference, deformed = (image.copy() for image in shared_pair((0.37, -0.42), 128))
    reference[44:84, 44:84] = patch_level
    deformed[44:84, 44:84] = patch_level

    result = _solve_points(
        reference, deformed, [[64.0, 64.0], [30.0, 30.0], [98.0, 98.0]]
    )
    assert _status_of(result) is Status.SINGULAR_HESSIAN
    assert np.isnan(result.masked("u")[0])
    assert np.all(result.valid[1:])
    assert np.allclose(result.u[1:], 0.37, atol=5e-3)


def test_flat_target_against_a_textured_reference_is_singular():
    reference, _ = shared_pair((0.0, 0.0), 128)
    result = _solve_points(reference, np.full_like(reference, 200.0), [[64.0, 64.0]])
    assert _status_of(result) is Status.SINGULAR_HESSIAN
    assert result.zncc[0] == -1.0


@pytest.mark.parametrize("gain", [1e-30, 1e-15, 1e-6, 1e6])
def test_faint_or_bright_texture_is_not_mistaken_for_flat(gain):
    """Rescaling the grey range must not change the answer at all.

    This is the other half of the flatness test. ZNSSD is exactly invariant
    to ``g = a f + b``, so any threshold that is not relative would quietly
    break that invariance at one end of the scale or the other.
    """
    reference, deformed = shared_pair((0.37, -0.42), 128)
    params = ICGNParams(subset_radius=10, step=16)
    points = make_grid(reference.shape, params, margin=INTERIOR_MARGIN)

    plain = icgn_first_order(reference, deformed, points, params)
    scaled = icgn_first_order(reference * gain, deformed * gain, points, params)

    assert np.all(plain.valid)
    assert np.array_equal(plain.status, scaled.status)
    assert np.max(np.abs(plain.u - scaled.u)) < 1e-12
    assert np.max(np.abs(plain.v - scaled.v)) < 1e-12


def test_min_contrast_knob_rejects_faint_but_real_texture():
    """The absolute floor is off by default and available when wanted."""
    reference, deformed = shared_pair((0.37, -0.42), 128)
    point = [[64.0, 64.0]]
    assert _solve_points(reference, deformed, point).valid[0]
    strict = _solve_points(reference, deformed, point, min_contrast=100.0)
    assert _status_of(strict) is Status.SINGULAR_HESSIAN


@pytest.mark.parametrize("period", [7.0, 13.0])
def test_one_dimensional_texture_is_reported_singular(period):
    """Stripes fix u and leave v free; the answer must be a status, not a 0.

    The Hessian is rank-deficient in three of its six directions. Without a
    conditioning test the diagonal loading turns that into a confident
    ``v = 0`` carrying ZNCC = 1, which is the most dangerous kind of wrong.
    """
    _, xs = np.mgrid[0:96, 0:96].astype(float)
    reference = 128.0 + 100.0 * np.sin(2.0 * math.pi * xs / period)
    deformed = 128.0 + 100.0 * np.sin(2.0 * math.pi * (xs - 0.4) / period)
    result = _solve_points(reference, deformed, [[48.0, 48.0]])
    assert _status_of(result) is Status.SINGULAR_HESSIAN


def test_two_dimensional_texture_of_the_same_kind_still_solves():
    """Guard the conditioning gate from rejecting subsets that are usable."""
    ys, xs = np.mgrid[0:96, 0:96].astype(float)

    def wave(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return 128.0 + 50.0 * (
            np.sin(2.0 * math.pi * x / 7.0) + np.sin(2.0 * math.pi * y / 9.0)
        )

    result = _solve_points(wave(xs, ys), wave(xs - 0.4, ys - 0.25), [[48.0, 48.0]])
    assert _status_of(result) is Status.CONVERGED
    assert abs(result.u[0] - 0.4) < 2e-3
    assert abs(result.v[0] - 0.25) < 2e-3


@pytest.mark.parametrize("level", [0.0, 128.0, 1.0e6])
def test_integer_search_reports_no_guess_on_a_flat_pair(level):
    flat = np.full((64, 64), level)
    assert integer_search_fftcc(flat, flat, (32.0, 32.0), 10, 5) == (0.0, 0.0, -1.0)


def test_integer_search_reports_no_guess_when_its_window_leaves_the_image():
    reference, deformed = shared_pair((0.4, 0.3), 128)
    assert integer_search_fftcc(reference, deformed, (13.0, 64.0), 10, 12) == (
        0.0,
        0.0,
        -1.0,
    )


def test_failed_integer_search_is_reported_not_silently_zero_seeded():
    """A search that cannot run is not the same as a search that found zero.

    The point sits inside the image, so it used to be solved from a zero
    seed -- correct only while the displacement stays small, which is the
    opposite of the reason a search radius was asked for in the first place.
    """
    reference, deformed = shared_pair((0.4, 0.3), 128)
    result = _solve_points(
        reference, deformed, [[13.0, 64.0], [64.0, 64.0]], search_radius=12
    )
    assert _status_of(result) is Status.NO_INITIAL_GUESS
    assert result.iterations[0] == 0
    assert result.zncc[0] == -1.0
    assert np.isnan(result.masked("u")[0])
    assert result.valid[1]


def test_the_default_grid_margin_never_triggers_a_failed_search():
    """Bounding the cost of the rule above: the default margin already
    includes the search radius, so ``NO_INITIAL_GUESS`` is reserved for
    points a caller placed closer to the border than their own search."""
    reference, deformed = shared_pair((0.4, 0.3), 128)
    params = ICGNParams(subset_radius=10, step=16, search_radius=8)
    points = make_grid(reference.shape, params)
    result = icgn_first_order(reference, deformed, points, params)
    assert not np.any(result.status == int(Status.NO_INITIAL_GUESS))


def test_failed_points_carry_no_covariance():
    reference, deformed = (image.copy() for image in shared_pair((0.37, -0.42), 128))
    reference[44:84, 44:84] = 255.0
    deformed[44:84, 44:84] = 255.0
    result = _solve_points(
        reference,
        deformed,
        [[64.0, 64.0], [30.0, 30.0]],
        compute_covariance=True,
        image_noise_sigma=1.0,
    )
    assert np.all(np.isnan(result.covariance[0]))
    assert np.all(np.isfinite(result.covariance[1]))


# --------------------------------------------------------------------------
# Empty AOI
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "empty", [np.empty((0, 2)), np.zeros((0, 2)), [], np.array([])]
)
def test_empty_aoi_returns_empty_arrays(base_pair, empty):
    """No points is a legitimate AOI, not an error: an entirely masked frame
    or a filtered point list reaches the solver this way."""
    reference, deformed, _ = base_pair
    result = icgn_first_order(reference, deformed, empty, ICGNParams(subset_radius=10))

    assert result.n_points == 0
    for name in ("x", "y", "zncc", "iterations", "status", "u", "v"):
        assert getattr(result, name).shape == (0,)
    assert result.p.shape == (0, 6)
    assert result.iterations.dtype == np.int32
    assert result.valid.shape == (0,)
    assert result.masked("u").shape == (0,)
    assert result.status_counts() == {}
    assert result.covariance is None


def test_empty_aoi_keeps_the_covariance_block_shape(base_pair):
    reference, deformed, _ = base_pair
    params = ICGNParams(
        subset_radius=10, compute_covariance=True, image_noise_sigma=1.0
    )
    result = icgn_first_order(reference, deformed, np.empty((0, 2)), params)
    assert result.covariance is not None
    assert result.covariance.shape == (0, 6, 6)


def test_aoi_entirely_outside_the_image_yields_no_valid_points(base_pair):
    """The AOI is non-empty but nothing in it is computable."""
    reference, deformed, _ = base_pair
    result = _solve_points(
        reference, deformed, [[2.0, 2.0], [3.0, 189.0], [189.0, 3.0]]
    )
    assert result.status_counts() == {Status.OUT_OF_BOUNDS: 3}
    assert np.all(np.isnan(result.masked("u")))
    assert np.all(result.iterations == 0)


def test_make_grid_rejects_a_margin_that_leaves_no_room():
    with pytest.raises(ValueError, match="too small"):
        make_grid((40, 40), ICGNParams(subset_radius=10), margin=20)


def test_make_grid_rejects_a_negative_margin():
    with pytest.raises(ValueError, match="margin"):
        make_grid((40, 40), ICGNParams(subset_radius=10), margin=-1)


def test_status_counts_reports_a_mixed_aoi():
    reference, deformed = (image.copy() for image in shared_pair((0.37, -0.42), 128))
    reference[44:84, 44:84] = 255.0
    deformed[44:84, 44:84] = 255.0
    result = _solve_points(
        reference, deformed, [[2.0, 2.0], [64.0, 64.0], [30.0, 30.0], [98.0, 98.0]]
    )
    assert result.status_counts() == {
        Status.CONVERGED: 2,
        Status.OUT_OF_BOUNDS: 1,
        Status.SINGULAR_HESSIAN: 1,
    }


# --------------------------------------------------------------------------
# Integer and integer-plus-subpixel translation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("shift", [(1.0, 0.0), (0.0, -1.0), (2.0, 3.0), (3.0, -2.0)])
def test_integer_translation_is_recovered_without_a_seed(shift):
    """Whole-pixel shifts carry no interpolation error, so they are the case
    where the solver has nowhere to hide: the answer should be exact."""
    reference, deformed = shared_pair(shift, 160)
    params = ICGNParams(subset_radius=10, step=16)
    points = make_grid(reference.shape, params, margin=45)
    result = icgn_first_order(reference, deformed, points, params)

    assert np.all(result.valid)
    assert np.max(np.abs(result.u - shift[0])) < 1e-4
    assert np.max(np.abs(result.v - shift[1])) < 1e-4
    assert np.max(np.abs(result.p[:, [1, 2, 4, 5]])) < 1e-5
    assert result.zncc.min() > 0.9999


@pytest.mark.parametrize("shift", [(3.25, -2.4), (4.5, 3.75), (-5.1, 2.6)])
def test_integer_plus_subpixel_is_seeded_by_the_integer_search(shift):
    reference, deformed = shared_pair(shift, 176)
    params = ICGNParams(subset_radius=10, step=16, search_radius=8)
    points = make_grid(reference.shape, params, margin=50)
    result = icgn_first_order(reference, deformed, points, params)

    assert np.all(result.valid)
    assert np.max(np.abs(result.u - shift[0])) < 5e-3
    assert np.max(np.abs(result.v - shift[1])) < 5e-3

    u0, v0, zncc = integer_search_fftcc(reference, deformed, (88.0, 88.0), 10, 8)
    assert abs(u0 - shift[0]) <= 0.5
    assert abs(v0 - shift[1]) <= 0.5
    assert zncc > 0.9


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75])
def test_a_whole_pixel_offset_does_not_change_the_subpixel_bias(phase):
    """Interpolation bias is a property of the phase, not of the integer part.

    Same S-curve as ``test_subpixel_phase_sweep``, ridden on top of a 4 px
    offset that the FFT-CC seed has to remove first.
    """
    shift = (4.0 + phase, -3.0)
    reference, deformed = shared_pair(shift, 176)
    params = ICGNParams(subset_radius=10, step=16, search_radius=8)
    points = make_grid(reference.shape, params, margin=50)
    result = icgn_first_order(reference, deformed, points, params)

    assert np.all(result.valid)
    assert abs(float(np.mean(result.u - shift[0]))) < 3e-3
    assert abs(float(np.mean(result.v - shift[1]))) < 3e-3


def test_pull_in_range_of_the_unseeded_solver_is_about_three_pixels():
    """Records where the zero seed stops working, so a regression in the
    seed path shows up as lost coverage rather than as silent inaccuracy."""
    params = ICGNParams(subset_radius=10, step=16)

    def hit_rate(u_true: float) -> float:
        reference, deformed = shared_pair((u_true, 0.0), 160)
        points = make_grid(reference.shape, params, margin=45)
        result = icgn_first_order(reference, deformed, points, params)
        return float(np.mean(result.valid & (np.abs(result.u - u_true) < 1e-3)))

    assert hit_rate(3.0) == 1.0
    assert hit_rate(5.0) < 0.5


def test_initial_guess_may_be_one_row_for_the_whole_grid():
    """A single integer guess broadcast over the AOI: the cheap alternative
    to a per-point search when the motion is known to be uniform."""
    reference, deformed = shared_pair((7.35, -5.6), 192)
    params = ICGNParams(subset_radius=10, step=16)
    points = make_grid(reference.shape, params, margin=60)
    result = icgn_first_order(
        reference, deformed, points, params, initial_guess=np.array([[7.0, -6.0]])
    )
    assert np.all(result.valid)
    assert np.max(np.abs(result.u - 7.35)) < 0.01
    assert np.max(np.abs(result.v + 5.6)) < 0.01


# --------------------------------------------------------------------------
# Remaining status codes
# --------------------------------------------------------------------------


def test_status_enum_covers_the_spec_failure_set():
    """R1-O1 §2.6 and §4.3 list nine outcomes; all nine must be expressible."""
    assert {status.name for status in Status} == {
        "UNCOMPUTED",
        "CONVERGED",
        "LOW_ZNCC",
        "NOT_CONVERGED",
        "OUT_OF_BOUNDS",
        "SINGULAR_HESSIAN",
        "DIVERGED",
        "NO_INITIAL_GUESS",
        "MASKED",
    }
    assert len({int(status) for status in Status}) == 9


def test_low_zncc_marks_the_point_but_keeps_its_solution():
    """Spec §2.6: below the threshold the result is retained and flagged, so
    it can be reported, not deleted."""
    reference, deformed = shared_pair((0.37, -0.42), 128)
    result = _solve_points(
        reference,
        deformed,
        [[64.0, 64.0]],
        zncc_min=1.0,
        compute_covariance=True,
        image_noise_sigma=1.0,
    )
    assert _status_of(result) is Status.LOW_ZNCC
    assert not result.valid[0]
    assert abs(result.u[0] - 0.37) < 5e-3
    assert np.isnan(result.masked("u")[0])
    assert np.all(np.isfinite(result.covariance[0]))


def test_iteration_budget_exhaustion_is_reported():
    reference, deformed = shared_pair((0.37, -0.42), 128)
    result = _solve_points(reference, deformed, [[64.0, 64.0]], max_iter=1)
    assert _status_of(result) is Status.NOT_CONVERGED
    assert result.iterations[0] == 1
    assert not result.valid[0]


def test_max_disp_guard_reports_divergence():
    reference, deformed = shared_pair((0.37, -0.42), 128)
    result = _solve_points(reference, deformed, [[64.0, 64.0]], max_disp=0.05)
    assert _status_of(result) is Status.DIVERGED
    assert not result.valid[0]


def test_masked_blanks_whole_rows_of_p():
    reference, deformed = shared_pair((0.37, -0.42), 128)
    result = _solve_points(reference, deformed, [[2.0, 2.0], [64.0, 64.0]])
    masked = result.masked("p")
    assert np.all(np.isnan(masked[0]))
    assert np.all(np.isfinite(masked[1]))


@pytest.mark.parametrize("field_name", ["covariance", "status", "valid", "nope"])
def test_masked_rejects_fields_it_cannot_blank(base_pair, field_name):
    reference, deformed, _ = base_pair
    result = _solve_points(reference, deformed, [[96.0, 96.0]])
    with pytest.raises(ValueError, match="cannot mask"):
        result.masked(field_name)


# --------------------------------------------------------------------------
# Input validation
#
# The B-spline prefilter is an IIR recursion in both axes, so a single
# non-finite pixel does not stay local: it reaches every coefficient. That is
# why images are checked once at the boundary instead of per point.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_image",
    [
        pytest.param(np.full((24, 24), np.nan), id="nan"),
        pytest.param(np.full((24, 24), np.inf), id="inf"),
        pytest.param(np.zeros(24), id="1d"),
        pytest.param(np.zeros((0, 4)), id="empty"),
    ],
)
@pytest.mark.parametrize(
    "call",
    [
        pytest.param(BSplineInterpolator, id="interpolator"),
        pytest.param(reference_gradients, id="gradients"),
        pytest.param(
            lambda img: integer_search_fftcc(img, img, (10.0, 10.0), 4, 2),
            id="fftcc",
        ),
        pytest.param(
            lambda img: icgn_first_order(
                img, img, np.array([[10.0, 10.0]]), ICGNParams(subset_radius=4)
            ),
            id="solver",
        ),
    ],
)
def test_public_entry_points_validate_their_images(call, bad_image):
    with pytest.raises(ValueError):
        call(bad_image)


def test_one_nan_pixel_stops_the_solver_rather_than_spreading(base_pair):
    reference, deformed, _ = base_pair
    poisoned = reference.copy()
    poisoned[0, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        _solve_points(poisoned, deformed, [[96.0, 96.0]])


def test_solver_rejects_mismatched_image_shapes(base_pair):
    reference, deformed, _ = base_pair
    with pytest.raises(ValueError, match="same shape"):
        icgn_first_order(reference, deformed[:-1], None, ICGNParams())


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"subset_radius": 1}, "subset_radius"),
        ({"step": 0}, "step"),
        ({"max_iter": 0}, "max_iter"),
        ({"search_radius": -1}, "search_radius"),
        ({"conv_tol": 0.0}, "conv_tol"),
        ({"conv_tol": math.nan}, "conv_tol"),
        ({"zncc_min": 1.5}, "zncc_min"),
        ({"max_disp": 0.0}, "max_disp"),
        ({"max_disp": math.inf}, "max_disp"),
        ({"hessian_reg": -1.0}, "hessian_reg"),
        ({"image_noise_sigma": -1.0}, "image_noise_sigma"),
        ({"min_contrast": -1.0}, "min_contrast"),
        ({"max_hessian_cond": 1.0}, "max_hessian_cond"),
    ],
)
def test_params_reject_nonsense(kwargs, match):
    with pytest.raises(ValueError, match=match):
        ICGNParams(**kwargs)


@pytest.mark.parametrize(
    "points",
    [
        pytest.param(np.zeros((3, 3)), id="three-columns"),
        pytest.param(np.array([1.0, 2.0, 3.0]), id="odd-length"),
        pytest.param(np.array([[np.nan, 1.0]]), id="nan"),
        pytest.param(np.array([[1.0, np.inf]]), id="inf"),
    ],
)
def test_solver_rejects_malformed_points(base_pair, points):
    reference, deformed, _ = base_pair
    with pytest.raises(ValueError, match="points"):
        icgn_first_order(reference, deformed, points, ICGNParams(subset_radius=10))


@pytest.mark.parametrize(
    "guess",
    [
        pytest.param(np.zeros((2, 3)), id="wrong-shape"),
        pytest.param(np.array([[np.nan, 0.0]]), id="nan"),
    ],
)
def test_solver_rejects_a_malformed_initial_guess(base_pair, guess):
    reference, deformed, _ = base_pair
    with pytest.raises(ValueError, match="initial_guess"):
        icgn_first_order(
            reference,
            deformed,
            np.array([[96.0, 96.0]]),
            ICGNParams(subset_radius=10),
            initial_guess=guess,
        )


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda img: integer_search_fftcc(img, img, (32.0, 32.0), 0, 2),
            id="radius-zero",
        ),
        pytest.param(
            lambda img: integer_search_fftcc(img, img, (32.0, 32.0), 4, -1),
            id="negative-search",
        ),
        pytest.param(
            lambda img: integer_search_fftcc(img, img, (np.nan, 32.0), 4, 2),
            id="nan-point",
        ),
    ],
)
def test_integer_search_validates_its_arguments(call):
    reference, _ = shared_pair((0.0, 0.0), 64)
    with pytest.raises(ValueError):
        call(reference)


# --------------------------------------------------------------------------
# Interpolator and shape-function algebra
# --------------------------------------------------------------------------


def test_bspline_accepts_a_scalar_and_broadcasts_mixed_shapes(base_pair):
    reference, _, _ = base_pair
    interp = BSplineInterpolator(reference)

    scalar = interp.sample(20.0, 30.0)
    assert scalar.shape == ()
    assert abs(float(scalar) - reference[30, 20]) < 1e-9

    row = interp.sample(np.array([20.0, 21.0]), 30.0)
    assert row.shape == (2,)
    assert np.allclose(row, reference[30, 20:22], atol=1e-9)


@pytest.mark.parametrize("coordinate", [np.nan, np.inf])
def test_bspline_rejects_non_finite_coordinates(base_pair, coordinate):
    """``floor(nan).astype(int64)`` is undefined and folds to some valid
    index, so an unchecked NaN returns a plausible grey value."""
    reference, _, _ = base_pair
    interp = BSplineInterpolator(reference)
    with pytest.raises(ValueError, match="finite"):
        interp.sample(np.array([coordinate]), np.array([10.0]))


def test_gradient_of_a_single_row_image_is_zero_across_the_row():
    fx, fy = reference_gradients(np.arange(6.0).reshape(1, 6))
    assert np.allclose(fx, 1.0)
    assert np.all(fy == 0.0)


@pytest.mark.parametrize(
    "bad", [np.zeros(5), np.zeros(7), np.full(6, np.nan), np.zeros((2, 6))]
)
def test_warp_matrix_rejects_malformed_parameter_vectors(bad):
    with pytest.raises(ValueError):
        warp_matrix(bad)


def test_warp_params_rejects_a_matrix_that_is_not_3x3():
    with pytest.raises(ValueError, match="3x3"):
        warp_params(np.eye(2))


def test_compose_inverse_rejects_a_singular_increment():
    collapsed = np.array([0.0, -1.0, 0.0, 0.0, 0.0, -1.0])
    with pytest.raises(np.linalg.LinAlgError):
        compose_inverse(np.zeros(6), collapsed)


def test_compose_inverse_matches_explicit_matrix_algebra():
    """The closed-form 2x2 inverse must agree with the 3x3 matrix route."""
    rng = np.random.default_rng(11)
    for _ in range(20):
        p = rng.normal(0.0, 0.05, 6)
        dp = rng.normal(0.0, 0.05, 6)
        expected = warp_params(warp_matrix(p) @ np.linalg.inv(warp_matrix(dp)))
        assert np.allclose(compose_inverse(p, dp), expected, atol=1e-12)


def test_compose_inverse_accepts_a_large_but_invertible_increment():
    """The singularity test is relative to the block, so a big step passes."""
    dp = np.array([50.0, 0.4, -0.3, -70.0, 0.2, 0.5])
    composed = compose_inverse(np.zeros(6), dp)
    assert np.all(np.isfinite(composed))
    assert np.allclose(compose_inverse(dp, dp), np.zeros(6), atol=1e-12)
