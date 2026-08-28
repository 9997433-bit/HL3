"""Accuracy and algebra tests for the second-order (12-parameter) IC-GN solver.

The first-order suite in ``tests/test_icgn_synth.py`` builds its pairs by
Fourier-shifting a speckle field, which is analytically exact but can only
express a rigid translation. A second-order shape function has to be measured
against a *curved* displacement field, so the texture here is a closed-form
band-limited function -- a finite sum of cosines with a Gaussian amplitude
envelope, i.e. a truncated Fourier series of a Gaussian-correlated random
field -- that can be evaluated at any real coordinate.

That closed form is what makes the ground truth exact. Writing the pair as

    target(x, y)    = h(x, y)
    reference(x, y) = h(x + u(x, y), y + v(x, y))

means ``reference(x, y) = target(W(x, y))`` identically, so ``W`` *is* the warp
the solver is asked to find, to the last bit, with no resampling anywhere in
the generator. Choosing ``u`` and ``v`` to be quadratic polynomials then makes
the second-order shape function exact and the first-order one deficient by a
known amount, which is exactly the contrast these tests need to measure.

The images are point samples of a band-limited function rather than
pixel-area integrals. That is deliberate: it is the sampling model the
bicubic B-spline interpolator is built for, so interpolation error stays far
below the shape-function model error and the comparison isolates the thing
under test. Pixel-integration bias is the first-order suite's job.

CPU / NumPy only.
"""

from __future__ import annotations

import functools
import math

import numpy as np
import pytest

from hl3.correlate import (
    ICGNParams,
    Status,
    compose_inverse,
    compose_inverse_second_order,
    first_to_second_order,
    icgn,
    icgn_first_order,
    icgn_second_order,
    make_grid,
    second_to_first_order,
    shape_param_count,
    shape_param_labels,
    warp_matrix_second_order,
    warp_params_second_order,
)

# Columns of the 12-parameter vector, for readable indexing.
U, UX, UY, UXX, UXY, UYY, V, VX, VY, VXX, VXY, VYY = range(12)
CURVATURE = [UXX, UXY, UYY, VXX, VXY, VYY]
GRADIENT = [UX, UY, VX, VY]


# --------------------------------------------------------------------------
# Analytic band-limited texture and exactly-warped image pairs
# --------------------------------------------------------------------------


