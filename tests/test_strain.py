# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`hl3.strain`: PLS gradients, tensor family, VSG bookkeeping.

Everything here is closed-form synthetic: displacement grids are built from an
exactly known deformation, so the expected strain is analytic and the tolerances
test the implementation rather than a reference number someone once measured.
That is possible because strain from a *given* displacement field is pure
algebra -- the correlator's own accuracy is tested in
``tests/test_icgn_synth.py`` and is deliberately not entangled with this file.

Two assertions carry most of the weight, and they are the two halves of the
spec's rigid-motion check (R1-O1 section 5.3):

* a uniform deformation must come back exactly, to rounding, for every tensor;
* a rigid rotation must give *exactly zero* Green-Lagrange strain, while
  engineering strain must give ``cos(theta) - 1``. Both halves matter: the first
  is correctness, the second documents the failure mode of the linearised
  measure so that nobody rediscovers it on a real specimen.

The rest covers what happens to imperfect input -- dropped points, masked
neighbours, windows that hang off the edge of the grid -- because that is the
state every real displacement field arrives in, and the contract surface frozen
in ``.agent_workspace/s1s4/IR1-F3-public-api.md`` section 4 and 6.
"""

from __future__ import annotations

import dataclasses
import math
import sys
from pathlib import Path

import numpy as np
import pytest

# Allow running against a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import hl3.strain as strain  # noqa: E402
from hl3.io.hdf5_schema import (  # noqa: E402
    STRAIN_METHODS,
    STRAIN_REQUIRED_ATTRS,
    STRAIN_TENSORS,
)
from hl3.io.hdf5_schema import vsg_size_px as schema_vsg_size_px  # noqa: E402
from hl3.strain import (  # noqa: E402
    StrainField,
    StrainParams,
    compute_strain,
    deformation_gradient,
    dilatation,
    effective_window_pts,
    engineering_shear,
    engineering_strain,
    euler_almansi_strain,
    green_lagrange_strain,
    grid_from_points,
    hencky_strain,
    neighbor_min_for,
    pls_gradients,
    principal_strains,
    rotation_angle,
    strain_tensor,
    subset_px_from_radius,
    tresca_strain,
    von_mises_strain,
    vsg_size_mm,
    vsg_size_px,
    window_pts_for_vsg,
)

SEED = 20260828
STEP = 5.0
SUBSET = 21
NX, NY = 40, 30
MICROSTRAIN = 1e-6

UNIFORM_F = np.array([[1.010, 0.004], [-0.002, 0.997]])


def grid_axes(step: float = STEP) -> tuple[np.ndarray, np.ndarray]:
    """POI axes in pixels, offset from the origin like a real AOI grid."""
    xs = 11.0 + step * np.arange(NX)
    ys = 7.0 + step * np.arange(NY)
    return xs, ys


def affine_displacement(
    F: np.ndarray, translation: tuple[float, float] = (0.0, 0.0), step: float = STEP
) -> tuple[np.ndarray, np.ndarray]:
    """Displacement grid of the homogeneous deformation ``x -> F x + t``."""
    xs, ys = grid_axes(step)
    X, Y = np.meshgrid(xs, ys)
    u = (F[0, 0] - 1.0) * X + F[0, 1] * Y + translation[0]
    v = F[1, 0] * X + (F[1, 1] - 1.0) * Y + translation[1]
    return u, v


def rotation_matrix(theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s], [s, c]])


def strain_of(u: np.ndarray, v: np.ndarray, params: StrainParams | None = None, **kw):
    """``compute_strain`` with this file's fixed step and subset size."""
    kw.setdefault("step_px", STEP)
    kw.setdefault("subset_px", SUBSET)
    return compute_strain(u, v, params, **kw)


def interior(field: np.ndarray, margin: int = 3) -> np.ndarray:
    """Drop the border, where windows are truncated, from a comparison."""
    return field[margin:-margin, margin:-margin]


def assert_uniform(actual: np.ndarray, expected: np.ndarray, atol: float = 1e-13):
    """Every entry of a field equals one tensor (``assert_allclose`` will not
    broadcast a ``(2, 2)`` expectation against a ``(ny, nx, 2, 2)`` field)."""
    np.testing.assert_allclose(
        actual, np.broadcast_to(expected, actual.shape), atol=atol
    )


# --------------------------------------------------------------------------- #
# Uniform deformation: the field the answer is known for
# --------------------------------------------------------------------------- #


def test_uniform_strain_gradients_are_exact():
    """A plane fit to a plane must return the plane, to rounding."""
    u, v = affine_displacement(UNIFORM_F, translation=(3.0, -1.5))
    g = pls_gradients(u, v, step_px=STEP)

    assert np.all(np.isfinite(interior(g.u_x)))
    np.testing.assert_allclose(interior(g.u_x), UNIFORM_F[0, 0] - 1.0, atol=1e-14)
    np.testing.assert_allclose(interior(g.u_y), UNIFORM_F[0, 1], atol=1e-14)
    np.testing.assert_allclose(interior(g.v_x), UNIFORM_F[1, 0], atol=1e-14)
    np.testing.assert_allclose(interior(g.v_y), UNIFORM_F[1, 1] - 1.0, atol=1e-14)


