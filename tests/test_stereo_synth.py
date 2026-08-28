"""Synthetic-stereo tests for :mod:`hl3.stereo`.

Covers the T0 (unit / closed-form versus analytic truth) and part of the T2
(noise floor and covariance agreement) rows of the test matrix in spec section
14.3. Everything is closed-loop synthetic with exactly known truth, seeded, and
NumPy only, so it runs in a few seconds on the CPU-only CI box.

The second half of the file tests the module's behaviour on input that is *not*
clean, which is the case every real dataset presents:

* dropped points -- a non-finite pixel must yield a ``nan`` world point and
  leave its neighbours alone, never abort the batch;
* degenerate geometry -- must be reported through the covariance, not hidden
  behind a plausible finite number;
* broken calls -- must raise with a message naming the offending value;
* algebraic invariances that any correct implementation has to satisfy
  regardless of the particular synthetic rig used here.

Not covered here, by design: lens distortion, Zhang planar calibration,
checkerboard corner detection, and any real Challenge imagery. See the module
docstrings in :mod:`hl3.stereo.calibrate` for the scope boundary, and
``test_stereo_package_ships_no_distortion_implementation`` for the check that
keeps that boundary honest.
"""

from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

# Allow running against a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import hl3.stereo as stereo  # noqa: E402
from hl3.stereo import (  # noqa: E402
    Camera,
    StereoRig,
    add_pixel_noise,
    camera_center,
    cheirality_mask,
    decompose_projection,
    epipolar_distance,
    fundamental_from_projections,
    intrinsics,
    look_at_extrinsics,
    make_stereo_rig,
    position_sigma,
    project,
    project_with_depth,
    projection_matrix,
    reconstruction_error,
    relative_pose,
    reprojection_residuals,
    reprojection_rmse,
    resection_dlt,
    rq3,
    run_synthetic_experiment,
    sampson_correct,
    sampson_distance,
    synth_complex_surface,
    synth_planar_target,
    synth_target_poses,
    triangulate_dlt,
    triangulate_midpoint,
    triangulate_multiview_dlt,
    triangulate_nonlinear,
    triangulate_optimal,
    triangulation_covariance,
    triangulation_quality_mask,
    umeyama,
    visible_mask,
)

SEED = 20260828
MM_TO_UM = 1e3


@pytest.fixture(scope="module")
def rig():
    return make_stereo_rig()


@pytest.fixture(scope="module")
def scene(rig):
    """Visible surface points plus their exact projections in both cameras."""
    X = synth_complex_surface(n_side=21)
    keep = visible_mask(rig.left, X, margin_px=8.0) & visible_mask(
        rig.right, X, margin_px=8.0
    )
    X = X[keep]
    return X, rig.left.project(X), rig.right.project(X)


@pytest.fixture(scope="module")
def calibration_object(rig):
    """Union of several planar board poses, i.e. a non-coplanar 3D target."""
    board = synth_planar_target()
    X = np.concatenate(
        [board @ R.T + t for R, t in synth_target_poses(n_poses=14, seed=SEED)]
    )
    keep = visible_mask(rig.left, X, margin_px=4.0) & visible_mask(
        rig.right, X, margin_px=4.0
    )
    return X[keep]


# --------------------------------------------------------------------------- #
# Camera model
# --------------------------------------------------------------------------- #


def test_rig_geometry_matches_requested_configuration(rig):
    assert rig.baseline_mm == pytest.approx(254.0, rel=1e-12)
    assert rig.stereo_angle_deg == pytest.approx(22.177, abs=1e-3)
    assert rig.left.K[0, 0] == pytest.approx(35.0 / 3.45e-3, rel=1e-12)
    assert rig.left.K[0, 1] == 0.0  # skew locked at zero (spec S4.1 L0)


def test_camera_center_is_projection_null_space(rig):
    for cam in (rig.left, rig.right):
        assert camera_center(cam.P) == pytest.approx(cam.C, abs=1e-9)
        assert cam.P @ np.append(cam.C, 1.0) == pytest.approx(np.zeros(3), abs=1e-6)


def test_look_at_points_optical_axis_at_target():
    C = np.array([100.0, -30.0, -500.0])
    target = np.array([5.0, 2.0, 0.0])
    R, t = look_at_extrinsics(C, target)
    assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-12)
    assert R @ R.T == pytest.approx(np.eye(3), abs=1e-12)
    # The target must land exactly on the principal point, i.e. at (0, 0)
    # in normalised camera coordinates.
    x_cam = R @ target + t
    assert x_cam[:2] / x_cam[2] == pytest.approx(np.zeros(2), abs=1e-12)
    assert x_cam[2] == pytest.approx(np.linalg.norm(target - C), rel=1e-12)


def test_look_at_rejects_degenerate_up_vector():
    with pytest.raises(ValueError, match="parallel"):
        look_at_extrinsics([0.0, 0.0, -10.0], [0.0, 0.0, 0.0], up=(0.0, 0.0, 1.0))


def test_visible_mask_rejects_points_outside_and_behind(rig):
    X = np.array([[0.0, 0.0, 0.0], [1e4, 0.0, 0.0], [0.0, 0.0, -1e4]])
    m = visible_mask(rig.left, X)
    assert m[0] and not m[1] and not m[2]


# --------------------------------------------------------------------------- #
# T0: triangulation against analytic truth
# --------------------------------------------------------------------------- #


def test_noise_free_triangulation_hits_numerical_floor(rig, scene):
    X, xL, xR = scene
    PL, PR = rig.left.P, rig.right.P
    solutions = {
        "midpoint": triangulate_midpoint(PL, PR, xL, xR),
        "dlt": triangulate_dlt(PL, PR, xL, xR),
        "sampson": triangulate_optimal(PL, PR, xL, xR),
        "nonlinear": triangulate_nonlinear([PL, PR], [xL, xR]),
    }
    for name, X_est in solutions.items():
        err = reconstruction_error(X_est, X)
        assert err["max_um"] < 1e-3, f"{name}: {err['max_um']} um"
        assert reprojection_rmse([PL, PR], [xL, xR], X_est) < 1e-8


def test_dlt_normalisation_does_not_change_the_answer(rig, scene):
    _, xL, xR = scene
    a = triangulate_dlt(rig.left.P, rig.right.P, xL, xR, normalize=True)
    b = triangulate_dlt(rig.left.P, rig.right.P, xL, xR, normalize=False)
    assert np.max(np.linalg.norm(a - b, axis=1)) < 1e-6


