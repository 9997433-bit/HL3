# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`hl3.uq`: displacement covariance -> strain standard deviation.

A propagated uncertainty is unfalsifiable by inspection -- it is a plausible
number whatever it is -- so every assertion here pins it to something obtained a
different way. The four routes are the gate criteria of
``.agent_workspace/s1s4/IR2-F3-uq-contract.md`` section 10:

1. **the closed form**. For a full uniform window of ``L`` POI at pitch ``step``
   the plane fit reduces to ``u_x = sum(dx_j u_j) / sum(dx_j^2)``, so
   ``sigma(exx) = (sigma_u / step) sqrt(12 / (L^2 (L^2 - 1)))`` exactly. That is
   the ``L^-2`` half of the VSG trade-off, and the contract requires it to 1e-12;
2. **equivalence with the fitter**. The operator this module builds must be the
   one :func:`hl3.strain.pls_gradients` applies -- same normal equations, same
   rank rejection, same NaN pattern -- or the sigma describes an estimator
   nobody ran. Asserted against the fitter's measured sensitivity to a moved
   POI, which needs no shared code at all;
3. **Monte Carlo**. Noise is drawn and the strain scatter measured, with the
   predicted/measured ratio required to land in ``[0.8, 1.25]``, the same band
   spec section 5.6 uses for the displacement noise floor;
4. **failure semantics and determinism**, which are as much of the contract as
   the arithmetic: a missing variance must become NaN at exactly the affected
   points, and impossible input must raise rather than propagate.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

# Allow running against a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hl3 import uq  # noqa: E402
from hl3.correlate import ICGNResult, Status  # noqa: E402
from hl3.io.hdf5_schema import (  # noqa: E402
    SG_STRAIN_STD,
    STRAIN_REQUIRED,
    UQ_METHODS,
)
from hl3.strain import StrainParams, compute_strain, pls_gradients  # noqa: E402
from hl3.uq import (  # noqa: E402
    DisplacementVariances,
    StrainStdField,
    displacement_variances,
    propagate_strain_std,
)

STEP = 5.0
SUBSET = 21


def uniform_field(
    ny: int = 9, nx: int = 11, exx: float = 1.0e-3, eyy: float = -3.0e-4
) -> tuple[np.ndarray, np.ndarray]:
    """Displacement grid of a uniform strain, in pixels, on a ``STEP`` lattice."""
    ys, xs = np.mgrid[0:ny, 0:nx].astype(float)
    return exx * xs * STEP, eyy * ys * STEP


def constant_variance(shape: tuple[int, int], sigma: float) -> np.ndarray:
    return np.full(shape, sigma * sigma)


def analytic_strain_std(sigma: float, window_pts: int, step: float) -> float:
    """The frozen closed form of IR2-F3 section 5."""
    L = window_pts
    return (sigma / step) * math.sqrt(12.0 / (L**2 * (L**2 - 1)))


def interior(values: np.ndarray, grid_shape: tuple[int, int], pad: int) -> np.ndarray:
    """Points whose fit window lies entirely inside the grid."""
    return values.reshape(grid_shape)[pad:-pad, pad:-pad]


