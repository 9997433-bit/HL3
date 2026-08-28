"""Synthetic-stereo tests for :mod:`hl3.stereo.match`.

The fixture is a closed-loop optical experiment with no free parameters: a
band-limited texture is painted on a *world plane*, and each camera image is
produced by back-projecting every one of its pixels onto that plane and reading
the texture there. Both views are therefore exact perspective renderings of the
same physical surface -- no resampling of one image into the other, no assumed
disparity -- so the true correspondence of any left-image pixel is known in
closed form and the matcher can be scored in absolute pixels rather than
against itself.

Covered here: the nominal-plane disparity prediction, the correspondence
accuracy of the IC-GN refinement, the epipolar quality fields and the gate
built on them, the seeding modes, and the hand-off to
:mod:`hl3.stereo.triangulate`.

Deliberately not covered, because the module deliberately does not implement
them: lens distortion, epipolar *curve* sampling, image rectification, the
quadratic shape function, adaptive subsets, and anything to do with stereo
microscopy (spec section 10.4, patent-clearance opinion pending). The
package-wide scope check lives in ``test_stereo_synth.py``.
"""

from __future__ import annotations

import math
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
from hl3.correlate import ICGNParams, Status  # noqa: E402
from hl3.stereo import (  # noqa: E402
    Camera,
    EpipolarResiduals,
    MatchSeed,
    StereoMatchParams,
    StereoMatchResult,
    StereoRig,
    epipolar_residuals,
    make_stereo_rig,
    match_stereo_pair,
    plane_disparity,
    project,
    reconstruction_error,
    rig_fundamental,
    triangulate_optimal,
)
from hl3.stereo import match as match_module  # noqa: E402

SEED = 20260828
WIDTH, HEIGHT = 360, 300
#: Tilt and depth offset of the specimen surface. Both matter: the tilt makes
#: the two views differ by more than a translation, and the depth offset takes
#: the surface off the plane the rig is aimed at, which is what gives the pair
#: a disparity worth seeding.
SURFACE_TILT_DEG = 15.0
SURFACE_OFFSET_MM = -8.0


# --------------------------------------------------------------------------- #
# Synthetic scene
# --------------------------------------------------------------------------- #


def _plane_frame(tilt_deg: float, offset_mm: float):
    """``(origin, e1, e2, normal, plane)`` for a plane tilted about the Y axis."""
    a = math.radians(tilt_deg)
    e1 = np.array([math.cos(a), 0.0, math.sin(a)])
    e2 = np.array([0.0, 1.0, 0.0])
    normal = np.cross(e1, e2)
    origin = np.array([0.0, 0.0, float(offset_mm)])
    plane = (*normal, -float(normal @ origin))
    return origin, e1, e2, normal, plane


def _waves(rng: np.random.Generator, n: int = 48):
    """Band-limited speckle: wave vectors in an annulus, random phases.

    A sum of sinusoids rather than a rendered blob field on purpose -- it is
    an analytic function of the in-plane coordinates, so both camera images are
    sampled from the *same* continuous texture and neither carries a
    resampling error the other does not.
    """
    wavelength = rng.uniform(0.8, 2.0, size=n)  # mm on the specimen surface
    angle = rng.uniform(0.0, np.pi, size=n)
    k = (2.0 * np.pi / wavelength)[:, None] * np.column_stack(
        (np.cos(angle), np.sin(angle))
    )
    return k, rng.uniform(0.0, 2.0 * np.pi, size=n)


def _texture(s: np.ndarray, t: np.ndarray, waves) -> np.ndarray:
    k, phase = waves
    arg = np.outer(s, k[:, 0]) + np.outer(t, k[:, 1]) + phase[None, :]
    raw = np.cos(arg).sum(axis=1) / math.sqrt(k.shape[0] / 2.0)
    return 128.0 + 45.0 * raw


def _backproject(P: np.ndarray, pixels: np.ndarray, origin, normal) -> np.ndarray:
    """World points where the rays through ``pixels`` meet the plane.

    Written out here rather than reused from the module under test: the
    prediction :func:`hl3.stereo.plane_disparity` makes is exactly what this
    computes, so sharing an implementation would make that test vacuous.
    """
    M = P[:, :3]
    center = -np.linalg.solve(M, P[:, 3])
    rays = np.linalg.solve(M, np.hstack([pixels, np.ones((pixels.shape[0], 1))]).T).T
    lam = ((origin - center) @ normal) / (rays @ normal)
    return center[None, :] + lam[:, None] * rays