def test_triangulate_multiview_rejects_bad_input(rig, scene):
    _, xL, xR = scene
    PL, PR = rig.left.P, rig.right.P
    with pytest.raises(ValueError, match="same number of views"):
        triangulate_multiview_dlt([PL, PR], [xL])
    with pytest.raises(ValueError, match="at least 2 views"):
        triangulate_multiview_dlt([PL], [xL])
    with pytest.raises(ValueError, match="same number of points"):
        triangulate_multiview_dlt([PL, PR], [xL, xR[:-3]])


def test_cheirality_mask_flags_points_behind_a_camera(rig, scene):
    X, _, _ = scene
    PL, PR = rig.left.P, rig.right.P
    assert cheirality_mask([PL, PR], X).all()
    behind = X.copy()
    behind[:5, 2] = -5000.0  # far behind both camera centres
    m = cheirality_mask([PL, PR], behind)
    assert not m[:5].any()
    assert m[5:].all()


# --------------------------------------------------------------------------- #
# Epipolar geometry
# --------------------------------------------------------------------------- #


def test_fundamental_matrix_is_rank_two_and_annihilates_true_matches(rig, scene):
    _, xL, xR = scene
    F = fundamental_from_projections(rig.left.P, rig.right.P)
    s = np.linalg.svd(F, compute_uv=False)
    assert s[2] / s[0] < 1e-12, "F must be rank 2"
    assert np.max(sampson_distance(F, xL, xR)) < 1e-8
    assert np.max(epipolar_distance(F, xL, xR)) < 1e-8


def test_sampson_correction_projects_noisy_matches_onto_epipolar_lines(rig, scene):
    _, xL0, xR0 = scene
    rng = np.random.default_rng(SEED)
    sigma = 0.05
    xL = add_pixel_noise(xL0, sigma, rng)
    xR = add_pixel_noise(xR0, sigma, rng)
    F = fundamental_from_projections(rig.left.P, rig.right.P)

    before = sampson_distance(F, xL, xR)
    xLc, xRc = sampson_correct(F, xL, xR, iters=10)
    after = sampson_distance(F, xLc, xRc)

    assert np.sqrt(np.mean(before**2)) == pytest.approx(sigma, rel=0.15)
    assert np.max(after) < 1e-9
    # The correction is the minimal shift that restores the constraint, so it
    # must stay on the order of the noise it removes.
    shift = np.linalg.norm(xLc - xL, axis=1)
    assert np.max(shift) < 6.0 * sigma


def test_sampson_corrected_rays_intersect_exactly(rig, scene):
    _, xL0, xR0 = scene
    rng = np.random.default_rng(SEED + 1)
    xL = add_pixel_noise(xL0, 0.05, rng)
    xR = add_pixel_noise(xR0, 0.05, rng)
    PL, PR = rig.left.P, rig.right.P
    X = triangulate_optimal(PL, PR, xL, xR)
    # Corrected rays are coplanar, so DLT and the ray midpoint must coincide.
    F = fundamental_from_projections(PL, PR)
    xLc, xRc = sampson_correct(F, xL, xR, iters=10)
    Xm = triangulate_midpoint(PL, PR, xLc, xRc)
    assert np.max(np.linalg.norm(X - Xm, axis=1)) * MM_TO_UM < 1e-3


# --------------------------------------------------------------------------- #
# T2: noise propagation and uncertainty
# --------------------------------------------------------------------------- #


def _mc_triangulate(rig, xL0, xR0, sigma, trials, rng):
    PL, PR = rig.left.P, rig.right.P
    return np.stack(
        [
            triangulate_nonlinear(
                [PL, PR],
                [add_pixel_noise(xL0, sigma, rng), add_pixel_noise(xR0, sigma, rng)],
            )
            for _ in range(trials)
        ]
    )


def test_three_d_error_scales_linearly_with_image_noise(rig, scene):
    X, xL0, xR0 = scene
    rng = np.random.default_rng(SEED)
    rms = []
    for sigma in (0.01, 0.02, 0.04):
        est = _mc_triangulate(rig, xL0, xR0, sigma, 20, rng)
        rms.append(
            reconstruction_error(
                est.reshape(-1, 3), np.tile(X, (est.shape[0], 1))
            )["rms_um"]
        )
    assert rms[1] / rms[0] == pytest.approx(2.0, rel=0.1)
    assert rms[2] / rms[1] == pytest.approx(2.0, rel=0.1)


def test_predicted_covariance_matches_monte_carlo_spread(rig, scene):
    X, xL0, xR0 = scene
    rng = np.random.default_rng(SEED)
    sigma = 0.02
    est = _mc_triangulate(rig, xL0, xR0, sigma, 120, rng)

    Sig = triangulation_covariance([rig.left.P, rig.right.P], X, sigma_px=sigma)
    predicted = np.sqrt(np.diagonal(Sig, axis1=1, axis2=2))
    empirical = est.std(axis=0, ddof=1)

    # Spec section 14.3 row T2 asks for agreement within +/-20%; the mean over
    # the field is far tighter than that and is the useful regression sentinel.
    ratio = empirical / predicted
    assert np.mean(ratio) == pytest.approx(1.0, abs=0.05)
    assert np.max(np.abs(ratio - 1.0)) < 0.5

    # Covariances must be symmetric positive definite.
    assert np.allclose(Sig, np.transpose(Sig, (0, 2, 1)), atol=1e-18)
    assert np.all(np.linalg.eigvalsh(Sig) > 0)


def test_out_of_plane_uncertainty_dominates_in_plane(rig, scene):
    X, _, _ = scene
    Sig = triangulation_covariance([rig.left.P, rig.right.P], X, sigma_px=0.02)
    sd = np.sqrt(np.diagonal(Sig, axis1=1, axis2=2)).mean(axis=0)
    # A converged stereo pair is always weakest along the viewing direction; if
    # this ever inverts, the rig or the jacobian sign convention is wrong.
    assert sd[2] > 3.0 * sd[0]
    assert sd[2] > 3.0 * sd[1]


def test_stereo_error_budget_is_the_right_order_for_the_challenge_geometry(rig, scene):
    """A sanity anchor against the public Stereo-DIC Challenge 1.0 numbers.

    The Challenge reports a typical displacement error of about +/-15 um at a
    match quality of roughly +/-0.25 px for a 16.35 px/mm setup. Driving this
    synthetic rig at 0.25 px of image noise must land in the same tens-of-microns
    band; a result orders of magnitude away means the synthetic geometry has
    drifted away from anything physical.
    """
    X, xL0, xR0 = scene
    rng = np.random.default_rng(SEED)
    est = _mc_triangulate(rig, xL0, xR0, 0.25, 10, rng)
    err = reconstruction_error(est.reshape(-1, 3), np.tile(X, (est.shape[0], 1)))
    assert 20.0 < err["rms_um"] < 150.0