def masked_case() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A grid with a hole and a masked corner -- where closed forms run out."""
    u, v = uniform_field(ny=7, nx=7)
    u = u + 2.0e-4 * np.arange(7)[:, None] * STEP  # a shear, so exy != 0
    u[3, 3] = np.nan
    v[3, 3] = np.nan
    valid = np.ones(u.shape, dtype=bool)
    valid[0, :2] = False
    return u, v, valid


# --------------------------------------------------------------------------
# Gate 1: the closed form
# --------------------------------------------------------------------------


@pytest.mark.parametrize("window_pts", [3, 5, 7])
@pytest.mark.parametrize("sigma", [0.005, 0.02])
def test_closed_form_anchor(window_pts, sigma):
    """IR2-F3 section 5, to the 1e-12 relative deviation the contract demands."""
    u, v = uniform_field(ny=13, nx=15)
    var = constant_variance(u.shape, sigma)
    std = propagate_strain_std(
        u,
        v,
        var,
        var,
        StrainParams(window_pts=window_pts, tensor="engineering"),
        step_px=STEP,
    )
    expected = analytic_strain_std(sigma, window_pts, STEP)
    pad = window_pts // 2
    for name in ("exx_std", "eyy_std"):
        block = interior(getattr(std, name), std.grid_shape, pad)
        assert np.allclose(block, expected, rtol=1e-12, atol=0.0)
    # exy = (u_y + v_x) / 2 of two independent gradients with equal variance.
    shear = interior(std.exy_std, std.grid_shape, pad)
    assert np.allclose(shear, expected / math.sqrt(2.0), rtol=1e-12, atol=0.0)


def test_the_documented_example():
    """sigma_u = 0.01 px, step = 5, L = 5 -> sigma_exx ~ 2.83e-4 (IR2-F3 s5)."""
    u, v = uniform_field(ny=11, nx=11)
    var = constant_variance(u.shape, 0.01)
    std = propagate_strain_std(
        u, v, var, var, StrainParams(tensor="engineering"), step_px=5.0
    )
    assert float(interior(std.exx_std, std.grid_shape, 2)[0, 0]) == pytest.approx(
        2.828e-4, rel=1e-3
    )


def test_strain_noise_falls_as_window_squared():
    """The VSG trade-off, quantified: a wider gauge is a quieter one."""
    u, v = uniform_field(ny=25, nx=25)
    var = constant_variance(u.shape, 0.01)
    stds = {}
    for window_pts in (5, 9):
        field = propagate_strain_std(
            u,
            v,
            var,
            var,
            StrainParams(window_pts=window_pts, tensor="engineering"),
            step_px=STEP,
        )
        stds[window_pts] = float(
            np.nanmean(interior(field.exx_std, field.grid_shape, window_pts // 2))
        )
    assert stds[5] / stds[9] == pytest.approx(
        math.sqrt((81 * 80) / (25 * 24)), rel=1e-9
    )


def test_variance_scales_the_sigma_linearly_and_the_step_inversely():
    u, v = uniform_field()
    params = StrainParams(tensor="engineering")
    one = propagate_strain_std(
        u, v, constant_variance(u.shape, 0.01), constant_variance(u.shape, 0.01),
        params, step_px=STEP,
    )
    ten = propagate_strain_std(
        u, v, constant_variance(u.shape, 0.10), constant_variance(u.shape, 0.10),
        params, step_px=STEP,
    )
    assert np.allclose(10.0 * one.exx_std, ten.exx_std, rtol=1e-12, equal_nan=True)

    coarse = propagate_strain_std(
        u, v, constant_variance(u.shape, 0.01), constant_variance(u.shape, 0.01),
        params, step_px=2.0 * STEP,
    )
    assert np.allclose(2.0 * coarse.exx_std, one.exx_std, rtol=1e-12, equal_nan=True)


# --------------------------------------------------------------------------
# Gate 2: equivalence with the PLS fitter
# --------------------------------------------------------------------------


@pytest.mark.parametrize("source", [(3, 2), (0, 3), (6, 6)])
def test_operator_is_the_fitters_own_operator(source):
    """A unit-variance impulse must equal the fitter's sensitivity to that POI.

    With ``Var(u) = 1`` at one POI and 0 elsewhere, ``sigma(exx)`` under the
    engineering tensor is exactly ``|c_x[p, source]|`` -- one entry of the PLS
    hat matrix. The fitter's own sensitivity to the same POI is the change in
    ``u_x`` when that POI's displacement moves by ``h``, divided by ``h``, and
    the fit is linear so the difference is exact for any ``h``. Comparing the
    two pins the weights, the offsets, the masking and the ``1 / step`` to the
    fitter rather than to a plausible reimplementation of it.
    """
    u, v, valid = masked_case()
    mask = np.isfinite(u) & np.isfinite(v) & valid
    if not mask[source]:
        pytest.skip("the impulse POI must be one the fit actually uses")

    impulse = np.zeros(u.shape)
    impulse[source] = 1.0
    zero = np.zeros(u.shape)
    params = StrainParams(window_pts=5, tensor="engineering")
    std = propagate_strain_std(
        u, v, impulse, zero, params, step_px=STEP, valid=valid
    )

    h = 0.25
    moved = u.copy()
    moved[source] += h
    base = pls_gradients(u, v, step_px=STEP, window_pts=5, valid=valid)
    bumped = pls_gradients(moved, v, step_px=STEP, window_pts=5, valid=valid)
    sensitivity = (bumped.u_x - base.u_x).ravel() / h
    assert np.allclose(
        std.exx_std, np.abs(sensitivity), rtol=1e-9, atol=1e-18, equal_nan=True
    )


def test_validity_pattern_is_exactly_the_strain_fields():
    u, v, valid = masked_case()
    params = StrainParams(window_pts=5)
    std = propagate_strain_std(
        u,
        v,
        constant_variance(u.shape, 0.01),
        constant_variance(u.shape, 0.01),
        params,
        step_px=STEP,
        valid=valid,
    )
    strain = compute_strain(
        u, v, params, step_px=STEP, subset_px=SUBSET, valid=valid
    )
    assert np.array_equal(std.valid, strain.valid)
    assert not std.valid.all()  # the masked corner really is rejected
    # The contract's containment rule, which the above makes an equality here.
    assert np.all(strain.valid[std.valid])


def test_rank_deficient_windows_are_rejected_like_the_fitter():
    """A single grid row has collinear neighbours: no plane fit, no sigma."""
    u = np.zeros((1, 9))
    v = np.zeros((1, 9))
    fit = pls_gradients(u, v, step_px=STEP, window_pts=3, neighbor_min=3)
    std = propagate_strain_std(
        u,
        v,
        constant_variance(u.shape, 0.01),
        constant_variance(u.shape, 0.01),
        StrainParams(window_pts=3, min_valid_fraction=1.0 / 3.0, tensor="engineering"),
        step_px=STEP,
    )
    assert not np.any(np.isfinite(fit.u_x))
    assert not np.any(std.valid)


def test_holes_raise_the_uncertainty_of_their_neighbours():
    u, v = uniform_field(ny=11, nx=11)
    var = constant_variance(u.shape, 0.01)
    params = StrainParams(window_pts=5, tensor="engineering")
    full = propagate_strain_std(u, v, var, var, params, step_px=STEP)
    u_holed, v_holed = u.copy(), v.copy()
    u_holed[5, 6] = np.nan
    v_holed[5, 6] = np.nan
    holed = propagate_strain_std(u_holed, v_holed, var, var, params, step_px=STEP)
    assert holed.as_grid("exx_std")[5, 5] > full.as_grid("exx_std")[5, 5]
    assert np.isnan(holed.as_grid("exx_std")[5, 6])


def test_gaussian_weighting_costs_noise_for_its_smaller_gauge():
    u, v = uniform_field(ny=13, nx=13)
    var = constant_variance(u.shape, 0.01)
    common = {"step_px": STEP}
    uniform_w = propagate_strain_std(
        u, v, var, var,
        StrainParams(window_pts=7, weighting="uniform", tensor="engineering"),
        **common,
    )
    gaussian = propagate_strain_std(
        u, v, var, var,
        StrainParams(window_pts=7, weighting="gaussian", tensor="engineering"),
        **common,
    )
    good = uniform_w.valid & gaussian.valid
    # Same nominal VSG, more noise: the reason IR1-F3 froze the weighting as
    # reported metadata rather than an implementation detail.
    assert np.all(gaussian.exx_std[good] > uniform_w.exx_std[good])


def test_quadratic_fit_costs_noise_at_the_same_window():
    u, v = uniform_field(ny=13, nx=13)
    var = constant_variance(u.shape, 0.01)
    linear = propagate_strain_std(
        u, v, var, var,
        StrainParams(window_pts=7, fit_order="linear", tensor="engineering"),
        step_px=STEP,
    )
    quadratic = propagate_strain_std(
        u, v, var, var,
        StrainParams(window_pts=7, fit_order="quadratic", tensor="engineering"),
        step_px=STEP,
    )
    good = linear.valid & quadratic.valid
    assert np.all(quadratic.exx_std[good] >= linear.exx_std[good])


# --------------------------------------------------------------------------
# Gate 3: Monte Carlo
# --------------------------------------------------------------------------


def measured_strain_std(
    u: np.ndarray,
    v: np.ndarray,
    sigma: float,
    params: StrainParams,
    *,
    draws: int,
    seed: int,
) -> dict[str, np.ndarray]:
    """Sample standard deviation of the strain under drawn displacement noise.

    An independent route by construction: it calls the strain engine on noisy
    inputs and never touches :mod:`hl3.uq`.
    """
    rng = np.random.default_rng(seed)
    samples = {"exx": [], "eyy": [], "exy": []}
    for _ in range(draws):
        field = compute_strain(
            u + sigma * rng.standard_normal(u.shape),
            v + sigma * rng.standard_normal(v.shape),
            params,
            step_px=STEP,
            subset_px=SUBSET,
        )
        for name, rows in samples.items():
            rows.append(getattr(field, name))
    return {
        name: np.std(np.stack(rows), axis=0, ddof=1)
        for name, rows in samples.items()
    }


@pytest.mark.parametrize("tensor", ["engineering", "green_lagrange"])
def test_monte_carlo_ratio_is_within_the_gate_band(tensor):
    u, v = uniform_field(ny=7, nx=7)
    sigma = 0.02
    params = StrainParams(window_pts=5, tensor=tensor)
    var = constant_variance(u.shape, sigma)
    predicted = propagate_strain_std(u, v, var, var, params, step_px=STEP)
    measured = measured_strain_std(u, v, sigma, params, draws=400, seed=20260828)
    good = predicted.valid
    for name in ("exx", "eyy", "exy"):
        ratio = getattr(predicted, f"{name}_std")[good] / measured[name][good]
        assert np.all(ratio > 0.8)
        assert np.all(ratio < 1.25)
        # 400 draws put the sample spread at 3.5%, so the agreement is much
        # tighter than the gate band; assert that too, or the band would hide a
        # systematic factor of 1.2.
        assert np.mean(ratio) == pytest.approx(1.0, abs=0.05)


# --------------------------------------------------------------------------
# Tensor scope and the delta method
# --------------------------------------------------------------------------


def test_green_lagrange_jacobian_is_the_frozen_one():
    """``E_xx = u_x + (u_x^2 + v_x^2) / 2``, so ``dE_xx/du_x = 1 + u_x``."""
    exx = 0.05  # large enough that (1 + u_x) is not 1 to rounding
    u, v = uniform_field(ny=11, nx=11, exx=exx, eyy=0.0)
    var = constant_variance(u.shape, 0.01)
    linear = propagate_strain_std(
        u, v, var, var, StrainParams(tensor="engineering"), step_px=STEP
    )
    quadratic = propagate_strain_std(
        u, v, var, var, StrainParams(tensor="green_lagrange"), step_px=STEP
    )
    ratio = quadratic.exx_std / linear.exx_std
    assert np.allclose(ratio[quadratic.valid], 1.0 + exx, rtol=1e-9)


@pytest.mark.parametrize("tensor", ["euler_almansi", "hencky", "logarithmic"])
def test_tensors_without_a_frozen_jacobian_are_refused(tensor):
    u, v = uniform_field(ny=7, nx=7)
    var = constant_variance(u.shape, 0.01)
    with pytest.raises(ValueError, match="no frozen Jacobian"):
        propagate_strain_std(
            u, v, var, var, StrainParams(tensor=tensor), step_px=STEP
        )


def test_cross_covariance_moves_the_shear_and_leaves_the_normals():
    u, v, valid = masked_case()
    var = constant_variance(u.shape, 0.02)
    params = StrainParams(window_pts=5, tensor="engineering")
    common = {"step_px": STEP, "valid": valid, "params": params}
    without = propagate_strain_std(u, v, var, var, **common)
    with_cov = propagate_strain_std(u, v, var, var, uv_cov=0.9 * var, **common)
    good = without.valid
    # exy mixes u_y and v_x, so the cross term enters its variance as
    # 2 Cov(u_y, v_x) = 2 sum_j c_y[j] c_x[j] Cov(u_j, v_j). Two consequences,
    # both asserted here because both are counter-intuitive:
    #
    # * on a full symmetric window the two hat-matrix rows are odd in dy and in
    #   dx respectively, so the sum is exactly zero and a strong u-v
    #   correlation is invisible;
    # * where the window is clipped or holed the sum is non-zero of either
    #   sign, so a *positive* Cov(u, v) can lower the shear uncertainty as well
    #   as raise it. The geometry decides, not the sign of the correlation.
    assert np.any(with_cov.exy_std[good] != without.exy_std[good])
    assert np.any(with_cov.exy_std[good] < without.exy_std[good])

    clean_u, clean_v = uniform_field(ny=11, nx=11)
    clean_var = constant_variance(clean_u.shape, 0.02)
    plain = propagate_strain_std(
        clean_u, clean_v, clean_var, clean_var, params, step_px=STEP
    )
    correlated = propagate_strain_std(
        clean_u, clean_v, clean_var, clean_var, params,
        step_px=STEP, uv_cov=0.9 * clean_var,
    )
    assert np.allclose(
        correlated.as_grid("exy_std")[2:9, 2:9],
        plain.as_grid("exy_std")[2:9, 2:9],
        rtol=1e-12,
    )
    # The normal components never see the cross term at all.
    assert np.allclose(with_cov.exx_std[good], without.exx_std[good], rtol=1e-12)
    assert np.allclose(with_cov.eyy_std[good], without.eyy_std[good], rtol=1e-12)


# --------------------------------------------------------------------------
# Segment B: the correlator's covariance
# --------------------------------------------------------------------------


def icgn_result(n_points: int, sigma: float, *, order: int = 1) -> ICGNResult:
    size = 6 if order == 1 else 12
    index_v = 3 if order == 1 else 6
    cov = np.zeros((n_points, size, size))
    cov[:, 0, 0] = sigma**2
    cov[:, index_v, index_v] = (2.0 * sigma) ** 2
    cov[:, 0, index_v] = cov[:, index_v, 0] = 0.5 * sigma * (2.0 * sigma)
    cov[0] = np.nan  # the kernel leaves unsolved points as nan
    status = np.full(n_points, int(Status.CONVERGED))
    status[0] = int(Status.NOT_CONVERGED)
    return ICGNResult(
        x=np.zeros(n_points),
        y=np.zeros(n_points),
        p=np.zeros((n_points, size)),
        zncc=np.full(n_points, 0.99),
        iterations=np.full(n_points, 4),
        status=status,
        covariance=cov,
        shape_order=order,
    )


@pytest.mark.parametrize("order", [1, 2])
def test_displacement_variances_reads_the_frozen_layout(order):
    result = icgn_result(9, 0.01, order=order)
    variances = displacement_variances(result)
    assert isinstance(variances, DisplacementVariances)
    assert variances.shape_order == order
    assert variances.u_var[1] == pytest.approx(1e-4)
    assert variances.v_var[1] == pytest.approx(4e-4)
    assert variances.uv_cov[1] == pytest.approx(1e-4)
    assert variances.u_std[1] == pytest.approx(0.01)
    assert variances.v_std[1] == pytest.approx(0.02)
    # NaN is passed through, not re-masked by status: the validity criterion
    # belongs to the strain fit, and two copies of it would be two criteria.
    assert np.isnan(variances.u_var[0])
    assert np.isnan(variances.u_std[0])


def test_displacement_variances_without_a_covariance_raises():
    result = icgn_result(4, 0.01)
    result.covariance = None
    with pytest.raises(ValueError, match="compute_covariance"):
        displacement_variances(result)


def test_displacement_variances_rejects_a_negative_variance():
    result = icgn_result(4, 0.01)
    result.covariance[2, 0, 0] = -1e-6
    with pytest.raises(ValueError, match="negative"):
        displacement_variances(result)


def test_chain_from_the_kernel_covariance_to_strain_std():
    """Segment A output -> B -> C+D, the path the pipeline will take."""
    shape = (7, 7)
    u, v = uniform_field(*shape)
    variances = displacement_variances(icgn_result(u.size, 0.01))
    valid = np.ones(shape, dtype=bool)
    valid.ravel()[0] = False  # the unconverged POI, excluded as the fit excludes it
    params = StrainParams(window_pts=5, tensor="engineering")
    std = propagate_strain_std(
        u,
        v,
        variances.u_var.reshape(shape),
        variances.v_var.reshape(shape),
        params,
        step_px=STEP,
        uv_cov=variances.uv_cov.reshape(shape),
        valid=valid,
        check_against=compute_strain(
            u, v, params, step_px=STEP, subset_px=SUBSET, valid=valid
        ),
        image_noise_sigma_dn=1.5,
    )
    assert np.isfinite(std.exx_std).any()
    assert std.image_noise_sigma_dn == 1.5
    assert std.schema_attrs()["image_noise_sigma_dn"] == 1.5
    # v is twice as uncertain as u, and eyy is the v_y gradient alone -- but
    # only where the window is full in both directions do the two gradients
    # share an operator norm, so the check is made on the clean interior block
    # rather than on the clipped border.
    assert np.allclose(
        std.as_grid("eyy_std")[3:5, 3:5],
        2.0 * std.as_grid("exx_std")[3:5, 3:5],
        rtol=1e-9,
    )


# --------------------------------------------------------------------------
# Failure semantics, NaN discipline, determinism
# --------------------------------------------------------------------------


def test_a_neighbour_without_a_variance_makes_only_that_window_nan():
    """Missing variance is NaN at the affected points, never a silent zero."""
    u, v = uniform_field(ny=11, nx=11)
    var = constant_variance(u.shape, 0.01)
    holed = var.copy()
    holed[5, 5] = np.nan
    params = StrainParams(window_pts=5, tensor="engineering")
    std = propagate_strain_std(u, v, holed, var, params, step_px=STEP)
    strain = compute_strain(u, v, params, step_px=STEP, subset_px=SUBSET)

    grid = std.as_grid("exx_std")
    assert np.all(np.isnan(grid[3:8, 3:8]))  # every window containing the POI
    assert np.isfinite(grid[2, 5])  # one row further out is unaffected
    # The strain itself is untouched -- an unknown uncertainty is not an
    # unknown measurement.
    assert np.isfinite(strain.as_grid("exx")[5, 5])
    assert np.all(strain.valid[std.valid])


def test_negative_or_impossible_inputs_raise():
    u, v = uniform_field(ny=7, nx=7)
    var = constant_variance(u.shape, 0.01)
    negative = var.copy()
    negative[2, 2] = -1e-8
    with pytest.raises(ValueError, match="negative"):
        propagate_strain_std(u, v, negative, var, step_px=STEP)
    with pytest.raises(ValueError, match="Cauchy-Schwarz|positive semi-definite"):
        propagate_strain_std(u, v, var, var, uv_cov=10.0 * var, step_px=STEP)
    with pytest.raises(ValueError, match="step_px"):
        propagate_strain_std(u, v, var, var, step_px=0.0)
    with pytest.raises(ValueError, match="2-D"):
        propagate_strain_std(u.ravel(), v.ravel(), var, var, step_px=STEP)
    with pytest.raises(ValueError, match="must have shape"):
        propagate_strain_std(u, v, var[:-1], var, step_px=STEP)
    with pytest.raises(ValueError, match="boolean"):
        propagate_strain_std(
            u, v, var, var, step_px=STEP, valid=np.ones(u.shape, dtype=int)
        )


def test_empty_grid_gives_an_empty_answer():
    empty = np.zeros((0, 0))
    std = propagate_strain_std(empty, empty, empty, empty, step_px=STEP)
    assert std.n_points == 0
    assert std.valid.size == 0
    assert std.grid_shape == (0, 0)
    assert std.schema_datasets()["exx"].size == 0


def test_check_against_catches_parameter_drift():
    u, v = uniform_field(ny=9, nx=9)
    var = constant_variance(u.shape, 0.01)
    params = StrainParams(window_pts=5, tensor="engineering")
    strain = compute_strain(u, v, params, step_px=STEP, subset_px=SUBSET)

    ok = propagate_strain_std(
        u, v, var, var, params, step_px=STEP, check_against=strain
    )
    assert np.array_equal(ok.valid, strain.valid)

    with pytest.raises(ValueError, match="window_pts"):
        propagate_strain_std(
            u,
            v,
            var,
            var,
            StrainParams(window_pts=7, tensor="engineering"),
            step_px=STEP,
            check_against=strain,
        )
    with pytest.raises(ValueError, match="tensor"):
        propagate_strain_std(
            u,
            v,
            var,
            var,
            StrainParams(window_pts=5, tensor="green_lagrange"),
            step_px=STEP,
            check_against=strain,
        )
    # Same parameters, different data: the mask that produced the strain field
    # is not the one being propagated.
    masked = np.ones(u.shape, dtype=bool)
    masked[4, 4] = False
    with pytest.raises(ValueError, match="validity pattern"):
        propagate_strain_std(
            u, v, var, var, params, step_px=STEP, valid=masked, check_against=strain
        )


def test_repeated_calls_are_bit_identical():
    u, v, valid = masked_case()
    var = constant_variance(u.shape, 0.01)
    args = (u, v, var, var, StrainParams(window_pts=5, tensor="green_lagrange"))
    first = propagate_strain_std(*args, step_px=STEP, valid=valid)
    second = propagate_strain_std(*args, step_px=STEP, valid=valid)
    for name in ("exx_std", "eyy_std", "exy_std"):
        assert np.array_equal(
            getattr(first, name), getattr(second, name), equal_nan=True
        )


def test_zero_variance_gives_zero_not_nan():
    """A noiseless input is a legitimate question with the answer zero."""
    u, v = uniform_field(ny=7, nx=7)
    zeros = np.zeros(u.shape)
    std = propagate_strain_std(
        u, v, zeros, zeros, StrainParams(tensor="engineering"), step_px=STEP
    )
    assert np.all(std.exx_std[std.valid] == 0.0)


# --------------------------------------------------------------------------
# Contract surface and schema alignment
# --------------------------------------------------------------------------


def test_public_surface_is_exactly_the_frozen_four():
    assert set(uq.__all__) == {
        "DisplacementVariances",
        "StrainStdField",
        "displacement_variances",
        "propagate_strain_std",
    }
    for name in uq.__all__:
        assert hasattr(uq, name)


def test_schema_datasets_and_attrs_line_up():
    u, v = uniform_field(ny=7, nx=7)
    var = constant_variance(u.shape, 0.01)
    std = propagate_strain_std(
        u, v, var, var, StrainParams(tensor="engineering"), step_px=STEP
    )
    datasets = std.schema_datasets()
    # strain_std/<name> is aligned to strain/<id> by name (schema section 9.4).
    assert set(datasets) == set(STRAIN_REQUIRED)
    for values in datasets.values():
        assert values.shape == (std.n_points,)
    assert SG_STRAIN_STD == "strain_std"

    attrs = std.schema_attrs()
    assert attrs["method"] == "propagated"
    assert attrs["method"] in UQ_METHODS
    assert "image_noise_sigma_dn" not in attrs  # omitted when unknown


def test_metadata_and_views_travel_with_the_field():
    u, v = uniform_field(ny=7, nx=9)
    var = constant_variance(u.shape, 0.01)
    params = StrainParams(window_pts=5, tensor="green_lagrange")
    std = propagate_strain_std(u, v, var, var, params, step_px=STEP)
    assert isinstance(std, StrainStdField)
    assert std.tensor == "green_lagrange"
    assert std.window_pts == 5
    assert std.method == "propagated"
    # Assumption A1 travels with the result rather than living in a docstring.
    assert std.neighbor_correlation == "independent"
    assert std.grid_shape == (7, 9)
    assert std.n_points == 63
    assert std.as_grid("exx_std").shape == (7, 9)
    assert np.allclose(std.gamma_xy_std, 2.0 * std.exy_std, equal_nan=True)
    with pytest.raises(ValueError, match="per-POI array"):
        std.as_grid("tensor")


def test_all_three_components_share_one_nan_pattern():
    u, v, valid = masked_case()
    var = constant_variance(u.shape, 0.01)
    std = propagate_strain_std(
        u, v, var, var, StrainParams(window_pts=5), step_px=STEP, valid=valid
    )
    assert np.array_equal(np.isnan(std.exx_std), np.isnan(std.eyy_std))
    assert np.array_equal(np.isnan(std.exx_std), np.isnan(std.exy_std))
    assert np.array_equal(std.valid, ~np.isnan(std.exx_std))
    assert np.all(std.exx_std[std.valid] >= 0.0)