def test_uniform_strain_fit_reproduces_the_displacement_itself():
    """The fitted constant term is the displacement, not a smoothed neighbour."""
    u, v = affine_displacement(UNIFORM_F, translation=(3.0, -1.5))
    g = pls_gradients(u, v, step_px=STEP)
    np.testing.assert_allclose(interior(g.u_fit), interior(u), atol=1e-11)
    np.testing.assert_allclose(interior(g.v_fit), interior(v), atol=1e-11)


@pytest.mark.parametrize("weighting", ["uniform", "gaussian"])
@pytest.mark.parametrize("fit_order", ["linear", "quadratic"])
@pytest.mark.parametrize("window_pts", [3, 5, 9])
def test_uniform_strain_is_recovered_for_every_fit_variant(
    weighting, fit_order, window_pts
):
    """Window, order and weighting change the noise, never the uniform answer."""
    u, v = affine_displacement(UNIFORM_F)
    g = pls_gradients(
        u,
        v,
        step_px=STEP,
        window_pts=window_pts,
        fit_order=fit_order,
        weighting=weighting,
    )
    np.testing.assert_allclose(interior(g.u_x, 5), UNIFORM_F[0, 0] - 1.0, atol=1e-13)
    np.testing.assert_allclose(interior(g.v_y, 5), UNIFORM_F[1, 1] - 1.0, atol=1e-13)


@pytest.mark.parametrize("tensor", sorted(STRAIN_TENSORS))
def test_uniform_strain_matches_the_closed_form_tensor(tensor):
    """Every member of the family matches its textbook value for a known F."""
    u, v = affine_displacement(UNIFORM_F)
    field = strain_of(u, v, StrainParams(tensor=tensor))
    assert_uniform(interior(field.as_grid("E")), strain_tensor(UNIFORM_F, tensor))
    assert field.tensor == tensor


def test_logarithmic_is_the_schema_alias_of_hencky():
    """Both names are schema-legal for one tensor (IR1-F4 gap G-4)."""
    u, v = affine_displacement(UNIFORM_F)
    hencky = strain_of(u, v, StrainParams(tensor="hencky"))
    log = strain_of(u, v, StrainParams(tensor="logarithmic"))
    np.testing.assert_array_equal(hencky.exx, log.exx)
    # The requested name is echoed back unchanged, so @tensor stays faithful.
    assert log.tensor == "logarithmic"


def test_engineering_and_green_lagrange_agree_to_first_order():
    """The families differ at O(eps^2): 1250 ustrain apart at 5% strain."""
    small = np.array([[1.0002, 0.0001], [0.0001, 0.9999]])
    assert np.max(np.abs(engineering_strain(small) - green_lagrange_strain(small))) < 1e-7

    large = np.array([[1.05, 0.0], [0.0, 0.985]])
    assert abs(engineering_strain(large)[0, 0] - 0.05) < 1e-15
    assert abs(green_lagrange_strain(large)[0, 0] - 0.05125) < 1e-15


# --------------------------------------------------------------------------- #
# Rigid motion: the invariance the whole tensor family exists for
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("degrees", [0.1, 1.0, 5.0, 10.0, 30.0, 45.0])
def test_rigid_rotation_gives_zero_green_lagrange_strain(degrees):
    """Spec section 5.3's hard invariance check, with room to spare.

    The spec's end-to-end budget is ``max|E| < 5e-5`` because the correlator
    contributes most of it; fed an exact displacement field the strain module
    alone must land at rounding, so the tolerance here is 1e-13.
    """
    field = strain_of(*affine_displacement(rotation_matrix(math.radians(degrees))))
    assert np.nanmax(np.abs(field.exx)) < 1e-13
    assert np.nanmax(np.abs(field.eyy)) < 1e-13
    assert np.nanmax(np.abs(field.exy)) < 1e-13
    assert np.nanmax(np.abs(field.e1)) < 1e-13
    assert np.nanmax(np.abs(field.von_mises)) < 1e-13


@pytest.mark.parametrize("tensor", ["green_lagrange", "euler_almansi", "hencky"])
@pytest.mark.parametrize("degrees", [1.0, 20.0])
def test_rigid_rotation_is_zero_for_every_finite_strain_measure(tensor, degrees):
    u, v = affine_displacement(rotation_matrix(math.radians(degrees)))
    field = strain_of(u, v, StrainParams(tensor=tensor))
    assert np.nanmax(np.abs(field.E)) < 1e-13


@pytest.mark.parametrize("degrees", [0.5, 2.0, 10.0])
def test_engineering_strain_under_rotation_is_the_documented_artefact(degrees):
    """``eps_xx = cos(theta) - 1``: the reason the default is Green-Lagrange.

    At 2 degrees this is -610 microstrain of pure fiction, comparable to the
    elastic strain of a metal coupon. Asserting the artefact exactly keeps the
    linearised measure honest instead of quietly tolerated.
    """
    theta = math.radians(degrees)
    u, v = affine_displacement(rotation_matrix(theta))
    field = strain_of(u, v, StrainParams(tensor="engineering"))

    expected = math.cos(theta) - 1.0
    np.testing.assert_allclose(interior(field.as_grid("exx")), expected, atol=1e-13)
    np.testing.assert_allclose(interior(field.as_grid("eyy")), expected, atol=1e-13)
    # Shear stays zero, so the artefact is an apparent isotropic compression ...
    np.testing.assert_allclose(interior(field.as_grid("exy")), 0.0, atol=1e-13)
    # ... of magnitude theta^2 / 2 to leading order.
    assert abs(expected + 0.5 * theta**2) < 0.05 * abs(expected)