def test_third_camera_reduces_the_error(rig, scene):
    X, xL0, xR0 = scene
    R3, t3 = look_at_extrinsics(
        [0.0, -220.0, -648.0], [0.0, 0.0, 0.0], up=(0.0, 0.0, -1.0)
    )
    cam3 = Camera(rig.left.K.copy(), R3, t3, rig.left.width, rig.left.height)
    keep = visible_mask(cam3, X, margin_px=8.0)
    assert keep.all(), "third view must see the whole test patch"

    Ps = [rig.left.P, rig.right.P, cam3.P]
    xs0 = [xL0, xR0, cam3.project(X)]
    rng = np.random.default_rng(SEED)
    sigma = 0.02
    two, three = [], []
    for _ in range(20):
        xs = [add_pixel_noise(x, sigma, rng) for x in xs0]
        two.append(triangulate_nonlinear(Ps[:2], xs[:2]))
        three.append(triangulate_nonlinear(Ps, xs))
    Xt = np.tile(X, (20, 1))
    e2 = reconstruction_error(np.concatenate(two), Xt)["rms_um"]
    e3 = reconstruction_error(np.concatenate(three), Xt)["rms_um"]
    assert e3 < 0.9 * e2


def test_nonlinear_refinement_never_worsens_the_reprojection_cost(rig, scene):
    _, xL0, xR0 = scene
    rng = np.random.default_rng(SEED)
    xL = add_pixel_noise(xL0, 0.1, rng)
    xR = add_pixel_noise(xR0, 0.1, rng)
    Ps, xs = [rig.left.P, rig.right.P], [xL, xR]
    X_dlt = triangulate_dlt(*Ps, *xs)
    X_nl = triangulate_nonlinear(Ps, xs, X0=X_dlt)
    assert reprojection_rmse(Ps, xs, X_nl) <= reprojection_rmse(Ps, xs, X_dlt) + 1e-12


# --------------------------------------------------------------------------- #
# Pose algebra
# --------------------------------------------------------------------------- #


def test_rq3_factorises_into_upper_triangular_times_orthogonal():
    rng = np.random.default_rng(SEED)
    M = rng.normal(size=(3, 3))
    R, Q = rq3(M)
    assert R @ Q == pytest.approx(M, abs=1e-12)
    assert Q @ Q.T == pytest.approx(np.eye(3), abs=1e-12)
    assert R[1, 0] == pytest.approx(0.0, abs=1e-12)
    assert R[2, 0] == pytest.approx(0.0, abs=1e-12)
    assert R[2, 1] == pytest.approx(0.0, abs=1e-12)


def test_decompose_projection_inverts_projection_matrix(rig):
    for cam in (rig.left, rig.right):
        K, R, t = decompose_projection(cam.P)
        assert K == pytest.approx(cam.K, rel=1e-10, abs=1e-8)
        assert R == pytest.approx(cam.R, abs=1e-12)
        assert t == pytest.approx(cam.t, abs=1e-9)
        assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-12)
        assert projection_matrix(K, R, t) == pytest.approx(cam.P, rel=1e-9)


def test_decompose_projection_is_insensitive_to_overall_sign(rig):
    K, R, _ = decompose_projection(-rig.left.P)
    assert K == pytest.approx(rig.left.K, rel=1e-10, abs=1e-8)
    assert R == pytest.approx(rig.left.R, abs=1e-12)


def test_umeyama_recovers_a_known_rigid_transform():
    rng = np.random.default_rng(SEED)
    A = rng.normal(scale=40.0, size=(200, 3))
    R_true, _ = look_at_extrinsics([13.0, -7.0, -95.0], [1.0, 2.0, 3.0])
    t_true = np.array([12.0, -3.5, 7.25])
    B = A @ R_true.T + t_true

    R, t, s = umeyama(A, B)
    assert s == pytest.approx(1.0)
    assert R == pytest.approx(R_true, abs=1e-10)
    assert t == pytest.approx(t_true, abs=1e-9)
    assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-12)


def test_umeyama_recovers_scale_when_asked():
    rng = np.random.default_rng(SEED)
    A = rng.normal(scale=40.0, size=(200, 3))
    R_true, _ = look_at_extrinsics([13.0, -7.0, -95.0], [1.0, 2.0, 3.0])
    B = 1.37 * (A @ R_true.T) + np.array([1.0, 2.0, 3.0])
    _, _, s = umeyama(A, B, with_scale=True)
    assert s == pytest.approx(1.37, rel=1e-9)


def test_reconstruction_error_separates_frame_offset_from_shape_error(rig, scene):
    """Spec section 7.3: a frame misalignment must not read as measurement error."""
    X, _, _ = scene
    angle = np.radians(0.3)
    c, s = np.cos(angle), np.sin(angle)
    R_off = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    X_shifted = X @ R_off.T + np.array([0.5, -0.25, 0.1])

    raw = reconstruction_error(X_shifted, X)
    aligned = reconstruction_error(X_shifted, X, align=True)

    # Unaligned, a 0.3 degree twist plus a half-millimetre shift looks like
    # hundreds of micrometres of error; aligned, it vanishes.
    assert raw["rms_um"] > 300.0
    assert aligned["rms_um"] < 1e-6
    assert aligned["align_rotation_deg"] == pytest.approx(0.3, abs=1e-9)
    assert aligned["align_translation_um"] > 100.0


# --------------------------------------------------------------------------- #
# Linear resection ("calibration" stand-in)
# --------------------------------------------------------------------------- #


def test_resection_recovers_exact_cameras_from_noise_free_correspondences(
    rig, calibration_object
):
    for cam in (rig.left, rig.right):
        x = cam.project(calibration_object)
        K, R, t = decompose_projection(resection_dlt(calibration_object, x))
        assert K[0, 0] == pytest.approx(cam.K[0, 0], rel=1e-9)
        assert K[1, 1] == pytest.approx(cam.K[1, 1], rel=1e-9)
        assert K[0, 2] == pytest.approx(cam.K[0, 2], abs=1e-6)
        assert K[1, 2] == pytest.approx(cam.K[1, 2], abs=1e-6)
        assert K[0, 1] == pytest.approx(0.0, abs=1e-6)
        assert R == pytest.approx(cam.R, abs=1e-9)
        assert t == pytest.approx(cam.t, abs=1e-6)


def test_resection_rejects_degenerate_inputs(rig):
    planar = synth_planar_target()
    planar_world = planar + np.array([0.0, 0.0, 0.0])
    x = rig.left.project(planar_world)
    with pytest.raises(ValueError, match="non-coplanar"):
        resection_dlt(planar_world, x)
    with pytest.raises(ValueError, match="at least 6"):
        resection_dlt(np.zeros((4, 3)), np.zeros((4, 2)))
    with pytest.raises(ValueError, match="same number of rows"):
        resection_dlt(np.zeros((8, 3)), np.zeros((7, 2)))