def _render(P: np.ndarray, shape, frame, waves) -> np.ndarray:
    origin, e1, e2, normal, _ = frame
    height, width = shape
    gx, gy = np.meshgrid(
        np.arange(width, dtype=float), np.arange(height, dtype=float)
    )
    pixels = np.column_stack((gx.ravel(), gy.ravel()))
    X = _backproject(P, pixels, origin, normal)
    d = X - origin
    return _texture(d @ e1, d @ e2, waves).reshape(height, width)


@pytest.fixture(scope="module")
def rig():
    """A converged pair at roughly 5 px/mm; Challenge-like angle, small sensor."""
    return make_stereo_rig(
        baseline_mm=254.0,
        standoff_mm=648.0,
        focal_mm=35.0,
        pixel_pitch_mm=35.0 / 3240.0,
        width=WIDTH,
        height=HEIGHT,
    )


@pytest.fixture(scope="module")
def frame():
    return _plane_frame(SURFACE_TILT_DEG, SURFACE_OFFSET_MM)


@pytest.fixture(scope="module")
def images(rig, frame):
    waves = _waves(np.random.default_rng(SEED))
    shape = (HEIGHT, WIDTH)
    return (
        _render(rig.left.P, shape, frame, waves),
        _render(rig.right.P, shape, frame, waves),
    )


@pytest.fixture(scope="module")
def params(frame):
    """Subset ~5 mm across, seeded on the true surface plane.

    The margin is wider than the kernel's default because a stereo AOI has to
    leave room for the disparity itself: a POI 14 px from the left edge has its
    matching subset 6 px off the right image and is correctly reported
    ``OUT_OF_BOUNDS``, which would otherwise show up as an accuracy result.
    """
    return StereoMatchParams(
        icgn=ICGNParams(subset_radius=12, step=20, zncc_min=0.9),
        seed=MatchSeed.PLANE,
        seed_plane=frame[4],
        max_sampson_px=0.5,
        margin=40,
    )


@pytest.fixture(scope="module")
def matched(rig, images, params):
    return match_stereo_pair(images[0], images[1], rig, params)


def _truth(rig, frame, pixels):
    """``(X_world, x_right)`` for left-image ``pixels`` lying on the surface."""
    origin, _, _, normal, _ = frame
    X = _backproject(rig.left.P, pixels, origin, normal)
    return X, project(rig.right.P, X)


# --------------------------------------------------------------------------- #
# Nominal-plane prediction
# --------------------------------------------------------------------------- #


def test_plane_disparity_is_the_exact_correspondence_on_the_plane(rig, frame):
    pixels = np.array(
        [[30.0, 30.0], [180.0, 150.0], [330.0, 270.0], [30.0, 270.0], [330.0, 30.0]]
    )
    _, expected = _truth(rig, frame, pixels)
    predicted = pixels + plane_disparity(rig, pixels, frame[4])
    assert np.allclose(predicted, expected, atol=1e-9)


def test_plane_disparity_is_large_enough_to_matter(rig, frame):
    """The seed is not decoration: unseeded, this pair is out of IC-GN's basin."""
    pixels = np.array([[30.0, 150.0], [180.0, 150.0], [330.0, 150.0]])
    shift = np.linalg.norm(plane_disparity(rig, pixels, frame[4]), axis=1)
    assert shift.max() > 20.0


def test_plane_disparity_accepts_a_bare_projection_pair(rig, frame):
    pixels = np.array([[100.0, 100.0], [250.0, 200.0]])
    from_rig = plane_disparity(rig, pixels, frame[4])
    from_pair = plane_disparity([rig.left.P, rig.right.P], pixels, frame[4])
    assert np.array_equal(from_rig, from_pair)


def test_plane_disparity_refuses_to_invent_a_seed_behind_the_cameras(rig):
    pixels = np.array([[100.0, 100.0], [250.0, 200.0]])
    behind = plane_disparity(rig, pixels, (0.0, 0.0, 1.0, 1000.0))
    assert np.all(np.isnan(behind))