def test_rigid_translation_gives_zero_strain_and_zero_rotation():
    field = strain_of(*affine_displacement(np.eye(2), translation=(7.25, -3.5)))
    assert np.nanmax(np.abs(field.exx)) < 1e-15
    assert np.nanmax(np.abs(field.rotation)) < 1e-15
    assert np.nanmax(np.abs(field.dilatation)) < 1e-15


@pytest.mark.parametrize("degrees", [-30.0, -1.0, 1.0, 15.0])
def test_polar_decomposition_recovers_the_rotation_angle(degrees):
    theta = math.radians(degrees)
    field = strain_of(*affine_displacement(rotation_matrix(theta)))
    np.testing.assert_allclose(interior(field.as_grid("rotation")), theta, atol=1e-13)


def test_rotation_angle_rejects_a_reflection():
    """det(F) <= 0 is not a deformation; it must not report a plausible angle."""
    assert np.isnan(rotation_angle(np.array([[1.0, 0.0], [0.0, -1.0]])))


# --------------------------------------------------------------------------- #
# Spatial resolution: what the window costs and what the VSG size means
# --------------------------------------------------------------------------- #


def test_quadratic_order_pays_off_only_where_the_window_is_truncated():
    """Both orders are exact at the centre; only the quadratic one is at the edge.

    On a full symmetric window the extra basis terms are even in each axis while
    the gradient terms are odd, so the two orders return *identical* gradients.
    The quadratic fit earns its 6x6 solve at the grid boundary, where the window
    is one-sided and a plane fit has to trade curvature against slope.
    """
    xs, ys = grid_axes()
    X, _ = np.meshgrid(xs, ys)
    curvature = 2.0e-5
    u = curvature * (X - xs[0]) ** 2
    v = np.zeros_like(u)
    truth = 2.0 * curvature * (X - xs[0])

    common = {"step_px": STEP, "neighbor_min": 6, "require_center": True}
    linear = pls_gradients(u, v, **common)
    quadratic = pls_gradients(u, v, fit_order="quadratic", **common)

    np.testing.assert_allclose(interior(linear.u_x), interior(truth), atol=1e-15)
    np.testing.assert_allclose(interior(quadratic.u_x), interior(truth), atol=1e-15)

    edge_linear = np.abs(linear.u_x[:, 0] - truth[:, 0])
    edge_quadratic = np.abs(quadratic.u_x[:, 0] - truth[:, 0])
    assert np.all(np.isfinite(edge_linear))
    assert np.max(edge_linear) > 1e-6  # a plane fit is biased on a one-sided window
    assert np.max(edge_quadratic) < 1e-15


@pytest.mark.parametrize("window_pts", [3, 5, 9])
def test_larger_windows_attenuate_a_sinusoidal_strain_field(window_pts):
    """The spatial-resolution transfer function of spec section 5.5, in miniature.

    ``u = A sin(2 pi x / lam)`` has a known strain amplitude and the PLS window
    acts as a low-pass filter on it. The spec's acceptance line is that a
    wavelength comfortably longer than the VSG survives; the subset contribution
    is set to 1 px here so the window is the only term in Eq. (7.2).
    """
    xs, ys = grid_axes(step=1.0)
    X, _ = np.meshgrid(xs, ys)
    amplitude = 0.5
    wavelength = 4.0 * vsg_size_px(window_pts, 1.0, 1)
    k = 2.0 * np.pi / wavelength
    u = amplitude * np.sin(k * (X - xs[0]))
    v = np.zeros_like(u)

    g = pls_gradients(u, v, step_px=1.0, window_pts=window_pts)
    truth = amplitude * k * np.cos(k * (X - xs[0]))
    ratio = np.max(np.abs(interior(g.u_x, window_pts))) / np.max(
        np.abs(interior(truth, window_pts))
    )
    assert 0.9 < ratio <= 1.0


def test_attenuation_grows_monotonically_with_window_size():
    xs, ys = grid_axes(step=1.0)
    X, _ = np.meshgrid(xs, ys)
    k = 2.0 * np.pi / 24.0
    u = 0.5 * np.sin(k * (X - xs[0]))
    v = np.zeros_like(u)

    peaks = [
        np.nanmax(np.abs(interior(pls_gradients(u, v, window_pts=w).u_x, 8)))
        for w in (3, 5, 9, 15)
    ]
    assert peaks == sorted(peaks, reverse=True)


def test_larger_windows_lower_the_strain_noise_floor():
    """The other half of the trade-off the VSG number exists to expose."""
    rng = np.random.default_rng(SEED)
    u = rng.normal(0.0, 0.01, size=(NY, NX))
    v = rng.normal(0.0, 0.01, size=(NY, NX))

    sigmas = [
        float(np.nanstd(interior(pls_gradients(u, v, step_px=STEP, window_pts=w).u_x, 8)))
        for w in (3, 5, 9)
    ]
    assert sigmas == sorted(sigmas, reverse=True)
    # A 0.01 px noise floor differenced over a 5 px step would be 2000 ustrain;
    # the 9-point window has to do far better than that to be worth having.
    assert sigmas[-1] < 400 * MICROSTRAIN