def test_resection_pose_error_under_realistic_detection_noise(rig, calibration_object):
    rng = np.random.default_rng(SEED)
    sigma = 0.02
    cams = []
    for cam in (rig.left, rig.right):
        x = add_pixel_noise(cam.project(calibration_object), sigma, rng)
        K, R, t = decompose_projection(resection_dlt(calibration_object, x))
        cams.append((K, R, t))
        assert abs(K[0, 0] - cam.K[0, 0]) / cam.K[0, 0] < 1e-3
        assert abs(K[0, 2] - cam.K[0, 2]) < 3.0
        dR = R @ cam.R.T
        angle = np.degrees(np.arccos(np.clip((np.trace(dR) - 1) / 2, -1, 1)))
        assert angle < 0.05

    R_rel, t_rel = relative_pose(cams[0][1], cams[0][2], cams[1][1], cams[1][2])
    R_rel_t, t_rel_t = relative_pose(rig.left.R, rig.left.t, rig.right.R, rig.right.t)
    assert np.linalg.norm(t_rel - t_rel_t) * MM_TO_UM < 300.0
    assert np.degrees(
        np.arccos(np.clip((np.trace(R_rel @ R_rel_t.T) - 1) / 2, -1, 1))
    ) < 0.05


def test_calibration_error_propagates_to_a_small_surface_error(
    rig, scene, calibration_object
):
    """Cameras recovered from a noisy target still reconstruct the surface well.

    With a pure pinhole model and 0.02 px detection noise over ~850 target
    points the residual calibration error contributes well under a micrometre of
    3D error -- an order of magnitude below the matching term. That ordering is
    an artefact of the distortion-free model, not a claim about real rigs; see
    the Round 2 report.
    """
    X, xL0, xR0 = scene
    rng = np.random.default_rng(SEED)
    Ps = []
    for cam in (rig.left, rig.right):
        x = add_pixel_noise(cam.project(calibration_object), 0.02, rng)
        Ps.append(resection_dlt(calibration_object, x))

    X_est = triangulate_nonlinear(Ps, [xL0, xR0])
    err = reconstruction_error(X_est, X)
    aligned = reconstruction_error(X_est, X, align=True)
    assert err["rms_um"] < 5.0
    assert aligned["rms_um"] <= err["rms_um"] + 1e-9


# --------------------------------------------------------------------------- #
# Reproducibility
# --------------------------------------------------------------------------- #


def test_pipeline_is_deterministic_for_a_fixed_seed(rig, scene):
    X, xL0, xR0 = scene

    def once():
        rng = np.random.default_rng(4242)
        xL = add_pixel_noise(xL0, 0.03, rng)
        xR = add_pixel_noise(xR0, 0.03, rng)
        return triangulate_nonlinear([rig.left.P, rig.right.P], [xL, xR])

    assert np.array_equal(once(), once())
    assert reconstruction_error(once(), X)["rms_um"] > 0.0


def test_synthetic_geometry_is_stable():
    X = synth_complex_surface(n_side=21)
    assert X.shape == (441, 3)
    assert np.ptp(X[:, 2]) == pytest.approx(15.95, abs=1e-9)
    assert synth_planar_target(9, 7, 10.0).shape == (63, 3)
    poses = synth_target_poses(n_poses=6, seed=1)
    assert len(poses) == 6
    for R, t in poses:
        assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-12)
        assert t.shape == (3,)


def test_intrinsics_helper_matches_manual_construction():
    K = intrinsics(35.0, 3.45e-3, 2448, 2048)
    assert K[0, 0] == pytest.approx(K[1, 1])
    assert K[0, 2] == pytest.approx(1223.5)
    assert K[1, 2] == pytest.approx(1023.5)
    K2 = intrinsics(35.0, 3.45e-3, 2448, 2048, principal_point=(10.0, 20.0))
    assert (K2[0, 2], K2[1, 2]) == (10.0, 20.0)


def test_project_agrees_with_explicit_matrix_algebra(rig, scene):
    X, xL, _ = scene
    Xh = np.hstack([X, np.ones((X.shape[0], 1))])
    manual = (rig.left.P @ Xh.T).T
    manual = manual[:, :2] / manual[:, 2:3]
    assert project(rig.left.P, X) == pytest.approx(manual, abs=1e-12)
    assert xL == pytest.approx(manual, abs=1e-12)


# --------------------------------------------------------------------------- #
# Missing measurements: a dropped point must not take the field with it
# --------------------------------------------------------------------------- #

_RUNGS = {
    "midpoint": lambda PL, PR, xL, xR: triangulate_midpoint(PL, PR, xL, xR),
    "dlt": lambda PL, PR, xL, xR: triangulate_dlt(PL, PR, xL, xR),
    "dlt_unnormalised": lambda PL, PR, xL, xR: triangulate_dlt(
        PL, PR, xL, xR, normalize=False
    ),
    "sampson": lambda PL, PR, xL, xR: triangulate_optimal(PL, PR, xL, xR),
    "nonlinear": lambda PL, PR, xL, xR: triangulate_nonlinear([PL, PR], [xL, xR]),
}


@pytest.mark.parametrize("rung", sorted(_RUNGS))
def test_a_dropped_point_does_not_destroy_the_rest_of_the_field(rig, scene, rung):
    """One unmatched POI must cost exactly one POI.

    Every rung except the midpoint pools all points into a single batched SVD
    or 3x3 solve, and the Hartley normaliser averages over the whole view, so a
    lone ``nan`` used to surface as ``LinAlgError: SVD did not converge`` for
    the entire field. Real correlation fields always contain dropped points, so
    this is the difference between a usable module and an unusable one.
    """
    X, xL0, xR0 = scene
    PL, PR = rig.left.P, rig.right.P
    dropped = [1, 7, len(X) - 1]
    xL = xL0.copy()
    xL[dropped] = np.nan

    X_est = _RUNGS[rung](PL, PR, xL, xR0)

    assert X_est.shape == X.shape
    bad = np.zeros(len(X), dtype=bool)
    bad[dropped] = True
    assert np.all(np.isnan(X_est[bad])), "dropped points must come back as nan"
    assert np.all(np.isfinite(X_est[~bad])), "surviving points must stay finite"
    # And the survivors must be numerically identical to a run with no dropout,
    # i.e. the dropped points did not perturb their neighbours' solution.
    reference = _RUNGS[rung](PL, PR, xL0, xR0)
    assert X_est[~bad] == pytest.approx(reference[~bad], abs=1e-9)