def test_plane_disparity_rejects_a_degenerate_plane(rig):
    pixels = np.array([[100.0, 100.0]])
    with pytest.raises(ValueError, match="non-zero"):
        plane_disparity(rig, pixels, (0.0, 0.0, 0.0, 1.0))
    with pytest.raises(ValueError, match="nx, ny, nz, w"):
        plane_disparity(rig, pixels, (0.0, 0.0, 1.0))


# --------------------------------------------------------------------------- #
# Correspondence accuracy
# --------------------------------------------------------------------------- #


def test_match_recovers_the_true_correspondence(rig, frame, matched):
    keep = matched.accepted
    assert matched.accepted_fraction > 0.9
    _, expected = _truth(rig, frame, matched.left_xy[keep])
    error = np.linalg.norm(matched.right_xy[keep] - expected, axis=1)
    assert float(np.sqrt(np.mean(error**2))) < 0.02
    assert float(error.max()) < 0.1


def test_match_reports_high_correlation_on_accepted_points(matched):
    assert float(np.median(matched.zncc[matched.accepted])) > 0.999
    assert np.all(matched.status[matched.accepted] == int(Status.CONVERGED))


def test_accepted_points_are_a_subset_of_converged_points(matched):
    assert np.all(matched.valid[matched.accepted])
    assert matched.n_accepted == int(np.count_nonzero(matched.accepted))


def test_disparity_is_the_left_to_right_offset(matched):
    assert np.allclose(
        matched.disparity, matched.right_xy - matched.left_xy, atol=0.0
    )


# --------------------------------------------------------------------------- #
# Epipolar quality
# --------------------------------------------------------------------------- #


def test_epipolar_residuals_are_a_fraction_of_a_pixel(matched):
    keep = matched.accepted
    assert float(np.max(matched.sampson_px[keep])) < 0.05
    assert float(np.max(matched.epipolar_px[keep])) < 0.1
    # Unmatched points must not carry a score at all.
    assert np.all(np.isnan(matched.sampson_px[~matched.valid]))


def test_standalone_residuals_agree_with_the_result_fields(rig, matched):
    keep = matched.accepted
    residuals = epipolar_residuals(rig, matched.left_xy[keep], matched.right_xy[keep])
    assert isinstance(residuals, EpipolarResiduals)
    assert np.allclose(residuals.sampson_px, matched.sampson_px[keep])
    assert np.allclose(residuals.distance_px, matched.epipolar_px[keep])


def test_fundamental_matrix_comes_from_the_calibration(rig, matched):
    F = rig_fundamental(rig)
    assert np.allclose(F, matched.fundamental)
    assert np.isclose(np.linalg.norm(F), 1.0)
    # x_right.T F x_left == 0 on exact correspondences, to round-off.
    assert float(np.max(np.abs(np.linalg.det(F)))) < 1e-12


def test_gate_rejects_matches_pushed_off_their_epipolar_line(rig, frame, matched):
    """A correspondence displaced across the epipolar line must score badly."""
    keep = matched.accepted
    left = matched.left_xy[keep]
    X, right = _truth(rig, frame, left)
    F = rig_fundamental(rig)
    lines = np.hstack([left, np.ones((left.shape[0], 1))]) @ F.T
    normal = lines[:, :2] / np.hypot(lines[:, 0], lines[:, 1])[:, None]

    clean = epipolar_residuals(rig, left, right)
    pushed = epipolar_residuals(rig, left, right + 3.0 * normal)
    assert float(np.max(clean.sampson_px)) < 1e-6
    assert float(np.min(pushed.sampson_px)) > 1.0
    assert float(np.min(pushed.distance_px)) > 2.0
    assert X.shape == (left.shape[0], 3)


def test_gate_flags_a_miscalibrated_rig(images, rig, params):
    """Same images, a rig whose right camera is mis-aimed by 0.05 degrees.

    This is the failure the Sampson gate exists for. The correlator is just as
    happy -- the images did not change -- so convergence and ZNCC say nothing
    at all; only the residual against the *claimed* calibration moves, and at
    3240 px of focal length a twentieth of a degree of pitch is already several
    pixels of epipolar violation.
    """
    tilt = math.radians(0.05)
    pitch = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(tilt), -math.sin(tilt)],
            [0.0, math.sin(tilt), math.cos(tilt)],
        ]
    )
    center = rig.right.C
    rotated = pitch @ rig.right.R
    wrong = StereoRig(
        left=rig.left,
        right=Camera(rig.right.K, rotated, -rotated @ center, WIDTH, HEIGHT),
        standoff_mm=rig.standoff_mm,
    )
    result = match_stereo_pair(images[0], images[1], wrong, params)
    assert float(np.count_nonzero(result.valid)) / result.n_points > 0.9
    assert result.accepted_fraction < 0.2
    assert float(np.nanmedian(result.sampson_px)) > params.max_sampson_px