# --------------------------------------------------------------------------- #
# Imperfect input
# --------------------------------------------------------------------------- #


def test_a_dropped_point_stays_local_and_does_not_bias_its_neighbours():
    u, v = affine_displacement(UNIFORM_F)
    u = u.copy()
    u[15, 20] = np.nan

    field = strain_of(u, v)
    exx = field.as_grid("exx")
    assert np.isnan(exx[15, 20])
    # Neighbours lose one sample out of 25 and are still exact, because the
    # missing sample is removed from the normal equations rather than filled.
    np.testing.assert_allclose(
        exx[15, 22], green_lagrange_strain(UNIFORM_F)[0, 0], atol=1e-13
    )
    assert np.isfinite(exx[16, 21])
    assert field.as_grid("n_neighbors")[15, 21] == 24


def test_require_center_false_fills_a_single_point_hole():
    """Interpolating across a pinhole is legitimate; it is opt-in and reported."""
    u, v = affine_displacement(UNIFORM_F)
    u = u.copy()
    u[15, 20] = np.nan

    filled = strain_of(u, v, StrainParams(require_center=False))
    np.testing.assert_allclose(
        filled.as_grid("exx")[15, 20],
        green_lagrange_strain(UNIFORM_F)[0, 0],
        atol=1e-13,
    )


def test_neighbor_min_rejects_thinly_populated_windows():
    u, v = affine_displacement(UNIFORM_F)
    u = u.copy()
    u[10:15, 10:15] = np.nan  # a hole the size of one whole window

    field = strain_of(u, v)
    exx = field.as_grid("exx")
    assert np.all(np.isnan(exx[11:14, 11:14]))
    assert np.isfinite(exx[20, 20])
    assert StrainParams().neighbor_min == 13


def test_grid_corners_are_rejected_by_the_default_neighbour_rule():
    """A corner window holds 9 of 25 points, below the ``0.5 L^2`` rule."""
    u, v = affine_displacement(UNIFORM_F)
    field = strain_of(u, v)
    assert np.isnan(field.as_grid("exx")[0, 0])
    assert field.as_grid("n_neighbors")[0, 0] == 9

    # Lowering the rule lets them through, and they are still exact: a truncated
    # window is not an inaccurate window, only a noisier one.
    relaxed = strain_of(u, v, StrainParams(min_valid_fraction=0.3))
    np.testing.assert_allclose(
        relaxed.as_grid("exx")[0, 0],
        green_lagrange_strain(UNIFORM_F)[0, 0],
        atol=1e-13,
    )


def test_non_converged_neighbours_are_excluded_from_the_fit():
    """The frozen neighbour rule: only ``status == CONVERGED`` points may pull.

    A ``LOW_ZNCC`` point keeps its displacement -- the correlator solved it --
    but a strain fit that lets it in inherits its error, so the mask is applied
    here rather than by deleting the displacement.
    """
    u, v = affine_displacement(UNIFORM_F)
    u = u.copy()
    u[12, 12] += 5.0  # a badly matched point ...
    converged = np.ones(u.shape, dtype=bool)
    converged[12, 12] = False  # ... that the correlator flagged as such

    unfiltered = strain_of(u, v)
    filtered = strain_of(u, v, valid=converged)

    truth = green_lagrange_strain(UNIFORM_F)[0, 0]
    assert abs(unfiltered.as_grid("exx")[13, 13] - truth) > 1e-3
    np.testing.assert_allclose(filtered.as_grid("exx")[13, 13], truth, atol=1e-13)
    assert np.isnan(filtered.as_grid("exx")[12, 12])


def test_all_invalid_input_yields_an_all_nan_field_without_raising():
    u = np.full((NY, NX), np.nan)
    field = strain_of(u, u)
    assert np.all(np.isnan(field.exx))
    assert not field.valid.any()
    assert np.all(field.n_neighbors == 0)


def test_the_three_components_share_one_nan_pattern():
    """``valid == isfinite(exx)`` is exact, so a mask taken from one component
    is a mask for all of them (frozen NaN semantics, IR1-F3 section 6)."""
    u, v = affine_displacement(UNIFORM_F)
    u = u.copy()
    u[5:9, 5:9] = np.nan
    field = strain_of(u, v)
    np.testing.assert_array_equal(np.isnan(field.exx), np.isnan(field.eyy))
    np.testing.assert_array_equal(np.isnan(field.exx), np.isnan(field.exy))
    np.testing.assert_array_equal(field.valid, np.isfinite(field.exx))


def test_a_single_grid_row_is_rank_deficient_rather_than_confidently_wrong():
    """One row cannot determine ``u_y``; the answer is NaN, not a fitted zero."""
    u, v = affine_displacement(UNIFORM_F)
    field = strain_of(u[:1, :], v[:1, :], StrainParams(min_valid_fraction=0.1))
    assert np.all(np.isnan(field.exx))