@pytest.mark.parametrize("rung", sorted(_RUNGS))
def test_a_fully_dropped_field_returns_all_nan(rig, scene, rung):
    _, xL0, xR0 = scene
    X_est = _RUNGS[rung](rig.left.P, rig.right.P, np.full_like(xL0, np.nan), xR0)
    assert X_est.shape == (len(xL0), 3)
    assert np.all(np.isnan(X_est))


@pytest.mark.parametrize("rung", sorted(_RUNGS))
def test_empty_input_returns_an_empty_result(rig, rung):
    empty = np.zeros((0, 2))
    X_est = _RUNGS[rung](rig.left.P, rig.right.P, empty, empty)
    assert X_est.shape == (0, 3)


def test_reconstruction_error_reports_coverage_alongside_the_error(rig, scene):
    """Dropping points must move the coverage count, not just improve the RMS."""
    X, _, _ = scene
    X_est = X.copy()
    X_est[:, 2] += 0.01  # a uniform 10 um offset
    X_est[:4] = np.nan

    err = reconstruction_error(X_est, X)
    assert err["n_points"] == len(X)
    assert err["n_finite"] == len(X) - 4
    # The surviving points still carry their real error rather than nan.
    assert err["rms_um"] == pytest.approx(10.0, rel=1e-9)

    nothing = reconstruction_error(np.full_like(X, np.nan), X)
    assert nothing["n_finite"] == 0
    assert np.isnan(nothing["rms_um"])


def test_reprojection_rmse_ignores_dropped_points(rig, scene):
    X, xL0, xR0 = scene
    Ps, xs = [rig.left.P, rig.right.P], [xL0, xR0]
    X_holed = X.copy()
    X_holed[:3] = np.nan
    assert reprojection_rmse(Ps, xs, X_holed) < 1e-8
    assert np.isnan(reprojection_rmse(Ps, xs, np.full_like(X, np.nan)))


def test_dropped_points_survive_the_covariance_and_the_quality_gate(rig, scene):
    X, _, _ = scene
    Ps = [rig.left.P, rig.right.P]
    X_holed = X.copy()
    X_holed[5] = np.nan

    Sig = triangulation_covariance(Ps, X_holed, sigma_px=0.02)
    assert np.all(np.isnan(Sig[5]))
    assert np.all(np.isfinite(np.delete(Sig, 5, axis=0)))

    keep = triangulation_quality_mask(Ps, X_holed, sigma_px=0.02)
    assert not keep[5]
    assert keep[np.arange(len(X)) != 5].all()


# --------------------------------------------------------------------------- #
# Degenerate geometry must be reported, not hidden
# --------------------------------------------------------------------------- #


def test_covariance_is_infinite_where_the_geometry_cannot_locate_the_point(rig, scene):
    """A rank-deficient point gets ``inf``, and does not abort the batch.

    A single view fixes a ray, not a position, so the covariance along that ray
    is unbounded. Returning ``inf`` says exactly that; raising ``LinAlgError``
    for the whole array -- the old behaviour -- loses the other points too, and
    a finite number would be a lie the quality gate then believes.
    """
    X, _, _ = scene
    one_view = triangulation_covariance([rig.left.P], X, sigma_px=0.02)
    assert np.all(np.isinf(one_view))
    assert np.all(np.isinf(position_sigma(one_view)))

    # Two copies of the same camera carry exactly as much information as one.
    doubled = triangulation_covariance([rig.left.P, rig.left.P], X, sigma_px=0.02)
    assert np.all(np.isinf(doubled))

    # A real pair still works, and mixing a bad point into a good field only
    # costs that point.
    Ps = [rig.left.P, rig.right.P]
    mixed = np.vstack([X, [[0.0, 0.0, 5e11]]])
    sig = position_sigma(triangulation_covariance(Ps, mixed, sigma_px=0.02))
    assert np.all(np.isfinite(sig[:-1]))
    assert sig[-1] > 1e3


def test_quality_mask_rejects_the_far_field_minimum(rig, scene):
    """The failure mode no residual threshold can catch (spec S5.1 stage D).

    Corrupted near-parallel rays admit a genuine low-residual optimum out near
    infinity. Reprojection error and Sampson distance both look excellent
    there, so only the position covariance can reject it.
    """
    X, _, _ = scene
    Ps = [rig.left.P, rig.right.P]
    # The cameras sit at z = -648 mm looking towards +z, so depth increases
    # with z and the surface lives near z = 0.
    behind = np.array([[0.0, 0.0, -1e4]])      # behind both camera centres
    far = np.array([[0.0, 0.0, 5e6]])          # far in front, unlocatable
    probe = np.vstack([X[:5], behind, far])

    keep = triangulation_quality_mask(Ps, probe, sigma_px=2.0,
                                      max_position_sigma_mm=1.0)
    assert keep[:5].all(), "good points must survive the gate"
    assert not keep[5], "cheirality must reject the point behind the cameras"
    assert not keep[6], "the covariance must reject the far-field point"

    # Without the covariance ceiling the far point passes: that is precisely
    # why the ceiling exists, and cheirality alone is a strictly weaker gate.
    assert triangulation_quality_mask(Ps, probe, sigma_px=2.0)[6]


def test_position_sigma_is_the_root_of_the_covariance_trace(rig, scene):
    X, _, _ = scene
    Sig = triangulation_covariance([rig.left.P, rig.right.P], X, sigma_px=0.02)
    assert position_sigma(Sig) == pytest.approx(
        np.sqrt(np.trace(Sig, axis1=1, axis2=2)), rel=1e-12
    )
    with pytest.raises(ValueError, match=r"shape \(N, 3, 3\)"):
        position_sigma(np.eye(3))


def test_coincident_cameras_have_no_epipolar_geometry(rig):
    """The unnormalised F is tiny rather than zero, so it must be caught early.

    ``fundamental_from_projections`` divides by ``norm(F)`` at the end. For a
    coincident pair that norm is pure rounding error, and the division would
    rescale it into a unit-norm matrix indistinguishable from a real answer.
    """
    with pytest.raises(ValueError, match="camera centres coincide"):
        fundamental_from_projections(rig.left.P, rig.left.P)
    with pytest.raises(ValueError, match="camera centres coincide"):
        fundamental_from_projections(rig.left.P, 2.5 * rig.left.P)