def test_an_infinite_gate_leaves_convergence_as_the_only_test(images, rig, params):
    from dataclasses import replace

    result = match_stereo_pair(
        images[0], images[1], rig, replace(params, max_sampson_px=math.inf)
    )
    assert np.array_equal(result.accepted, result.valid)


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #


def test_zero_seed_loses_the_points_the_plane_seed_keeps(images, rig, params, matched):
    from dataclasses import replace

    zeroed = match_stereo_pair(
        images[0], images[1], rig, replace(params, seed=MatchSeed.ZERO)
    )
    assert zeroed.accepted_fraction < 0.5 * matched.accepted_fraction
    assert zeroed.provenance["seed"] == "zero"


def test_a_wrong_nominal_plane_costs_points(images, rig, params):
    """Seeding on ``z = 0`` when the surface is tilted and 8 mm away from it."""
    from dataclasses import replace

    result = match_stereo_pair(
        images[0], images[1], rig, replace(params, seed_plane=(0.0, 0.0, 1.0, 0.0))
    )
    assert result.accepted_fraction < 0.9


def test_the_integer_search_finds_the_same_matches_as_the_plane_seed(
    images, rig, frame, params
):
    """``SOLVER`` seeding, i.e. FFT-CC, is an independent route to the answer."""
    from dataclasses import replace

    coarse = replace(
        params,
        icgn=ICGNParams(subset_radius=12, step=60, zncc_min=0.9, search_radius=40),
        seed=MatchSeed.SOLVER,
        # The FFT-CC window needs its own border, which make_grid's default
        # margin (subset + search + 2) already accounts for.
        margin=None,
    )
    result = match_stereo_pair(images[0], images[1], rig, coarse)
    assert result.provenance["seed"] == "solver"
    assert result.accepted_fraction > 0.8
    keep = result.accepted
    _, expected = _truth(rig, frame, result.left_xy[keep])
    assert float(np.max(np.linalg.norm(result.right_xy[keep] - expected, axis=1))) < 0.1


def test_auto_seeding_follows_the_availability_of_a_rig(images, rig, params):
    from dataclasses import replace

    auto = replace(params, seed=MatchSeed.AUTO)
    with_rig = match_stereo_pair(images[0], images[1], rig, auto)
    without_rig = match_stereo_pair(images[0], images[1], None, auto)
    assert with_rig.provenance["seed"] == "plane"
    assert without_rig.provenance["seed"] == "solver"


def test_an_explicit_initial_guess_overrides_the_seed_mode(
    images, rig, frame, params, matched
):
    guess = plane_disparity(rig, matched.left_xy, frame[4])
    result = match_stereo_pair(
        images[0],
        images[1],
        rig,
        params,
        points=matched.left_xy,
        initial_guess=guess,
    )
    assert result.provenance["seed"] == "explicit"
    assert np.allclose(result.right_xy, matched.right_xy, atol=1e-12)


def test_an_undefined_plane_prediction_degrades_to_zero_rather_than_raising(
    images, rig, params
):
    """A plane behind the rig predicts nothing; the run must still happen."""
    from dataclasses import replace

    result = match_stereo_pair(
        images[0],
        images[1],
        rig,
        replace(params, seed_plane=(0.0, 0.0, 1.0, 1000.0)),
    )
    assert result.provenance["seed_fallback_points"] == result.n_points
    assert result.n_points > 0


# --------------------------------------------------------------------------- #
# Working without a rig
# --------------------------------------------------------------------------- #


def test_match_without_a_rig_reports_no_epipolar_metrics(images, params):
    from dataclasses import replace

    result = match_stereo_pair(
        images[0], images[1], None, replace(params, seed=MatchSeed.SOLVER)
    )
    assert result.fundamental is None
    assert result.sampson_px is None
    assert result.epipolar_px is None
    assert np.array_equal(result.accepted, result.valid)
    assert result.provenance["has_rig"] is False
    assert result.provenance["epipolar_source"] is None
    assert math.isnan(result.summary()["sampson_px_rms"])