def test_explicit_valid_mask_combines_with_finiteness():
    u, v = affine_displacement(UNIFORM_F)
    valid = np.ones(u.shape, dtype=bool)
    valid[:, 20] = False
    g = pls_gradients(u, v, step_px=STEP, valid=valid)
    assert np.all(np.isnan(g.u_x[:, 20]))
    assert np.isfinite(g.u_x[15, 18])
    assert g.n_neighbors[15, 18] == 20  # the masked column costs 5 of 25 ...
    assert g.n_neighbors[15, 15] == 25  # ... and only inside the window


# --------------------------------------------------------------------------- #
# Tensor algebra
# --------------------------------------------------------------------------- #


def test_principal_strains_match_a_numerical_eigen_decomposition():
    rng = np.random.default_rng(SEED)
    xx = rng.normal(0.0, 0.02, size=200)
    yy = rng.normal(0.0, 0.02, size=200)
    xy = rng.normal(0.0, 0.01, size=200)
    E = np.stack([np.stack([xx, xy], -1), np.stack([xy, yy], -1)], axis=-2)
    p = principal_strains(E)
    reference = np.linalg.eigvalsh(E)

    np.testing.assert_allclose(p.e2, reference[:, 0], atol=1e-15)
    np.testing.assert_allclose(p.e1, reference[:, 1], atol=1e-15)
    np.testing.assert_allclose(p.gamma_max, p.e1 - p.e2, atol=1e-15)
    assert np.all(p.e1 >= p.e2)

    # theta_p really is the direction of e1, not merely an angle of the right size.
    n1 = np.stack([np.cos(p.theta_p), np.sin(p.theta_p)], axis=-1)
    np.testing.assert_allclose(
        np.einsum("nij,nj->ni", E, n1), p.e1[:, None] * n1, atol=1e-15
    )


def test_principal_values_are_invariant_under_a_frame_rotation():
    E = np.array([[0.02, 0.005], [0.005, -0.008]])
    base = principal_strains(E)
    alpha = math.radians(37.0)
    Q = rotation_matrix(alpha)
    rotated = principal_strains(Q.T @ E @ Q)

    assert abs(rotated.e1 - base.e1) < 1e-16
    assert abs(rotated.e2 - base.e2) < 1e-16
    assert abs((rotated.theta_p + alpha) - base.theta_p) < 1e-15


def test_pure_shear_principal_direction_is_45_degrees():
    """The case where the naive ``atan`` formula divides by zero."""
    E = np.array([[0.0, 0.01], [0.01, 0.0]])
    p = principal_strains(E)
    assert abs(p.theta_p - math.pi / 4) < 1e-15
    assert abs(p.e1 - 0.01) < 1e-17
    assert abs(engineering_shear(E) - 0.02) < 1e-17


def test_von_mises_equals_the_axial_strain_in_incompressible_uniaxial_tension():
    """Fixes the prefactor at ``2/sqrt(3)``; ``2/3`` would fail by sqrt(3)."""
    axial = 0.02
    assert abs(von_mises_strain(np.diag([axial, -0.5 * axial])) - axial) < 1e-15
    assert abs(von_mises_strain(np.zeros((2, 2)))) < 1e-18


def test_tresca_uses_the_out_of_plane_principal_strain():
    """Equibiaxial tension is where Tresca and the in-plane gamma_max part ways."""
    E = np.diag([0.01, 0.01])
    assert abs(principal_strains(E).gamma_max) < 1e-17
    assert abs(tresca_strain(E) - 0.03) < 1e-15  # e3 = -0.02


def test_hencky_strain_of_a_pure_stretch_is_the_log_stretch():
    stretch = 1.4
    E = hencky_strain(np.diag([stretch, 1.0 / stretch]))
    assert abs(E[0, 0] - math.log(stretch)) < 1e-15
    assert abs(E[1, 1] + math.log(stretch)) < 1e-15
    assert abs(E[0, 1]) < 1e-16
    # Additivity over load steps is the property Hencky strain is chosen for.
    total = hencky_strain(np.diag([stretch**2, stretch**-2]))
    assert abs(total[0, 0] - 2.0 * E[0, 0]) < 1e-15


def test_euler_almansi_is_the_pushforward_of_green_lagrange():
    F = np.array([[1.08, 0.03], [-0.02, 0.96]])
    Finv = np.linalg.inv(F)
    np.testing.assert_allclose(
        euler_almansi_strain(F), Finv.T @ green_lagrange_strain(F) @ Finv, atol=1e-15
    )


def test_dilatation_is_the_relative_area_change():
    assert abs(dilatation(np.array([[1.1, 0.0], [0.0, 1.2]])) - 0.32) < 1e-15
    assert abs(dilatation(rotation_matrix(0.3))) < 1e-15


def test_tensor_helpers_propagate_nan_instead_of_raising():
    """A failed POI must not take the whole field's eigen-solve down with it."""
    F = np.stack([np.eye(2), np.full((2, 2), np.nan), 1.05 * np.eye(2)])
    for func in (green_lagrange_strain, euler_almansi_strain, hencky_strain):
        E = func(F)
        assert np.all(np.isnan(E[1]))
        assert np.all(np.isfinite(E[0])) and np.all(np.isfinite(E[2]))
    assert np.isnan(principal_strains(np.full((1, 2, 2), np.nan)).e1[0])
    assert np.all(np.isnan(euler_almansi_strain(np.zeros((1, 2, 2)))))