def _texture(seed: int, n_waves: int, speckle_sigma: float, f_max: float):
    """A closed-form band-limited texture ``h(x, y)``, evaluable anywhere.

    Frequencies fill a disc of radius ``f_max`` cycles/px -- comfortably below
    Nyquist even after the warp stretches them -- and amplitudes follow the
    Gaussian envelope of a speckle of standard deviation ``speckle_sigma``, so
    the result has the spectrum of a speckle pattern while remaining an
    ordinary function of two real variables.
    """
    rng = np.random.default_rng(seed)
    radius = f_max * np.sqrt(rng.uniform(0.02, 1.0, n_waves))
    angle = rng.uniform(0.0, 2.0 * math.pi, n_waves)
    fx = radius * np.cos(angle)
    fy = radius * np.sin(angle)
    envelope = np.exp(-2.0 * math.pi**2 * speckle_sigma**2 * (fx * fx + fy * fy))
    amplitude = envelope * rng.uniform(0.5, 1.5, n_waves)
    phase = rng.uniform(0.0, 2.0 * math.pi, n_waves)

    def h(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        out = np.zeros(np.broadcast(x, y).shape, dtype=np.float64)
        for k in range(n_waves):
            out += amplitude[k] * np.cos(
                2.0 * math.pi * (fx[k] * x + fy[k] * y) + phase[k]
            )
        return out

    return h


class QuadraticField:
    """A displacement field that is quadratic in coordinates about a centre.

    ``coeff_u = (u0, a1, a2, a3, a4, a5)`` means

        u(x, y) = u0 + a1 X + a2 Y + a3 X^2 + a4 X Y + a5 Y^2,  X = x - cx

    and likewise for ``v``. Expanding about a POI turns those six numbers into
    the six ``u`` shape-function parameters at that POI, which is what
    :meth:`params_at` returns -- the exact answer the solver should produce.
    """

    def __init__(self, coeff_u, coeff_v, centre) -> None:
        self.coeff_u = tuple(float(c) for c in coeff_u)
        self.coeff_v = tuple(float(c) for c in coeff_v)
        self.centre = (float(centre[0]), float(centre[1]))

    def displacement(self, x: np.ndarray, y: np.ndarray):
        big_x = np.asarray(x, dtype=np.float64) - self.centre[0]
        big_y = np.asarray(y, dtype=np.float64) - self.centre[1]

        def evaluate(c):
            return (
                c[0]
                + c[1] * big_x
                + c[2] * big_y
                + c[3] * big_x * big_x
                + c[4] * big_x * big_y
                + c[5] * big_y * big_y
            )

        return evaluate(self.coeff_u), evaluate(self.coeff_v)

    def params_at(self, points: np.ndarray) -> np.ndarray:
        """``(n, 12)`` ground-truth warp parameters for each POI."""
        points = np.atleast_2d(np.asarray(points, dtype=np.float64))
        big_x = points[:, 0] - self.centre[0]
        big_y = points[:, 1] - self.centre[1]
        ones = np.ones_like(big_x)
        u, v = self.displacement(points[:, 0], points[:, 1])

        def block(c, constant):
            return (
                constant,
                c[1] + 2.0 * c[3] * big_x + c[4] * big_y,
                c[2] + c[4] * big_x + 2.0 * c[5] * big_y,
                2.0 * c[3] * ones,
                c[4] * ones,
                2.0 * c[5] * ones,
            )

        return np.column_stack(block(self.coeff_u, u) + block(self.coeff_v, v))


def warped_pair(
    field: QuadraticField,
    size: int,
    seed: int = 11,
    n_waves: int = 300,
    speckle_sigma: float = 1.4,
    f_max: float = 0.30,
    noise_sigma: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Reference/target images realising ``field`` exactly, 0..255 grey.

    Both images are rescaled by the *same* affine grey map, taken from the
    joint min/max so that nothing is clipped: clipping is a non-linearity and
    would break the ``reference(x, y) = target(W(x, y))`` identity that makes
    the ground truth exact.
    """
    h = _texture(seed, n_waves, speckle_sigma, f_max)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    u, v = field.displacement(xs, ys)

    target = h(xs, ys)
    reference = h(xs + u, ys + v)

    low = min(float(target.min()), float(reference.min()))
    high = max(float(target.max()), float(reference.max()))
    gain = 255.0 / (high - low)
    reference = gain * (reference - low)
    target = gain * (target - low)

    if noise_sigma > 0.0:
        rng = np.random.default_rng(seed + 977)
        reference = reference + rng.normal(0.0, noise_sigma, reference.shape)
        target = target + rng.normal(0.0, noise_sigma, target.shape)

    return reference, target


def centre_of(size: int) -> tuple[float, float]:
    return ((size - 1) / 2.0, (size - 1) / 2.0)


@functools.lru_cache(maxsize=16)
def _cached_case(
    name: str, size: int, noise_sigma: float
) -> tuple[np.ndarray, np.ndarray, QuadraticField]:
    field = QuadraticField(*_FIELDS[name], centre=centre_of(size))
    reference, target = warped_pair(field, size, noise_sigma=noise_sigma)
    reference.setflags(write=False)
    target.setflags(write=False)
    return reference, target, field


# (coeff_u, coeff_v) for each named deformation. The quadratic coefficients
# are sized so the curvature contributes ~0.1 px across a 31 px subset --
# small enough to be a plausible experiment, large enough that a first-order
# shape function cannot absorb it.
_FIELDS: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
    "translation": (
        (0.37, 0.0, 0.0, 0.0, 0.0, 0.0),
        (-0.42, 0.0, 0.0, 0.0, 0.0, 0.0),
    ),
    "stretch": (
        (0.0, 1.0e-2, 0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, -3.0e-3, 0.0, 0.0, 0.0),
    ),
    "quadratic": (
        (0.31, 3.0e-3, -1.5e-3, 4.0e-4, -2.0e-4, 1.5e-4),
        (-0.24, 1.2e-3, 2.5e-3, -1.8e-4, 3.0e-4, -2.5e-4),
    ),
}


def case(name: str, size: int = 160, noise_sigma: float = 0.0):
    return _cached_case(name, size, noise_sigma)


# The texture is defined on the whole plane but the images are finite, so
# POIs stay clear of the border where the interpolator would mirror.
INTERIOR_MARGIN = 30


def solve_pair(name, order, size=160, subset_radius=15, step=20, **kwargs):
    """Run one solver over an interior grid of a named case."""
    reference, target, field = case(name, size)
    params = ICGNParams(
        subset_radius=subset_radius, step=step, max_iter=50, shape_order=order
    )
    points = make_grid((size, size), params, margin=INTERIOR_MARGIN)
    solver = icgn_first_order if order == 1 else icgn_second_order
    return points, field, solver(reference, target, points, params, **kwargs)


def displacement_rms(result, truth: np.ndarray) -> float:
    error = np.concatenate((result.u - truth[:, U], result.v - truth[:, V]))
    return float(np.sqrt(np.mean(error * error)))


# --------------------------------------------------------------------------
# Parameter bookkeeping
# --------------------------------------------------------------------------


def test_shape_param_bookkeeping():
    assert shape_param_count(1) == 6
    assert shape_param_count(2) == 12
    assert shape_param_labels(1) == ("u", "u_x", "u_y", "v", "v_x", "v_y")
    assert shape_param_labels(2)[UXX] == "u_xx"
    assert shape_param_labels(2)[V] == "v"
    assert len(shape_param_labels(2)) == 12


@pytest.mark.parametrize("order", [0, 3, -1, 1.5])
def test_shape_order_must_be_one_or_two(order):
    with pytest.raises(ValueError, match="shape_order"):
        ICGNParams(shape_order=order)


def test_params_expose_the_parameter_count():
    assert ICGNParams().n_shape_params == 6
    assert ICGNParams(shape_order=2).n_shape_params == 12


# --------------------------------------------------------------------------
# Second-order warp algebra
# --------------------------------------------------------------------------

P_SAMPLE = np.array(
    [
        1.3,
        0.011,
        -0.004,
        8.0e-4,
        -3.0e-4,
        5.0e-4,
        -0.7,
        0.002,
        0.009,
        -6.0e-4,
        4.0e-4,
        2.0e-4,
    ]
)


def monomials(dx: float, dy: float) -> np.ndarray:
    return np.array([dx * dx, dy * dy, dx * dy, dx, dy, 1.0])


def shape_function(p: np.ndarray, dx: float, dy: float) -> tuple[float, float]:
    """Direct evaluation of the quadratic shape function, for cross-checking."""
    xi = p[U] + p[UX] * dx + p[UY] * dy
    xi += 0.5 * p[UXX] * dx * dx + p[UXY] * dx * dy + 0.5 * p[UYY] * dy * dy
    eta = p[V] + p[VX] * dx + p[VY] * dy
    eta += 0.5 * p[VXX] * dx * dx + p[VXY] * dx * dy + 0.5 * p[VYY] * dy * dy
    return dx + xi, dy + eta


def test_warp_matrix_second_order_roundtrips_through_its_parameters():
    recovered = warp_params_second_order(warp_matrix_second_order(P_SAMPLE))
    assert np.allclose(recovered, P_SAMPLE, atol=1e-15, rtol=0)


def test_warp_matrix_second_order_applies_the_shape_function():
    """Rows 3 and 4 must be the shape function itself, not an approximation."""
    matrix = warp_matrix_second_order(P_SAMPLE)
    for dx, dy in [(0.0, 0.0), (7.0, -11.0), (-15.0, 15.0), (0.7, -1.3)]:
        image = matrix @ monomials(dx, dy)
        expected_x, expected_y = shape_function(P_SAMPLE, dx, dy)
        assert image[3] == pytest.approx(expected_x, abs=1e-12)
        assert image[4] == pytest.approx(expected_y, abs=1e-12)
        assert image[5] == 1.0


def test_affine_warps_are_represented_without_truncation():
    """Squaring an affine map produces no cubic terms, so all six rows are exact.

    This is the reason the 6x6 representation is safe to build a solver on:
    the truncation it performs is invisible on the affine subgroup, which is
    where the bulk of any real warp lives.
    """
    affine = np.array([1.3, 0.011, -0.004, -0.7, 0.002, 0.009])
    matrix = warp_matrix_second_order(first_to_second_order(affine))
    for dx, dy in [(9.0, -13.0), (-15.0, 4.5)]:
        warped_x = dx + affine[0] + affine[1] * dx + affine[2] * dy
        warped_y = dy + affine[3] + affine[4] * dx + affine[5] * dy
        assert np.allclose(
            matrix @ monomials(dx, dy), monomials(warped_x, warped_y), atol=1e-11
        )


def test_composing_a_warp_with_itself_cancels():
    assert np.allclose(
        compose_inverse_second_order(P_SAMPLE, P_SAMPLE), np.zeros(12), atol=1e-12
    )


def test_second_order_composition_agrees_with_first_order_on_affine():
    """On the affine subgroup the 12-parameter update must reproduce the 6."""
    p = np.array([1.3, 0.010, -0.004, -0.7, 0.002, 0.008])
    dp = np.array([-0.4, 0.02, 0.005, 0.9, -0.003, 0.011])
    quadratic = compose_inverse_second_order(
        first_to_second_order(p), first_to_second_order(dp)
    )
    assert np.allclose(quadratic, first_to_second_order(compose_inverse(p, dp)))
    assert np.allclose(second_to_first_order(quadratic), compose_inverse(p, dp))


def test_composed_warp_undoes_the_increment_on_the_subset():
    """``W(p) . W(dp)^-1`` applied after ``W(dp)`` must land back on ``W(p)``.

    Checked where it has to hold -- on the subset itself -- because the
    truncated representation is only second-order accurate off it.
    """
    p = P_SAMPLE
    dp = np.array(
        [0.05, 1e-3, -2e-3, 4e-5, -3e-5, 2e-5, -0.03, 2e-3, 1e-3, -2e-5, 3e-5, -4e-5]
    )
    composed = compose_inverse_second_order(p, dp)
    for dx, dy in [(-10.0, -10.0), (0.0, 6.0), (10.0, 10.0)]:
        via_dp = shape_function(dp, dx, dy)
        two_step = shape_function(composed, via_dp[0], via_dp[1])
        direct = shape_function(p, dx, dy)
        # The two-step route re-enters the shape function at an offset that is
        # itself displaced, so agreement is to the order of the neglected
        # cubic terms, not to round-off.
        assert two_step[0] == pytest.approx(direct[0], abs=2e-3)
        assert two_step[1] == pytest.approx(direct[1], abs=2e-3)


def test_compose_inverse_second_order_rejects_a_degenerate_increment():
    """A warp increment that collapses the subset must raise, not return junk."""
    dp = np.zeros(12)
    dp[UX] = -1.0  # 1 + u_x = 0 with no v_x: the linear part is rank 1
    with pytest.raises(np.linalg.LinAlgError):
        compose_inverse_second_order(np.zeros(12), dp)


@pytest.mark.parametrize("bad", [np.zeros(6), np.zeros(13), np.full(12, np.nan)])
def test_second_order_algebra_validates_its_input(bad):
    with pytest.raises(ValueError):
        compose_inverse_second_order(np.zeros(12), bad)


def test_warp_params_second_order_rejects_a_wrong_sized_matrix():
    with pytest.raises(ValueError, match="6x6"):
        warp_params_second_order(np.eye(3))


def test_order_conversions_round_trip_through_the_affine_subgroup():
    affine = np.array([1.3, 0.011, -0.004, -0.7, 0.002, 0.009])
    promoted = first_to_second_order(affine)
    assert promoted.shape == (12,)
    assert np.all(promoted[CURVATURE] == 0.0)
    assert np.array_equal(second_to_first_order(promoted), affine)
    # The projection genuinely discards curvature; it is not an inverse.
    assert not np.array_equal(second_to_first_order(P_SAMPLE), P_SAMPLE[:6])


# --------------------------------------------------------------------------
# The result object
# --------------------------------------------------------------------------


def test_second_order_result_has_twelve_labelled_columns():
    points, _, result = solve_pair("quadratic", order=2)
    assert result.shape_order == 2
    assert result.p.shape == (len(points), 12)
    assert result.p_labels == shape_param_labels(2)
    # ``v`` moves from column 3 to column 6 with the wider parameter vector;
    # reading it from the wrong column is the obvious way to get this wrong.
    assert np.array_equal(result.v, result.p[:, V])
    assert not np.allclose(result.v, result.p[:, 3])
    assert np.array_equal(result.u, result.p[:, U])


def test_second_order_masking_and_status_counts_cover_all_columns():
    reference, target, _ = case("quadratic")
    params = ICGNParams(subset_radius=12, shape_order=2)
    result = icgn_second_order(
        reference, target, np.array([[2.0, 2.0], [80.0, 80.0]]), params
    )
    assert result.status_counts() == {Status.OUT_OF_BOUNDS: 1, Status.CONVERGED: 1}
    masked = result.masked("p")
    assert masked.shape == (2, 12)
    assert np.all(np.isnan(masked[0]))
    assert np.all(np.isfinite(masked[1]))


def test_second_order_empty_aoi_keeps_the_twelve_column_layout():
    reference, target, _ = case("quadratic")
    params = ICGNParams(subset_radius=12, shape_order=2, compute_covariance=True)
    result = icgn_second_order(reference, target, np.zeros((0, 2)), params)
    assert result.p.shape == (0, 12)
    assert result.covariance is not None
    assert result.covariance.shape == (0, 12, 12)
    assert result.v.shape == (0,)
    assert result.status_counts() == {}


# --------------------------------------------------------------------------
# Accuracy: the second-order shape function against the first
# --------------------------------------------------------------------------


def test_second_order_recovers_a_quadratic_warp_far_better_than_first_order():
    """The headline comparison: a displacement field curved inside the subset.

    The second-order shape function can represent this field exactly, the
    first-order one cannot, and the gap is the whole point of the extra six
    parameters. An order of magnitude is asked for; the observed ratio is
    around fifty.
    """
    points, field, first = solve_pair("quadratic", order=1)
    _, _, second = solve_pair("quadratic", order=2)
    truth = field.params_at(points)

    assert np.all(first.status == int(Status.CONVERGED))
    assert np.all(second.status == int(Status.CONVERGED))

    rms_first = displacement_rms(first, truth)
    rms_second = displacement_rms(second, truth)
    assert rms_second < rms_first / 10.0, f"{rms_second:.3e} vs {rms_first:.3e}"
    assert rms_second < 5e-3, f"second-order RMS = {rms_second:.3e} px"
    # And the first-order fit really is limited by its shape function, not by
    # something both solvers share -- otherwise the comparison proves nothing.
    assert rms_first > 5e-3


def test_second_order_recovers_the_curvature_terms():
    points, field, result = solve_pair("quadratic", order=2)
    truth = field.params_at(points)
    assert np.all(result.valid)

    error = np.abs(result.p[:, CURVATURE] - truth[:, CURVATURE])
    assert error.max() < 1e-4, f"max curvature error = {error.max():.3e} px^-1"
    relative = error.max(axis=0) / np.abs(truth[0, CURVATURE])
    assert relative.max() < 0.05, (
        f"worst relative curvature error = {relative.max():.3%}"
    )


def test_second_order_fits_the_subset_better_than_first_order():
    """A richer shape function must not fit a curved field *worse*."""
    _, _, first = solve_pair("quadratic", order=1)
    _, _, second = solve_pair("quadratic", order=2)
    assert second.zncc.min() > first.zncc.max()
    assert second.zncc.min() > 0.9999


def test_second_order_also_sharpens_the_displacement_gradients():
    points, field, first = solve_pair("quadratic", order=1)
    _, _, second = solve_pair("quadratic", order=2)
    truth = field.params_at(points)

    def gradient_rms(result, columns):
        error = result.p[:, columns] - truth[:, GRADIENT]
        return float(np.sqrt(np.mean(error * error)))

    assert gradient_rms(second, GRADIENT) < gradient_rms(first, [1, 2, 4, 5])


# --------------------------------------------------------------------------
# Accuracy: cases the first-order solver already handles
# --------------------------------------------------------------------------


def test_second_order_recovers_a_pure_translation():
    """No curvature to find: the six new parameters must stay near zero."""
    points, field, result = solve_pair(
        "translation", order=2, size=128, subset_radius=12
    )
    truth = field.params_at(points)
    assert np.all(result.status == int(Status.CONVERGED))
    assert np.max(np.abs(result.u - truth[:, U])) < 0.01
    assert np.max(np.abs(result.v - truth[:, V])) < 0.01
    assert np.max(np.abs(result.p[:, GRADIENT])) < 1e-3
    assert np.max(np.abs(result.p[:, CURVATURE])) < 1e-4


def test_second_order_recovers_a_uniaxial_stretch():
    """1% uniaxial stretch with a Poisson contraction: affine, so flat.

    The stretch is the classic first-order acceptance case; the second-order
    solver has to reproduce it without inventing curvature to explain a field
    that has none.
    """
    points, field, second = solve_pair("stretch", order=2)
    _, _, first = solve_pair("stretch", order=1)
    truth = field.params_at(points)

    assert np.all(second.status == int(Status.CONVERGED))
    assert np.max(np.abs(second.p[:, UX] - 1.0e-2)) < 5e-4
    assert np.max(np.abs(second.p[:, VY] + 3.0e-3)) < 5e-4
    assert np.max(np.abs(second.p[:, CURVATURE])) < 5e-5

    # On an affine field the two orders must agree closely: any large gap
    # would mean the extra parameters are absorbing noise or model error.
    assert displacement_rms(second, truth) < 5e-3
    assert displacement_rms(second, truth) < 5.0 * displacement_rms(first, truth)


def test_second_order_costs_precision_where_there_is_no_curvature_to_find():
    """The documented trade-off, asserted rather than left as folklore.

    Twelve parameters fitted from the same pixels means a higher noise floor.
    On a noisy pure translation the second-order scatter should be worse than
    the first-order scatter -- but only by a small factor, not a blow-up.
    """
    size = 192
    field = QuadraticField(*_FIELDS["translation"], centre=centre_of(size))
    reference, target = warped_pair(field, size, noise_sigma=2.0)
    points = make_grid((size, size), ICGNParams(subset_radius=15, step=10), margin=40)
    common = {"subset_radius": 15, "step": 10, "max_iter": 50}
    first = icgn_first_order(reference, target, points, ICGNParams(**common))
    second = icgn_second_order(
        reference, target, points, ICGNParams(shape_order=2, **common)
    )

    assert np.mean(first.valid) > 0.99
    assert np.mean(second.valid) > 0.99
    spread_first = float(np.std(first.u[first.valid]))
    spread_second = float(np.std(second.u[second.valid]))
    assert spread_second > spread_first
    assert spread_second < 5.0 * spread_first
    # Still a usable measurement, not a diverging one.
    assert spread_second < 0.05
    assert abs(float(np.mean(second.u[second.valid])) - 0.37) < 0.01


# --------------------------------------------------------------------------
# Entry points, seeding and failure reporting
# --------------------------------------------------------------------------


def test_icgn_dispatches_on_the_shape_order_field():
    reference, target, _ = case("quadratic")
    points = make_grid((160, 160), ICGNParams(step=20), margin=INTERIOR_MARGIN)
    assert icgn(reference, target, points, ICGNParams(step=20)).p.shape[1] == 6
    wide = icgn(reference, target, points, ICGNParams(step=20, shape_order=2))
    assert wide.p.shape[1] == 12
    assert wide.shape_order == 2
    # The default is still first order, so existing callers are untouched.
    assert icgn(reference, target, points).shape_order == 1


def test_icgn_first_order_ignores_the_shape_order_field():
    """The named entry points fix their own order; only :func:`icgn` dispatches.

    A caller who reaches for ``icgn_first_order`` has asked for six
    parameters by name, and must get them whatever the params object says.
    """
    reference, target, _ = case("quadratic")
    points = make_grid((160, 160), ICGNParams(step=20), margin=INTERIOR_MARGIN)
    plain = icgn_first_order(reference, target, points, ICGNParams(step=20))
    confused = icgn_first_order(
        reference, target, points, ICGNParams(step=20, shape_order=2)
    )
    assert confused.p.shape == plain.p.shape == (len(points), 6)
    assert confused.shape_order == 1
    assert np.array_equal(confused.p, plain.p)
    assert np.array_equal(confused.status, plain.status)


def test_second_order_accepts_an_affine_seed_from_the_first_order_solver():
    """Two-stage solving: cheap 6-parameter field, then 12-parameter refinement."""
    points, field, first = solve_pair("quadratic", order=1)
    reference, target, _ = case("quadratic")
    params = ICGNParams(subset_radius=15, step=20, max_iter=50, shape_order=2)
    seeded = icgn_second_order(reference, target, points, params, initial_guess=first.p)
    truth = field.params_at(points)

    assert np.all(seeded.status == int(Status.CONVERGED))
    assert displacement_rms(seeded, truth) < 5e-3
    # The seed carries the affine part, so fewer iterations are left to do.
    _, _, cold = solve_pair("quadratic", order=2)
    assert seeded.iterations.mean() < cold.iterations.mean()


def test_second_order_accepts_a_translation_seed_in_the_right_column():
    reference, target, _ = case("translation", size=128)
    params = ICGNParams(subset_radius=12, step=16, shape_order=2)
    points = make_grid((128, 128), params, margin=INTERIOR_MARGIN)
    result = icgn_second_order(
        reference, target, points, params, initial_guess=np.array([[0.0, -1.0]])
    )
    assert np.all(result.valid)
    assert np.max(np.abs(result.v + 0.42)) < 0.01


@pytest.mark.parametrize(
    "guess",
    [
        pytest.param(np.zeros((1, 5)), id="wrong-width"),
        pytest.param(np.zeros((3, 12)), id="wrong-count"),
        pytest.param(np.full((1, 12), np.nan), id="nan"),
    ],
)
def test_second_order_rejects_a_malformed_initial_guess(guess):
    reference, target, _ = case("quadratic")
    with pytest.raises(ValueError, match="initial_guess"):
        icgn_second_order(
            reference,
            target,
            np.array([[80.0, 80.0]]),
            ICGNParams(subset_radius=12, shape_order=2),
            initial_guess=guess,
        )


def test_second_order_reports_a_flat_subset_instead_of_guessing():
    reference, target, _ = case("quadratic")
    reference, target = reference.copy(), target.copy()
    reference[50:110, 50:110] = 200.0
    target[50:110, 50:110] = 200.0
    params = ICGNParams(subset_radius=12, shape_order=2)
    result = icgn_second_order(
        reference, target, np.array([[80.0, 80.0], [125.0, 125.0]]), params
    )
    assert result.status[0] == int(Status.SINGULAR_HESSIAN)
    assert np.isnan(result.masked("p")[0]).all()
    assert result.valid[1]


def test_second_order_rejects_a_subset_textured_in_one_direction_only():
    """Vertical stripes leave the whole ``v`` half of the Hessian empty.

    Rank deficiency of this kind is worse at second order -- twelve unknowns
    from a one-dimensional gradient field -- so the conditioning gate has to
    catch it there too rather than being rescued by the diagonal loading.
    """
    size = 96
    xs = np.arange(size, dtype=np.float64)
    stripes = 128.0 + 60.0 * np.sin(2.0 * math.pi * xs / 7.0)
    reference = np.tile(stripes, (size, 1))
    params = ICGNParams(subset_radius=12, shape_order=2)
    result = icgn_second_order(
        reference, reference.copy(), np.array([[48.0, 48.0]]), params
    )
    assert result.status[0] == int(Status.SINGULAR_HESSIAN)


def test_second_order_is_invariant_to_gain_and_offset():
    """ZNSSD absorbs ``g = a f + b`` at either shape order."""
    reference, target, _ = case("quadratic")
    params = ICGNParams(subset_radius=15, step=20, max_iter=50, shape_order=2)
    points = make_grid((160, 160), params, margin=INTERIOR_MARGIN)
    plain = icgn_second_order(reference, target, points, params)
    rescaled = icgn_second_order(reference, 0.7 * target + 30.0, points, params)
    assert np.max(np.abs(plain.p - rescaled.p)) < 1e-8


def test_second_order_covariance_is_twelve_by_twelve_and_scales_with_noise():
    reference, target, _ = case("quadratic")
    points = make_grid((160, 160), ICGNParams(step=20), margin=INTERIOR_MARGIN)

    def sigma_u(noise: float) -> np.ndarray:
        params = ICGNParams(
            subset_radius=15,
            step=20,
            shape_order=2,
            compute_covariance=True,
            image_noise_sigma=noise,
        )
        result = icgn_second_order(reference, target, points, params)
        assert result.covariance.shape == (len(points), 12, 12)
        return np.sqrt(result.covariance[:, U, U])

    one = sigma_u(1.0)
    assert np.all(np.isfinite(one))
    assert np.allclose(sigma_u(2.0), 2.0 * one)
    # The curvature terms are far less well determined than the translation,
    # which is the price the wider parameter vector pays.
    params = ICGNParams(
        subset_radius=15,
        step=20,
        shape_order=2,
        compute_covariance=True,
        image_noise_sigma=1.0,
    )
    covariance = icgn_second_order(reference, target, points, params).covariance
    assert np.all(covariance[:, UXX, UXX] < covariance[:, U, U])


def test_second_order_out_of_bounds_and_no_initial_guess_still_report():
    reference, target, _ = case("translation", size=128)
    params = ICGNParams(subset_radius=12, shape_order=2)
    result = icgn_second_order(reference, target, np.array([[3.0, 3.0]]), params)
    assert result.status[0] == int(Status.OUT_OF_BOUNDS)
    assert result.iterations[0] == 0
    assert result.p.shape == (1, 12)
