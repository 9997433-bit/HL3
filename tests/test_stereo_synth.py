"""Synthetic-stereo tests for :mod:`hl3.stereo` (R2-O2).

Covers the T0 (unit / closed-form versus analytic truth) and part of the T2
(noise floor and covariance agreement) rows of the test matrix in spec section
14.3. Everything is closed-loop synthetic with exactly known truth, seeded, and
NumPy only, so it runs in a few seconds on the CPU-only CI box.

Not covered here, by design: lens distortion, Zhang planar calibration,
checkerboard corner detection, and any real Challenge imagery. See the module
docstrings in :mod:`hl3.stereo.calibrate` for the scope boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Allow running against a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hl3.stereo import (  # noqa: E402
    Camera,
    add_pixel_noise,
    camera_center,
    cheirality_mask,
    decompose_projection,
    epipolar_distance,
    fundamental_from_projections,
    intrinsics,
    look_at_extrinsics,
    make_stereo_rig,
    project,
    projection_matrix,
    reconstruction_error,
    relative_pose,
    reprojection_rmse,
    resection_dlt,
    rq3,
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
    with pytest.raises(ValueError, match="at least two views"):
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