# --------------------------------------------------------------------------- #
# Hand-off to triangulation
# --------------------------------------------------------------------------- #


def test_masked_correspondences_triangulate_back_onto_the_surface(
    rig, frame, matched
):
    x_left, x_right = matched.correspondences()
    X_est = triangulate_optimal(rig.left.P, rig.right.P, x_left, x_right)

    keep = matched.accepted
    assert np.all(np.isnan(X_est[~keep]))
    X_true, _ = _truth(rig, frame, matched.left_xy[keep])
    error = reconstruction_error(X_est[keep], X_true)
    assert error["rms_um"] < 25.0
    assert error["max_um"] < 150.0


def test_sampson_corrected_pairs_sit_on_their_epipolar_lines(rig, matched):
    left, right = matched.correspondences(corrected=True)
    keep = matched.accepted
    residuals = epipolar_residuals(rig, left[keep], right[keep])
    assert float(np.max(residuals.sampson_px)) < 1e-9
    # The correction is a nudge, not a re-match.
    shift = np.linalg.norm(left[keep] - matched.left_xy[keep], axis=1)
    assert float(np.max(shift)) < 0.1


def test_unmasked_correspondences_keep_the_raw_values(matched):
    left, right = matched.correspondences(masked=False)
    assert np.array_equal(left, matched.left_xy)
    assert np.array_equal(right, matched.right_xy)
    assert np.all(np.isfinite(right))


def test_corrected_correspondences_need_a_rig(images, params):
    from dataclasses import replace

    result = match_stereo_pair(
        images[0], images[1], None, replace(params, seed=MatchSeed.SOLVER)
    )
    with pytest.raises(ValueError, match="Sampson-corrected"):
        result.correspondences(corrected=True)


def test_sampson_correction_can_be_switched_off(images, rig, params):
    from dataclasses import replace

    result = match_stereo_pair(
        images[0], images[1], rig, replace(params, sampson_iters=0)
    )
    assert result.left_corrected is None
    assert result.right_corrected is None


# --------------------------------------------------------------------------- #
# Reporting and reproducibility
# --------------------------------------------------------------------------- #


def test_summary_reports_coverage_and_geometry(matched):
    summary = matched.summary()
    assert summary["n_points"] == matched.n_points
    assert summary["n_accepted"] == matched.n_accepted
    assert summary["n_converged"] >= summary["n_accepted"]
    assert 0.0 < summary["accepted_fraction"] <= 1.0
    assert summary["zncc_median"] > 0.99
    assert summary["disparity_px_median"] > 1.0
    assert summary["sampson_px_rms"] <= summary["sampson_px_max"]
    assert summary["sampson_px_p95"] <= summary["sampson_px_max"]
    assert summary["status_counts"]["CONVERGED"] == summary["n_converged"]


def test_provenance_records_the_scope_boundaries(matched, rig):
    p = matched.provenance
    assert p["solver"] == "hl3.correlate.icgn_first_order"
    assert p["shape_function"] == "first_order_affine"
    assert p["distortion_model"] == "none_pinhole_l0"
    assert p["rectified"] is False
    assert p["deterministic"] is True
    assert p["epipolar_source"] == "analytic_from_projections"
    assert p["baseline_mm"] == pytest.approx(rig.baseline_mm)
    assert p["image_shape"] == (HEIGHT, WIDTH)


def test_matching_is_bit_for_bit_reproducible(images, rig, params):
    first = match_stereo_pair(images[0], images[1], rig, params)
    second = match_stereo_pair(images[0], images[1], rig, params)
    assert np.array_equal(first.right_xy, second.right_xy)
    assert np.array_equal(first.accepted, second.accepted)
    assert np.array_equal(first.sampson_px, second.sampson_px, equal_nan=True)


def test_status_counts_and_field_lengths_agree(matched):
    assert matched.left_xy.shape == matched.right_xy.shape == (matched.n_points, 2)
    assert matched.sampson_px.shape == (matched.n_points,)
    assert sum(matched.status_counts().values()) == matched.n_points


# --------------------------------------------------------------------------- #
# Broken calls
# --------------------------------------------------------------------------- #