def test_epipolar_metrics_report_nan_rather_than_a_perfect_score(rig, scene):
    """A degenerate epipolar line must read as "undefined", not as "perfect".

    The module used to floor the denominator at the smallest denormal, which
    turns "this quality field has no opinion here" into "this match is exactly
    right" -- a fail-open on the field whose entire job is to flag bad matches,
    and one that a downstream threshold cannot possibly notice.

    ``F`` here is contrived so that the epipolar lines in both directions have
    an exactly zero gradient. A real rig only approaches that state, near the
    epipole, where the metric degrades continuously rather than snapping to
    zero.
    """
    _, xL, xR = scene
    # Both F x1 and F.T x2 come out as (0, 0, 1): lines with no direction.
    F_degenerate = np.diag([0.0, 0.0, 1.0])
    for metric in (sampson_distance, epipolar_distance):
        d = metric(F_degenerate, xL[:4], xR[:4])
        assert np.all(np.isnan(d)), f"{metric.__name__} scored a degenerate line"
        assert not np.any(d == 0.0)

    with pytest.raises(ValueError, match="zero matrix"):
        sampson_distance(np.zeros((3, 3)), xL, xR)
    with pytest.raises(ValueError, match="non-finite"):
        sampson_distance(np.full((3, 3), np.nan), xL, xR)


def test_midpoint_returns_nan_for_parallel_rays():
    """Zero disparity in a fronto-parallel pair means the rays never meet."""
    K = intrinsics(35.0, 3.45e-3, 2448, 2048)
    P1 = projection_matrix(K, np.eye(3), np.array([0.0, 0.0, 600.0]))
    P2 = projection_matrix(K, np.eye(3), np.array([-100.0, 0.0, 600.0]))
    principal = np.array([[K[0, 2], K[1, 2]]])
    disparate = np.array([[K[0, 2] - 300.0, K[1, 2]]])

    assert np.all(np.isnan(triangulate_midpoint(P1, P2, principal, principal)))
    assert np.all(np.isfinite(triangulate_midpoint(P1, P2, disparate, principal)))


def test_projection_is_nan_on_the_principal_plane():
    """Zero projective depth has no image, and must not divide by a denormal.

    The guard is on exact zero. A point merely *close* to the principal plane
    genuinely does project to a huge finite coordinate, and clamping that would
    be wrong; rejecting it is the covariance gate's job, not the projector's.
    """
    K = intrinsics(35.0, 3.45e-3, 2448, 2048)
    P = projection_matrix(K, np.eye(3), np.zeros(3))
    on_plane = np.array([[10.0, -4.0, 0.0]])
    x, w = project_with_depth(P, on_plane)
    assert w[0] == 0.0
    assert np.all(np.isnan(x))

    near_plane = np.array([[10.0, -4.0, 1e-9]])
    x_near, _ = project_with_depth(P, near_plane)
    assert np.all(np.isfinite(x_near))
    assert np.abs(x_near).max() > 1e6

    # The camera centre is the physically meaningful zero-depth point.
    C = camera_center(P)
    assert C == pytest.approx(np.zeros(3), abs=1e-9)
    assert abs(project_with_depth(P, C[None, :])[1][0]) < 1e-9


def test_cheirality_gate_fails_closed_with_no_cameras(scene):
    """A safety gate with nothing to check against must not pass everything."""
    X, _, _ = scene
    with pytest.raises(ValueError, match="at least one view"):
        cheirality_mask([], X)


# --------------------------------------------------------------------------- #
# Algebraic invariances any correct implementation must satisfy
# --------------------------------------------------------------------------- #


def test_triangulation_is_equivariant_under_a_rigid_world_transform(rig, scene):
    """Move the world and the cameras together; the answer must move with them.

    This exercises the whole chain -- camera centres, ray directions, the DLT
    normaliser and Gauss--Newton -- against a truth that is independent of the
    particular synthetic rig, so it catches frame-convention errors that a
    fixed-geometry regression test would happily confirm.
    """
    X, _, _ = scene
    angle = np.radians(37.0)
    c, s = np.cos(angle), np.sin(angle)
    Rw = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    tw = np.array([120.0, -35.0, 60.0])

    Y = X @ Rw.T + tw
    Ps = []
    for cam in (rig.left, rig.right):
        R2 = cam.R @ Rw.T
        Ps.append(projection_matrix(cam.K, R2, cam.t - R2 @ tw))

    ys = [project(P, Y) for P in Ps]
    # Same images as before the transform, so the pixels carry no extra clue.
    assert ys[0] == pytest.approx(rig.left.project(X), abs=1e-6)

    for solver in (
        lambda: triangulate_dlt(Ps[0], Ps[1], ys[0], ys[1]),
        lambda: triangulate_midpoint(Ps[0], Ps[1], ys[0], ys[1]),
        lambda: triangulate_nonlinear(Ps, ys),
    ):
        assert np.max(np.linalg.norm(solver() - Y, axis=1)) * MM_TO_UM < 1e-3


@pytest.mark.parametrize("alpha", [2.5, -1.0, 1e-3])
def test_triangulation_is_invariant_to_projective_rescaling(rig, scene, alpha):
    """``P`` and ``alpha P`` are the same camera, so they must give one answer."""
    X, xL, xR = scene
    PL, PR = rig.left.P, rig.right.P
    for solver in (triangulate_dlt, triangulate_midpoint, triangulate_optimal):
        a = solver(PL, PR, xL, xR)
        b = solver(alpha * PL, PR, xL, xR)
        assert np.max(np.linalg.norm(a - b, axis=1)) * MM_TO_UM < 1e-3
        assert np.max(np.linalg.norm(a - X, axis=1)) * MM_TO_UM < 1e-3


def test_sampson_correction_is_idempotent_once_converged(rig, scene):
    _, xL0, xR0 = scene
    rng = np.random.default_rng(SEED)
    xL = add_pixel_noise(xL0, 0.05, rng)
    xR = add_pixel_noise(xR0, 0.05, rng)
    F = fundamental_from_projections(rig.left.P, rig.right.P)

    a1, b1 = sampson_correct(F, xL, xR, iters=10)
    a2, b2 = sampson_correct(F, a1, b1, iters=10)
    assert np.max(np.abs(a2 - a1)) < 1e-9
    assert np.max(np.abs(b2 - b1)) < 1e-9

    # iters=0 is a no-op, and the early exit must not change the answer.
    a0, b0 = sampson_correct(F, xL, xR, iters=0)
    assert np.array_equal(a0, xL) and np.array_equal(b0, xR)
    a3, _ = sampson_correct(F, xL, xR, iters=50, tol=0.0)
    assert np.max(np.abs(a3 - a1)) < 1e-9