def test_deformation_gradient_broadcasts_and_matches_its_definition():
    F = deformation_gradient(0.01, 0.002, -0.003, 0.02)
    np.testing.assert_allclose(F, [[1.01, 0.002], [-0.003, 1.02]], atol=0)
    field = deformation_gradient(np.zeros((4, 3)), 0.0, 0.0, np.zeros((4, 3)))
    assert field.shape == (4, 3, 2, 2)
    assert_uniform(field, np.eye(2), atol=0)


# --------------------------------------------------------------------------- #
# VSG bookkeeping
# --------------------------------------------------------------------------- #


def test_vsg_matches_gpg_equation_7_2():
    # (5 - 1) * 5 + 21 = 41 px, the worked default of spec section 1.6.
    assert vsg_size_px(5, 5.0, 21) == 41.0
    assert vsg_size_px(1, 5.0, 21) == 21.0  # strain from the shape function
    assert vsg_size_px(9, 3.0, 31) == 55.0
    assert vsg_size_mm(41.0, 16.35) == pytest.approx(41.0 / 16.35)
    assert subset_px_from_radius(10) == 21


def test_the_vsg_formula_has_exactly_one_implementation():
    """IR1-F4 section 10 item 2: the schema module owns the arithmetic.

    Two copies of Eq. (7.2) is how a reported gauge size and a stored
    ``@vsg_px`` drift apart, so this package must be delegating rather than
    repeating.
    """
    for window_pts, step, subset in ((5, 5, 21), (9, 3, 31), (1, 7, 15)):
        assert vsg_size_px(window_pts, step, subset) == schema_vsg_size_px(
            window_pts, step, subset
        )
    assert strain.vsg.vsg_size_px.__module__ == "hl3.strain.vsg"
    assert strain.vsg._schema_vsg_size_px is schema_vsg_size_px


def test_vsg_accounts_for_a_post_filter_window():
    assert effective_window_pts(5) == 5
    assert effective_window_pts(5, 9) == 9
    assert effective_window_pts(9, 5) == 9  # "whichever actually takes effect"
    assert effective_window_pts(5, 9, combine="cascade") == 13
    assert vsg_size_px(5, 5.0, 21, filter_window_pts=9) == 61.0
    assert vsg_size_px(5, 5.0, 21, filter_window_pts=9, combine="cascade") == 81.0


@pytest.mark.parametrize("target", [21.0, 22.0, 41.0, 42.0, 120.0])
def test_window_for_vsg_is_the_smallest_odd_window_that_reaches_the_target(target):
    step, subset = 5.0, 21
    window_pts = window_pts_for_vsg(target, step, subset)
    assert window_pts % 2 == 1
    assert vsg_size_px(window_pts, step, subset) >= target - 1e-9
    if window_pts > 1:
        assert vsg_size_px(window_pts - 2, step, subset) < target


def test_window_for_vsg_clamps_below_the_subset_size():
    """No window makes the gauge smaller than the subset; say so, do not lie."""
    assert window_pts_for_vsg(5.0, 5.0, 21) == 1
    assert vsg_size_px(1, 5.0, 21) == 21.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"window_pts": 4, "step_px": 5.0, "subset_px": 21}, "odd"),
        ({"window_pts": 0, "step_px": 5.0, "subset_px": 21}, ">= 1"),
        ({"window_pts": 5, "step_px": 0.0, "subset_px": 21}, "step_px"),
        ({"window_pts": 5, "step_px": 0.5, "subset_px": 21}, "step_px"),
        ({"window_pts": 5, "step_px": 5.0, "subset_px": 20}, "odd"),
        ({"window_pts": 5.5, "step_px": 5.0, "subset_px": 21}, "integer"),
    ],
)
def test_vsg_rejects_impossible_parameters(kwargs, message):
    with pytest.raises(ValueError, match=message):
        vsg_size_px(**kwargs)


def test_compute_strain_cannot_be_called_without_a_vsg_size():
    """``@vsg_px`` is mandatory in the schema, so it is never defaulted."""
    u, v = affine_displacement(UNIFORM_F)
    with pytest.raises(TypeError, match="subset_px"):
        compute_strain(u, v, step_px=STEP)
    with pytest.raises(TypeError, match="step_px"):
        compute_strain(u, v, subset_px=SUBSET)


def test_schema_attributes_carry_the_units_the_report_needs():
    field = strain_of(
        *affine_displacement(UNIFORM_F),
        StrainParams(window_pts=9),
        image_scale_px_per_mm=16.35,
    )
    attrs = field.schema_attrs()

    assert set(attrs) >= set(STRAIN_REQUIRED_ATTRS)
    assert attrs["tensor"] in STRAIN_TENSORS
    assert attrs["method"] in STRAIN_METHODS
    assert attrs["tensor"] == "green_lagrange"
    assert attrs["method"] == "local_plane_fit"
    assert attrs["window_pts"] == 9
    assert attrs["vsg_px"] == 61.0
    assert attrs["vsg_mm"] == pytest.approx(61.0 / 16.35)