def test_second_order_is_refused_rather_than_silently_ignored():
    with pytest.raises(ValueError, match="first-order only"):
        StereoMatchParams(icgn=ICGNParams(shape_order=2))


@pytest.mark.parametrize(
    "kwargs, match",
    (
        ({"max_sampson_px": 0.0}, "max_sampson_px"),
        ({"max_sampson_px": -1.0}, "max_sampson_px"),
        ({"sampson_iters": -1}, "sampson_iters"),
        ({"margin": -3}, "margin"),
        ({"seed_plane": (0.0, 0.0, 0.0, 1.0)}, "non-zero"),
        ({"seed_plane": (0.0, 0.0, np.nan, 1.0)}, "finite"),
    ),
)
def test_bad_parameters_raise(kwargs, match):
    with pytest.raises(ValueError, match=match):
        StereoMatchParams(**kwargs)


def test_bad_parameter_types_raise():
    with pytest.raises(TypeError, match="ICGNParams"):
        StereoMatchParams(icgn=object())
    with pytest.raises(TypeError, match="MatchSeed"):
        StereoMatchParams(seed="plane")


def test_broken_calls_raise(images, rig, params):
    from dataclasses import replace

    left, right = images
    with pytest.raises(ValueError, match="same shape"):
        match_stereo_pair(left, right[:-1], rig, params)
    with pytest.raises(ValueError, match="2-D"):
        match_stereo_pair(left[0], right[0], rig, params)
    with pytest.raises(ValueError, match=r"\(N, 2\)"):
        match_stereo_pair(left, right, rig, params, points=np.zeros((4, 3)))
    with pytest.raises(ValueError, match="finite"):
        match_stereo_pair(
            left, right, rig, params, points=np.full((4, 2), np.nan)
        )
    with pytest.raises(ValueError, match="PLANE seed needs a rig"):
        match_stereo_pair(left, right, None, replace(params, seed=MatchSeed.PLANE))
    with pytest.raises(TypeError, match="StereoRig"):
        match_stereo_pair(left, right, object(), params)
    with pytest.raises(ValueError, match="3x4"):
        match_stereo_pair(left, right, [np.eye(3), np.eye(3)], params)


def test_an_empty_aoi_is_a_valid_request(images, rig, params):
    """No POIs is a question with an answer, not a broken call."""
    result = match_stereo_pair(
        images[0], images[1], rig, params, points=np.zeros((0, 2))
    )
    assert result.n_points == 0
    assert result.accepted_fraction == 0.0
    assert result.correspondences()[0].shape == (0, 2)
    assert math.isnan(result.summary()["zncc_median"])


def test_a_flat_pair_fails_every_point_instead_of_answering(rig, params):
    """No texture, no correspondence -- and no plausible-looking number either."""
    flat = np.full((HEIGHT, WIDTH), 100.0)
    result = match_stereo_pair(flat, flat, rig, params)
    assert result.n_accepted == 0
    assert np.all(result.status == int(Status.SINGULAR_HESSIAN))
    assert np.all(np.isnan(result.sampson_px))
    assert math.isnan(result.summary()["sampson_px_rms"])


def test_no_runtime_warnings_on_the_failure_paths(rig, params, images):
    """A RuntimeWarning here is a silent-nonsense bug in waiting."""
    from dataclasses import replace

    flat = np.full((HEIGHT, WIDTH), 100.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for left, right in ((flat, flat), images):
            for rig_arg in (rig, None):
                seeded = replace(
                    params,
                    seed=MatchSeed.SOLVER if rig_arg is None else MatchSeed.PLANE,
                )
                out = match_stereo_pair(left, right, rig_arg, seeded)
                out.summary()
                out.correspondences()
        plane_disparity(rig, np.array([[10.0, 10.0]]), (0.0, 0.0, 1.0, 1000.0))


# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #


def test_package_reexports_the_matcher():
    for name in match_module.__all__:
        assert hasattr(match_module, name), name
        assert name in stereo.__all__, name
    assert stereo.__all__ == sorted(stereo.__all__)
    assert stereo.match_stereo_pair is match_module.match_stereo_pair


def test_result_is_the_documented_type(matched):
    assert isinstance(matched, StereoMatchResult)
    assert isinstance(matched.params, StereoMatchParams)