def test_view_weights_pull_the_solution_towards_the_trusted_camera(rig, scene):
    """Per-view weights are the spec S9 multi-system hook, and were untested."""
    X, xL0, xR0 = scene
    R3, t3 = look_at_extrinsics(
        [0.0, -220.0, -648.0], [0.0, 0.0, 0.0], up=(0.0, 0.0, -1.0)
    )
    cam3 = Camera(rig.left.K.copy(), R3, t3, rig.left.width, rig.left.height)
    Ps = [rig.left.P, rig.right.P, cam3.P]

    rng = np.random.default_rng(SEED)
    xs = [
        add_pixel_noise(xL0, 0.3, rng),
        add_pixel_noise(xR0, 0.3, rng),
        cam3.project(X),  # the trustworthy view: exact pixels
    ]

    equal = triangulate_nonlinear(Ps, xs)
    trusted = triangulate_nonlinear(Ps, xs, weights=[1.0, 1.0, 1e4])
    residual = [
        np.sqrt(np.mean(reprojection_residuals(Ps, xs, Y)[2] ** 2)) for Y in
        (equal, trusted)
    ]
    assert residual[1] < 0.2 * residual[0]

    with pytest.raises(ValueError, match="one value per view"):
        triangulate_nonlinear(Ps, xs, weights=[1.0, 1.0])
    with pytest.raises(ValueError, match="finite and non-negative"):
        triangulate_nonlinear(Ps, xs, weights=[1.0, 1.0, -1.0])


# --------------------------------------------------------------------------- #
# Input contracts: broken calls raise, and say what was wrong
# --------------------------------------------------------------------------- #


def _bad_calls(rig, X, xL, xR):
    """``(label, thunk, expected message fragment)`` for every guarded entry point."""
    PL, PR = rig.left.P, rig.right.P
    cam = rig.left
    K, R, t = cam.K, cam.R, cam.t
    F = fundamental_from_projections(PL, PR)
    rng = np.random.default_rng(0)
    nan33 = np.full((3, 3), np.nan)
    blind = Camera(K, R, t)  # constructed without a sensor extent

    def case(label, fragment, thunk):
        return label, thunk, fragment

    return [
        # Shapes and finiteness of camera parameters.
        case("P shape", "3x4 projection", lambda: project(np.eye(3), X)),
        case("P non-finite", "non-finite", lambda: project(np.full((3, 4), np.inf), X)),
        case("Ps not a sequence", "sequence of 3x4", lambda: cheirality_mask(PL, X)),
        case("K shape", "K must be 3x3", lambda: projection_matrix(np.eye(2), R, t)),
        case("t shape", "3-vector", lambda: projection_matrix(K, R, np.zeros(4))),
        case("F shape", "3x3", lambda: sampson_distance(np.eye(4), xL, xR)),
        # Shapes of the data arrays. A wrong-width array is never reinterpreted.
        case("pixels are points", "(N, 2)", lambda: triangulate_dlt(PL, PR, X, xR)),
        case("points are pixels", "(N, 3)", lambda: project(PL, xL)),
        case("points are 3-D", "(N, 3)", lambda: project(PL, X[None, ...])),
        case("x1 vs x2 length", "same number of points",
             lambda: sampson_distance(F, xL, xR[:-1])),
        case("X0 length", "one point per observation",
             lambda: triangulate_nonlinear([PL, PR], [xL, xR], X0=X[:-1])),
        case("X vs xs length", "one point per observation",
             lambda: reprojection_rmse([PL, PR], [xL, xR], X[:-1])),
        case("recon shapes", "same shape", lambda: reconstruction_error(X, X[:-1])),
        case("umeyama shapes", "same shape", lambda: umeyama(X, X[:-1])),
        case("pose_errors shape", "must be 3x3",
             lambda: stereo.pose_errors(np.eye(2), t, R, t)),
        # Solver settings.
        case("negative iters", "non-negative",
             lambda: triangulate_nonlinear([PL, PR], [xL, xR], iters=-1)),
        case("sigma zero", "strictly positive",
             lambda: triangulation_covariance([PL, PR], X, sigma_px=0.0)),
        case("sigma per-view count", "one value per view",
             lambda: triangulation_covariance([PL, PR], X, sigma_px=[0.1, 0.2, 0.3])),
        case("gate ceiling", "must be positive",
             lambda: triangulation_quality_mask([PL, PR], X,
                                                max_position_sigma_mm=0.0)),
        case("noise sigma", "non-negative", lambda: add_pixel_noise(xL, -0.1, rng)),
        case("noise rng", "Generator", lambda: add_pixel_noise(xL, 0.1, 42)),
        # Physically impossible camera models and rigs.
        case("R reflected", "proper rotation", lambda: Camera(K, -np.eye(3), t)),
        case("R not orthonormal", "orthonormal",
             lambda: Camera(K, np.full((3, 3), 0.5), t)),
        case("camera t shape", "3-vector", lambda: Camera(K, R, np.zeros(2))),
        case("rig standoff", "non-negative", lambda: StereoRig(cam, rig.right, -1.0)),
        case("zero focal", "focal_mm must be positive",
             lambda: intrinsics(0.0, 3.45e-3, 8, 8)),
        case("negative pitch", "pixel_pitch_mm must be",
             lambda: intrinsics(35.0, -1e-3, 8, 8)),
        case("empty sensor", "must be >= 1", lambda: intrinsics(35.0, 3.45e-3, 0, 8)),
        case("zero baseline", "baseline_mm", lambda: make_stereo_rig(baseline_mm=0.0)),
        case("camera on its target", "coincide",
             lambda: look_at_extrinsics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])),
        case("zero up vector", "non-zero",
             lambda: look_at_extrinsics([0, 0, -9], [0, 0, 0], up=(0, 0, 0))),
        case("visible without a sensor", "no sensor extent",
             lambda: visible_mask(blind, X)),
        case("negative margin", "non-negative",
             lambda: visible_mask(cam, X, margin_px=-1.0)),
        # Synthetic geometry generators.
        case("surface too small", "n_side must be >= 2",
             lambda: synth_complex_surface(n_side=1)),
        case("board too small", "must be >= 2", lambda: synth_planar_target(1, 7)),
        case("zero spacing", "spacing_mm", lambda: synth_planar_target(9, 7, 0.0)),
        case("no poses", "n_poses must be >= 1",
             lambda: synth_target_poses(n_poses=0)),
        # Estimators fed data they cannot use.
        case("umeyama too few", "at least 3 point pairs",
             lambda: umeyama(X[:2], X[:2])),
        case("umeyama non-finite", "finite",
             lambda: umeyama(np.full_like(X, np.nan), X)),
        case("resection non-finite", "finite",
             lambda: resection_dlt(np.full((8, 3), np.nan), np.zeros((8, 2)))),
        case("decompose singular", "singular",
             lambda: decompose_projection(np.zeros((3, 4)))),
        case("decompose non-finite", "non-finite",
             lambda: decompose_projection(np.full((3, 4), np.inf))),
        case("F is zero", "zero matrix", lambda: sampson_distance(np.zeros((3, 3)),
                                                                 xL, xR)),
        case("F is nan", "non-finite", lambda: sampson_distance(nan33, xL, xR)),
    ]