def test_vsg_mm_is_absent_for_an_uncalibrated_analysis():
    """IR1-F4 section 10 item 3: no calibration, no attribute at all."""
    field = strain_of(*affine_displacement(UNIFORM_F))
    assert field.vsg_mm is None
    assert "vsg_mm" not in field.schema_attrs()


def test_quadratic_order_is_reported_as_savitzky_golay():
    field = strain_of(*affine_displacement(UNIFORM_F), StrainParams(fit_order="quadratic"))
    assert field.method == "savitzky_golay"
    assert field.schema_attrs()["method"] in STRAIN_METHODS


def test_with_window_supports_a_vsg_sweep():
    params = StrainParams()
    sizes = [params.with_window(w).vsg_px(STEP, SUBSET) for w in (3, 5, 9, 15)]
    assert sizes == [31.0, 41.0, 61.0, 91.0]
    assert params.window_pts == 5  # the original is untouched


# --------------------------------------------------------------------------- #
# The frozen calling surface
# --------------------------------------------------------------------------- #


def test_strain_field_keeps_the_frozen_layout():
    """IR1-F3 section 6: names, order and the flat per-POI point order."""
    field = strain_of(*affine_displacement(UNIFORM_F))
    names = [f.name for f in dataclasses.fields(field)]
    assert names[:8] == [
        "exx",
        "eyy",
        "exy",
        "tensor",
        "method",
        "window_pts",
        "vsg_px",
        "grid_shape",
    ]
    assert field.grid_shape == (NY, NX)
    assert field.n_points == NY * NX
    assert field.exx.shape == (NY * NX,)
    assert isinstance(field.vsg_px, float)
    # Row major, y outer, x inner -- the same order as ICGNResult's arrays.
    assert field.as_grid("exx")[7, 11] == field.exx[7 * NX + 11]


def test_strain_params_keep_the_frozen_signature():
    """IR1-F3 section 4, including the registered S1 default of uniform weights."""
    params = StrainParams()
    assert [f.name for f in dataclasses.fields(params)][:4] == [
        "window_pts",
        "tensor",
        "weighting",
        "min_valid_fraction",
    ]
    assert (params.window_pts, params.tensor) == (5, "green_lagrange")
    assert (params.weighting, params.min_valid_fraction) == ("uniform", 0.5)
    assert params.method == "local_plane_fit"
    with pytest.raises(dataclasses.FrozenInstanceError):
        params.window_pts = 7


def test_derived_fields_follow_the_frozen_formulas():
    field = strain_of(*affine_displacement(UNIFORM_F))
    exx, eyy, exy = field.exx, field.eyy, field.exy
    mean, radius = 0.5 * (exx + eyy), np.hypot(0.5 * (exx - eyy), exy)

    np.testing.assert_allclose(field.e1, mean + radius, atol=1e-18)
    np.testing.assert_allclose(field.e2, mean - radius, atol=1e-18)
    np.testing.assert_allclose(
        field.theta_p, 0.5 * np.arctan2(2.0 * exy, exx - eyy), atol=1e-18
    )
    np.testing.assert_allclose(field.gamma_max, field.e1 - field.e2, atol=1e-18)
    np.testing.assert_allclose(field.gamma_xy, 2.0 * exy, atol=1e-18)


def test_as_grid_reshapes_every_per_poi_field_including_tensors():
    field = strain_of(*affine_displacement(UNIFORM_F))
    assert field.as_grid("e1").shape == (NY, NX)
    assert field.as_grid("E").shape == (NY, NX, 2, 2)
    assert field.as_grid("F").shape == (NY, NX, 2, 2)
    with pytest.raises(ValueError, match="per-POI array"):
        field.as_grid("vsg_px")


def test_gradient_detail_is_optional_and_says_so_when_missing():
    """A StrainField rebuilt from stored components still answers the frozen
    questions; only the extras that need the fit raise."""
    stored = strain_of(*affine_displacement(UNIFORM_F))
    rebuilt = StrainField(
        exx=stored.exx,
        eyy=stored.eyy,
        exy=stored.exy,
        tensor=stored.tensor,
        method=stored.method,
        window_pts=stored.window_pts,
        vsg_px=stored.vsg_px,
        grid_shape=stored.grid_shape,
    )
    np.testing.assert_allclose(rebuilt.e1, stored.e1, atol=0)
    np.testing.assert_allclose(rebuilt.von_mises, stored.von_mises, atol=0)
    with pytest.raises(ValueError, match="PLS detail"):
        _ = rebuilt.rotation


def test_as_schema_dict_covers_the_documented_datasets():
    field = strain_of(*affine_displacement(UNIFORM_F))
    datasets = field.as_schema_dict()
    assert set(datasets) == {
        "exx",
        "eyy",
        "exy",
        "e1",
        "e2",
        "theta_p",
        "gamma_max",
        "von_mises",
    }
    assert all(a.shape == (field.n_points,) for a in datasets.values())


# --------------------------------------------------------------------------- #
# Interop and validation
# --------------------------------------------------------------------------- #