def test_every_guarded_entry_point_raises_with_a_useful_message(rig, scene):
    """One sweep over the module's input contracts.

    Each of these used to produce silent nonsense, a cryptic NumPy broadcast
    error or a bare ``LinAlgError``. The assertion is on the message as well as
    the type: an exception that does not name the offending value costs a
    debugging session to interpret. Collecting all failures before asserting
    keeps one regression from masking the rest.
    """
    X, xL, xR = scene
    failures = []
    for label, call, fragment in _bad_calls(rig, X, xL, xR):
        try:
            call()
        except (ValueError, TypeError) as exc:
            if fragment not in str(exc):
                failures.append(f"{label}: message {str(exc)!r} lacks {fragment!r}")
        except Exception as exc:
            failures.append(f"{label}: raised {type(exc).__name__} instead: {exc}")
        else:
            failures.append(f"{label}: did not raise")
    assert not failures, "\n".join(failures)


def test_the_public_api_never_emits_a_runtime_warning(rig, scene):
    """Warning-free on the paths that used to divide by zero or average nan.

    A ``RuntimeWarning`` in a numerical library is a latent silent-nonsense bug:
    it fires once, gets filtered, and the caller keeps the polluted array.
    """
    X, xL0, xR0 = scene
    Ps = [rig.left.P, rig.right.P]
    holed = xL0.copy()
    holed[::7] = np.nan
    empty = np.zeros((0, 2))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for xs in ([holed, xR0], [np.full_like(xL0, np.nan), xR0], [empty, empty]):
            for solver in _RUNGS.values():
                Y = solver(Ps[0], Ps[1], xs[0], xs[1])
                reprojection_rmse(Ps, xs, Y)
                triangulation_quality_mask(Ps, Y, sigma_px=0.02,
                                           max_position_sigma_mm=1.0)
                position_sigma(triangulation_covariance(Ps, Y, sigma_px=0.02))
        far = np.vstack([X, [[0.0, 0.0, -1e9]], [[0.0, 0.0, 1e9]]])
        triangulation_quality_mask(Ps, far, sigma_px=2.0, max_position_sigma_mm=1.0)


# --------------------------------------------------------------------------- #
# Scope boundary: the microscope distortion layer must stay at zero code
# --------------------------------------------------------------------------- #


def test_stereo_package_ships_no_distortion_implementation():
    """Spec S10.4 / gate L-7: zero implementation until the FTO opinion exists.

    The check is on *definitions*, not on mentions: the module docstrings state
    the exclusion in prose, and that prose is required to stay. Deleting the
    disclaimer must not be a way to make this test pass.
    """
    forbidden = re.compile(
        r"^\s*(?:def|class)\s+\w*"
        r"(?:distort|brown|conrady|radial|tangential|prism|fisheye|telecentric"
        r"|microscop)\w*",
        re.IGNORECASE | re.MULTILINE,
    )
    package = Path(stereo.__file__).parent
    sources = sorted(package.glob("*.py"))
    assert sources, "the stereo package must have source files to scan"

    for path in sources:
        text = path.read_text(encoding="utf-8")
        hits = forbidden.findall(text)
        assert not hits, f"{path.name} defines distortion machinery: {hits}"
        assert "patent-clearance" in text, (
            f"{path.name} must keep the spec S10.4 scope exclusion in its docstring"
        )

    banned = ("distort", "brown", "conrady", "microscop")
    exported = [n for n in stereo.__all__ if any(b in n.lower() for b in banned)]
    assert not exported, f"public API exposes distortion entry points: {exported}"


def test_public_api_matches_what_the_package_actually_exports():
    """``__all__`` and the module namespace must not drift apart."""
    missing = [n for n in stereo.__all__ if not hasattr(stereo, n)]
    assert not missing, f"__all__ names that do not exist: {missing}"
    assert stereo.__all__ == sorted(stereo.__all__)
    for module in (stereo.triangulate, stereo.calibrate):
        undefined = [n for n in module.__all__ if not hasattr(module, n)]
        assert not undefined, f"{module.__name__}.__all__ is stale: {undefined}"


# --------------------------------------------------------------------------- #
# End-to-end study driver
# --------------------------------------------------------------------------- #

_SMALL_STUDY = dict(
    sigmas_px=(0.0, 0.02),
    degenerate_sigma_px=2.0,
    n_trials=2,
    n_side=9,
    n_target_poses=4,
    pose_counts=(3,),
    pose_repeats=1,
    seed=7,
)


@pytest.fixture(scope="module")
def small_study():
    return run_synthetic_experiment(**_SMALL_STUDY)


def test_run_synthetic_experiment_produces_a_complete_result_tree(small_study):
    """The whole driver had no test at all; this is its smoke and shape check."""
    r = small_study
    assert set(r) == {
        "rig", "noise_free", "noise_sweep", "covariance", "epipolar",
        "multiview", "calibration", "pose_sweep", "error_budget", "degeneracy",
    }
    assert r["rig"]["baseline_mm"] == pytest.approx(254.0, rel=1e-12)
    assert r["rig"]["n_points"] > 0

    for name, m in r["noise_free"].items():
        assert m["rms_um"] < 1e-3, f"{name} lost the numerical floor"
    for method in ("midpoint", "dlt", "sampson", "nonlinear"):
        assert r["noise_sweep"]["0.02"][method]["rms_um"] > 0.0
        assert r["degeneracy"][method]["kept_fraction"] <= 1.0

    assert r["error_budget"]["combined"]["rms_um"] > 0.0
    assert r["calibration"]["exact"]["left"]["focal_err_rel"] < 1e-6
    assert r["multiview"]["three_view"]["rms_um"] < r["multiview"]["two_view"]["rms_um"]


def test_run_synthetic_experiment_is_bit_for_bit_reproducible(small_study):
    """Every number in the study must be a function of the seed alone."""

    def flatten(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from flatten(v, f"{prefix}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from flatten(v, f"{prefix}[{i}]")
        else:
            yield prefix, node

    a = dict(flatten(small_study))
    b = dict(flatten(run_synthetic_experiment(**_SMALL_STUDY)))
    assert a.keys() == b.keys()
    drift = {k: (a[k], b[k]) for k in a if a[k] != b[k] and a[k] == a[k]}
    assert not drift, f"non-deterministic entries: {drift}"


def test_a_different_seed_moves_the_noise_but_not_the_geometry(small_study):
    other = run_synthetic_experiment(**{**_SMALL_STUDY, "seed": 99})
    assert other["rig"] == small_study["rig"]
    assert other["noise_free"] == small_study["noise_free"]
    assert (
        other["noise_sweep"]["0.02"]["nonlinear"]["rms_um"]
        != small_study["noise_sweep"]["0.02"]["nonlinear"]["rms_um"]
    )