def test_grid_from_points_round_trips_a_correlator_poi_list():
    """The adapter between the correlator's flat POI arrays and the PLS fitter."""
    from hl3.correlate import ICGNParams, make_grid

    params = ICGNParams(subset_radius=10, step=5)
    poi = make_grid((240, 320), params)
    truth_u = 0.01 * poi[:, 0] + 0.004 * poi[:, 1]
    truth_v = -0.002 * poi[:, 0] - 0.003 * poi[:, 1]

    xs, ys, (u, v) = grid_from_points(poi[:, 0], poi[:, 1], [truth_u, truth_v])
    assert u.shape == (ys.size, xs.size)
    assert np.all(np.isfinite(u))
    np.testing.assert_allclose(np.diff(xs), params.step, atol=0)

    field = compute_strain(
        u,
        v,
        step_px=float(params.step),
        subset_px=subset_px_from_radius(params.subset_radius),
    )
    F = np.array([[1.01, 0.004], [-0.002, 0.997]])
    assert_uniform(interior(field.as_grid("E")), green_lagrange_strain(F))
    assert field.vsg_px == 41.0
    # POI order survives the round trip: strain index i is correlator point i.
    assert field.n_points == poi.shape[0]


def test_grid_from_points_reports_holes_as_nan():
    x = np.array([0.0, 5.0, 0.0])
    y = np.array([0.0, 0.0, 5.0])
    _, _, (grid,) = grid_from_points(x, y, [np.array([1.0, 2.0, 3.0])])
    np.testing.assert_allclose(grid, [[1.0, 2.0], [3.0, np.nan]])


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (((0.0, 1.0), (0.0,), [(0.0,)]), "same length"),
        (((0.0, 1.0), (0.0, 1.0), [(0.0,)]), "one value per POI"),
        (((0.0, 1.0, 5.0), (0.0, 0.0, 0.0), [(0.0, 1.0, 2.0)]), "regular grid"),
        (((0.0, 0.0), (0.0, 0.0), [(0.0, 1.0)]), "same grid cell"),
        (((np.nan, 1.0), (0.0, 0.0), [(0.0, 1.0)]), "finite"),
    ],
)
def test_grid_from_points_rejects_a_grid_it_cannot_rebuild(args, message):
    x, y, values = args
    with pytest.raises(ValueError, match=message):
        grid_from_points(np.array(x), np.array(y), [np.array(v) for v in values])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"window_pts": 4}, "odd"),
        ({"window_pts": 1}, ">= 3"),
        ({"fit_order": "cubic"}, "fit_order"),
        ({"weighting": "triangular"}, "weighting"),
        ({"weighting": "gaussian", "sigma": 0.0}, "sigma"),
        ({"step_px": 0.0}, "step_px"),
        ({"step_px": float("inf")}, "step_px"),
        ({"neighbor_min": 0}, "neighbor_min"),
    ],
)
def test_pls_gradients_rejects_broken_calls(kwargs, message):
    u, v = affine_displacement(UNIFORM_F)
    with pytest.raises(ValueError, match=message):
        pls_gradients(u, v, **kwargs)


def test_pls_gradients_rejects_mismatched_or_non_grid_input():
    u, v = affine_displacement(UNIFORM_F)
    with pytest.raises(ValueError, match="2-D"):
        pls_gradients(u.ravel(), v.ravel())
    with pytest.raises(ValueError, match="same shape"):
        pls_gradients(u, v[:-1])
    with pytest.raises(ValueError, match="same shape"):
        pls_gradients(u, v, valid=np.ones((3, 3), dtype=bool))
    with pytest.raises(ValueError, match="boolean"):
        pls_gradients(u, v, valid=np.ones(u.shape))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tensor": "cauchy"}, "tensor"),
        ({"fit_order": "cubic"}, "fit_order"),
        ({"window_pts": 6}, "odd"),
        ({"window_pts": 1}, ">= 3"),
        ({"weighting": "boxcar"}, "weighting"),
        ({"sigma": -1.0}, "sigma"),
        ({"min_valid_fraction": 0.0}, "frac"),
    ],
)
def test_strain_params_reject_impossible_configurations(kwargs, message):
    with pytest.raises(ValueError, match=message):
        StrainParams(**kwargs)


def test_strain_tensor_dispatch_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="tensor must be one of"):
        strain_tensor(np.eye(2), "hooke")
    with pytest.raises(ValueError, match=r"\(\.\.\., 2, 2\)"):
        green_lagrange_strain(np.zeros((3, 3)))


def test_every_supported_tensor_name_is_schema_legal():
    """Gate G-S1-STR-1: names must match the schema vocabulary exactly."""
    assert set(strain.TENSOR_KINDS) <= set(STRAIN_TENSORS)
    assert {"engineering", "green_lagrange"} <= set(strain.TENSOR_KINDS)


def test_default_neighbor_min_follows_the_half_window_rule():
    assert neighbor_min_for(5) == 13  # ceil(0.5 * 25)
    assert neighbor_min_for(9) == 41
    assert neighbor_min_for(5, 1.0) == 25
    # Never below the number of coefficients, whatever fraction is asked for.
    assert StrainParams(window_pts=3, min_valid_fraction=0.01).neighbor_min == 1


def test_public_api_is_importable_and_complete():
    missing = [name for name in strain.__all__ if not hasattr(strain, name)]
    assert missing == []
    assert isinstance(strain_of(*affine_displacement(UNIFORM_F)), StrainField)
