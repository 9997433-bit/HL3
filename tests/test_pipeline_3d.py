# SPDX-License-Identifier: Apache-2.0
"""Tests for the stereo-DIC pipeline: two views, two frames, world-frame U/V/W.

The scene is a speckled plane imaged by the converged stereo rig of
:func:`hl3.stereo.make_stereo_rig`, and every deformed frame is a *rigid
translation* of that plane. Rigid translation is the strongest cheap test there
is for a 3D chain, because the answer is known to the last digit at every point
and three independent things have to be right to reproduce it:

* the stereo correspondence, or ``W`` picks up a bias that no in-plane check
  would see;
* both temporal matches, or the two views disagree and the triangulated point
  moves along the epipolar direction;
* the triangulation, or a correct correspondence still lands on the wrong
  world point.

Getting ``U`` and ``V`` right while ``W`` drifts is the classic stereo-DIC
failure, so the assertions are per-component rather than on the magnitude.

The images are rendered from an analytic, exactly band-limited random texture
evaluated on the *object plane* and sampled through each camera's true pinhole
projection. Nothing in the renderer shares code with the solver: the reference
and deformed images are two independent evaluations of the same continuous
function at different world positions, so the residual measured here is the
pipeline's own, not an artefact of shifting an array.

:mod:`hl3.stereo.match` may or may not be importable depending on what has
merged; the suite covers both, and the numeric assertions must hold either way.
"""

from __future__ import annotations

import dataclasses
import math
import sys
import types

import numpy as np
import pytest

from hl3.correlate import ICGNParams, Status
from hl3.pipeline import dic3d
from hl3.pipeline.dic3d import (
    Dic3DConfig,
    MatchMode,
    MatchOutcome,
    MatchUnavailableError,
    RejectReason,
    Triangulator,
    correlate_stereo_pair,
    epipolar_depth_search,
    match_reference_stereo,
    resolve_match_backend,
    run_stereo_sequence,
    triangulate_correspondence,
)
from hl3.stereo import Camera, StereoRig, make_stereo_rig

# --------------------------------------------------------------------------
# Synthetic scene: a speckled plane seen by a converged stereo rig
# --------------------------------------------------------------------------

#: Sensor crop. Small enough that a whole run is a couple of seconds, large
#: enough to hold a POI grid with a 21 px subset and a real margin.
SENSOR = 192

#: World translations applied to the plane, in mm. The first is the reference,
#: the second is sub-pixel in every component, the third is several pixels.
SHIFTS = (
    np.array([0.0, 0.0, 0.0]),
    np.array([0.060, -0.040, 0.030]),
    np.array([0.150, 0.100, -0.080]),
)


def speckle_field(seed: int = 7, n_waves: int = 320, f_min=0.6, f_max=2.4):
    """A band-limited Gaussian random field on the object plane, in mm^-1.

    A sum of random-phase cosines with frequencies drawn from an annulus. Two
    properties matter: it is defined everywhere, so it can be evaluated at the
    scattered world points a perspective camera actually samples, and it is
    exactly band limited, so the rendered image carries no aliasing for the
    interpolator to trip over.
    """
    rng = np.random.default_rng(seed)
    angle = rng.uniform(0.0, 2.0 * np.pi, n_waves)
    freq = np.sqrt(rng.uniform(f_min**2, f_max**2, n_waves))
    phase = rng.uniform(0.0, 2.0 * np.pi, n_waves)
    fx, fy = freq * np.cos(angle), freq * np.sin(angle)

    def field(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        arg = 2.0 * np.pi * (fx[None, :] * a[:, None] + fy[None, :] * b[:, None])
        return np.cos(arg + phase[None, :]).sum(axis=1) / np.sqrt(n_waves)

    return field


def plane_basis(tilt_deg: float = 0.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """In-plane axes and normal of the object plane, rotated about world x."""
    t = math.radians(tilt_deg)
    rotation = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(t), -math.sin(t)],
            [0.0, math.sin(t), math.cos(t)],
        ]
    )
    return rotation[:, 0], rotation[:, 1], rotation[:, 2]


def render(
    camera: Camera,
    field,
    translation=(0.0, 0.0, 0.0),
    tilt_deg: float = 0.0,
    noise: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """Image of the translated speckled plane through one pinhole camera.

    Each pixel's viewing ray is intersected with the plane in its *current*
    position and the texture is evaluated at the material coordinate of that
    intersection, so the deformed image is what the camera would really have
    seen after the plane moved -- perspective, foreshortening and all.
    """
    P = camera.P
    M = P[:, :3]
    centre = -np.linalg.solve(M, P[:, 3])
    ys, xs = np.meshgrid(
        np.arange(camera.height), np.arange(camera.width), indexing="ij"
    )
    pixels = np.column_stack([xs.ravel(), ys.ravel(), np.ones(xs.size)])
    rays = np.linalg.solve(M, pixels.T).T
    rays /= np.linalg.norm(rays, axis=1, keepdims=True)
    if (rays @ P[2, :3]).mean() < 0.0:
        rays = -rays

    e1, e2, normal = plane_basis(tilt_deg)
    origin = np.asarray(translation, dtype=float)
    distance = (normal @ (origin - centre)) / (rays @ normal)
    world = centre[None, :] + distance[:, None] * rays
    local = world - origin[None, :]
    image = field(local @ e1, local @ e2).reshape(camera.height, camera.width)

    low, high = np.percentile(image, (0.5, 99.5))
    image = 255.0 * np.clip((image - low) / (high - low), 0.0, 1.0)
    if noise:
        image = image + np.random.default_rng(seed).normal(0.0, noise, image.shape)
    return image


@pytest.fixture(scope="module")
def rig() -> StereoRig:
    return make_stereo_rig(width=SENSOR, height=SENSOR)


@pytest.fixture(scope="module")
def scene(rig: StereoRig) -> dict:
    """Every image the suite needs, rendered once."""
    field = speckle_field()
    flat_left = [render(rig.left, field, shift) for shift in SHIFTS]
    flat_right = [render(rig.right, field, shift) for shift in SHIFTS]
    return {
        "field": field,
        "left": flat_left,
        "right": flat_right,
        "tilted_left": [
            render(rig.left, field, shift, tilt_deg=20.0) for shift in SHIFTS[:2]
        ],
        "tilted_right": [
            render(rig.right, field, shift, tilt_deg=20.0) for shift in SHIFTS[:2]
        ],
        "noisy_left": [
            render(rig.left, field, shift, noise=2.0, seed=10 + i)
            for i, shift in enumerate(SHIFTS[:2])
        ],
        "noisy_right": [
            render(rig.right, field, shift, noise=2.0, seed=20 + i)
            for i, shift in enumerate(SHIFTS[:2])
        ],
    }


#: Working configuration: 21 px subsets on a 16 px grid, loop closure on.
CONFIG = Dic3DConfig(icgn=ICGNParams(subset_radius=10, step=16), margin=26)
#: Coarse and loop-free, for the tests that are about plumbing not numbers.
QUICK = Dic3DConfig(
    icgn=ICGNParams(subset_radius=10, step=32), margin=30, loop_closure=False
)


@pytest.fixture(scope="module")
def rigid_run(rig: StereoRig, scene: dict):
    """The reference run: three frames of rigid translation, loop closure on."""
    return run_stereo_sequence(scene["left"], scene["right"], rig, CONFIG)


@pytest.fixture(scope="module")
def quick_run(rig: StereoRig, scene: dict):
    return run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, QUICK)


def displacement_error(frame, shift: np.ndarray) -> np.ndarray:
    """``(n_valid, 3)`` error of a frame's displacement against the truth."""
    return frame.displacement[frame.valid] - shift


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_default_config_is_usable_and_self_describing():
    config = Dic3DConfig()
    assert config.stereo_params is config.icgn
    assert config.subset_size == config.icgn.subset_size
    assert config.step == config.icgn.step
    assert config.triangulator is Triangulator.DLT
    assert config.match_mode is MatchMode.AUTO
    assert config.loop_closure is True
    # Reporting the loop residual is the default; rejecting on it is not.
    assert config.max_loop_px == math.inf
    assert config.max_epipolar_px == math.inf
    assert config.max_position_sigma_mm == math.inf


def test_stereo_params_can_differ_from_the_temporal_ones():
    stereo = ICGNParams(subset_radius=15, shape_order=2)
    config = Dic3DConfig(icgn=ICGNParams(subset_radius=8), stereo_icgn=stereo)
    assert config.stereo_params is stereo
    assert config.temporal_config().icgn.subset_radius == 8


def test_temporal_config_switches_strain_off():
    """Per-view 2D strain is a different quantity from surface strain."""
    from hl3.pipeline.dic2d import StrainMode

    temporal = Dic3DConfig().temporal_config()
    assert temporal.strain_mode is StrainMode.OFF


def test_temporal_config_carries_the_sequence_settings():
    from hl3.pipeline.dic2d import ReferenceMode, SeedMode

    config = Dic3DConfig(
        seed_mode=SeedMode.ZERO,
        reference_mode=ReferenceMode.EVERY_N,
        reference_every_n=3,
        margin=17,
    )
    temporal = config.temporal_config()
    assert temporal.seed_mode is SeedMode.ZERO
    assert temporal.reference_mode is ReferenceMode.EVERY_N
    assert temporal.reference_every_n == 3
    assert temporal.margin == 17


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"icgn": object()}, "ICGNParams"),
        ({"stereo_icgn": object()}, "ICGNParams"),
        ({"reference_index": -1}, "reference_index"),
        ({"reference_every_n": 0}, "reference_every_n"),
        ({"reference_zncc": 1.5}, "reference_zncc"),
        ({"margin": -1}, "margin"),
        ({"match_backend": 5}, "match_backend"),
        ({"depth_samples": 1}, "depth_samples"),
        ({"depth_step_px": 0.0}, "depth_step_px"),
        ({"max_depth_samples": 1}, "max_depth_samples"),
        ({"depth_span": 1.0}, "depth_span"),
        ({"depth_span": 0.0}, "depth_span"),
        ({"seed_zncc_min": 2.0}, "seed_zncc_min"),
        ({"depth_range_mm": (600.0, 100.0)}, "depth_range_mm"),
        ({"depth_range_mm": (0.0, 100.0)}, "depth_range_mm"),
        ({"depth_range_mm": (100.0, math.inf)}, "depth_range_mm"),
        ({"sigma_px": 0.0}, "sigma_px"),
        ({"max_position_sigma_mm": 0.0}, "max_position_sigma_mm"),
        ({"max_epipolar_px": -1.0}, "max_epipolar_px"),
        ({"max_loop_px": 0.0}, "max_loop_px"),
    ],
)
def test_config_rejects_impossible_settings(kwargs, fragment):
    with pytest.raises((TypeError, ValueError), match=fragment):
        Dic3DConfig(**kwargs)


def test_reference_updates_require_a_zero_reference_index():
    from hl3.pipeline.dic2d import ReferenceMode

    with pytest.raises(ValueError, match="forward accumulation"):
        Dic3DConfig(reference_mode=ReferenceMode.INCREMENTAL, reference_index=4)


# --------------------------------------------------------------------------
# Camera plumbing
# --------------------------------------------------------------------------


def test_a_rig_a_camera_pair_and_a_matrix_pair_are_the_same_run(rig, scene):
    """The three ways of naming the cameras must not change a single number."""
    pair = (rig.left, rig.right)
    matrices = np.stack([rig.left.P, rig.right.P])
    runs = [
        run_stereo_sequence(scene["left"][:2], scene["right"][:2], cameras, QUICK)
        for cameras in (rig, pair, matrices)
    ]
    for other in runs[1:]:
        assert np.array_equal(
            np.nan_to_num(runs[0].X_ref, nan=-1.0),
            np.nan_to_num(other.X_ref, nan=-1.0),
        )
        assert np.array_equal(
            np.nan_to_num(runs[0].frames[1].displacement, nan=-1.0),
            np.nan_to_num(other.frames[1].displacement, nan=-1.0),
        )


@pytest.mark.parametrize(
    ("cameras", "error", "fragment"),
    [
        (np.zeros((3, 4)), ValueError, "exactly two views"),
        ([np.zeros((3, 4))], ValueError, "exactly two views"),
        ([np.eye(3), np.eye(3)], ValueError, "projection matrix"),
        ([np.zeros((3, 4)), np.zeros((3, 4))], ValueError, "singular"),
        (7, TypeError, "StereoRig"),
    ],
)
def test_bad_cameras_are_rejected(cameras, error, fragment, scene):
    with pytest.raises(error, match=fragment):
        run_stereo_sequence(scene["left"][:2], scene["right"][:2], cameras, QUICK)


def test_a_non_finite_projection_matrix_is_rejected(rig, scene):
    P = rig.left.P.copy()
    P[0, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        run_stereo_sequence(
            scene["left"][:2], scene["right"][:2], [P, rig.right.P], QUICK
        )


# --------------------------------------------------------------------------
# The built-in epipolar search and matcher
# --------------------------------------------------------------------------


def test_the_depth_sweep_recovers_the_correspondence(rig, scene):
    """Stage B on its own must land within the solver's convergence radius."""
    points = np.array([[64.0, 64.0], [96.0, 96.0], [120.0, 80.0]])
    best, zncc = epipolar_depth_search(
        scene["left"][0],
        scene["right"][0],
        points,
        rig.left.P,
        rig.right.P,
        radius=10,
        depth_range_mm=(420.0, 880.0),
    )
    # The plane is at z = 0, which is where both optical axes cross, so the
    # true correspondence is the projection of the ray at that range.
    truth = np.array(
        [_project_plane(rig, point) for point in points], dtype=float
    )
    assert np.all(zncc > 0.9)
    assert np.all(np.linalg.norm(best - truth, axis=1) < 3.0)


def _project_plane(rig: StereoRig, point: np.ndarray) -> np.ndarray:
    """Where a left pixel's ray meets ``z = 0``, projected into the right view."""
    P = rig.left.P
    M = P[:, :3]
    centre = -np.linalg.solve(M, P[:, 3])
    ray = np.linalg.solve(M, np.array([point[0], point[1], 1.0]))
    world = centre + ray * (-centre[2] / ray[2])
    projected = rig.right.P @ np.append(world, 1.0)
    return projected[:2] / projected[2]


def test_the_sweep_reports_no_candidate_when_the_range_is_wrong(rig, scene):
    """A sweep nowhere near the surface must score badly, not merely differ."""
    _, zncc = epipolar_depth_search(
        scene["left"][0],
        scene["right"][0],
        np.array([[96.0, 96.0]]),
        rig.left.P,
        rig.right.P,
        radius=10,
        depth_range_mm=(100.0, 200.0),
    )
    assert zncc[0] < 0.5


def test_the_sweep_skips_points_whose_subset_leaves_the_image(rig, scene):
    _, zncc = epipolar_depth_search(
        scene["left"][0],
        scene["right"][0],
        np.array([[2.0, 2.0]]),
        rig.left.P,
        rig.right.P,
        radius=10,
        depth_range_mm=(420.0, 880.0),
    )
    assert zncc[0] == -1.0


def test_the_sample_count_follows_the_geometry(rig, scene):
    """A wider depth range is swept with proportionally more candidates.

    The count is derived, not configured, because the right number is a
    property of the rig: this baseline sweeps thousands of pixels across a
    +-35% range, and a fixed count that suits one rig misses on the next.
    """

    def sweep_calls(span: float) -> int:
        calls: list[int] = []
        real = dic3d.project

        def counting_project(P, X):
            calls.append(X.shape[0])
            return real(P, X)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(dic3d, "project", counting_project)
            epipolar_depth_search(
                scene["left"][0],
                scene["right"][0],
                np.array([[96.0, 96.0]]),
                rig.left.P,
                rig.right.P,
                radius=10,
                depth_range_mm=(648.0 * (1.0 - span), 648.0 * (1.0 + span)),
            )
        return len(calls)

    assert sweep_calls(0.35) > 3 * sweep_calls(0.05)


def test_an_explicit_sample_count_overrides_the_geometry(rig, scene):
    best, zncc = epipolar_depth_search(
        scene["left"][0],
        scene["right"][0],
        np.array([[96.0, 96.0]]),
        rig.left.P,
        rig.right.P,
        radius=10,
        depth_range_mm=(420.0, 880.0),
        depth_samples=2,
    )
    # Two samples at the ends of the range cannot see the middle of it.
    assert zncc[0] < 0.5 or np.isnan(best[0, 0])


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"depth_range_mm": (800.0, 400.0)}, "near < far"),
        ({"depth_range_mm": (-1.0, 400.0)}, "near < far"),
        ({"radius": 0}, "radius"),
        ({"depth_samples": 1}, "depth_samples"),
    ],
)
def test_the_sweep_rejects_impossible_arguments(rig, scene, kwargs, fragment):
    arguments = {
        "radius": 10,
        "depth_range_mm": (420.0, 880.0),
    } | kwargs
    with pytest.raises(ValueError, match=fragment):
        epipolar_depth_search(
            scene["left"][0],
            scene["right"][0],
            np.array([[96.0, 96.0]]),
            rig.left.P,
            rig.right.P,
            **arguments,
        )


def test_the_builtin_matcher_lands_on_the_epipolar_line(rig, scene):
    points = np.array([[70.0, 70.0], [96.0, 96.0], [110.0, 84.0]])
    match = match_reference_stereo(
        scene["left"][0],
        scene["right"][0],
        points,
        rig.left.P,
        rig.right.P,
        ICGNParams(subset_radius=10),
    )
    assert match.matched_fraction == 1.0
    assert np.all(match.zncc[match.valid] > 0.99)
    assert match.seed_zncc is not None
    truth = np.array([_project_plane(rig, point) for point in points])
    assert np.all(np.linalg.norm(match.x_right - truth, axis=1) < 0.05)


def test_the_builtin_matcher_accepts_a_supplied_guess(rig, scene):
    points = np.array([[96.0, 96.0]])
    guess = np.array([_project_plane(rig, points[0])]) + 0.4
    match = match_reference_stereo(
        scene["left"][0],
        scene["right"][0],
        points,
        rig.left.P,
        rig.right.P,
        ICGNParams(subset_radius=10),
        guess=guess,
    )
    assert match.seed_zncc is None
    assert "caller-supplied" in match.reason
    assert np.allclose(match.x_right[0], guess[0] - 0.4, atol=0.05)


def test_the_builtin_matcher_refuses_a_guess_of_the_wrong_shape(rig, scene):
    with pytest.raises(ValueError, match="shape"):
        match_reference_stereo(
            scene["left"][0],
            scene["right"][0],
            np.array([[96.0, 96.0]]),
            rig.left.P,
            rig.right.P,
            guess=np.zeros((3, 2)),
        )


def test_a_parallel_rig_has_no_derivable_depth_range(scene):
    """Refusing to guess is the point: a parallel rig has no convergence range."""
    K = make_stereo_rig(width=SENSOR, height=SENSOR).left.K
    left = Camera(K, np.eye(3), np.array([0.0, 0.0, 648.0]), SENSOR, SENSOR)
    right = Camera(K, np.eye(3), np.array([-254.0, 0.0, 648.0]), SENSOR, SENSOR)
    with pytest.raises(ValueError, match="depth_range_mm"):
        match_reference_stereo(
            scene["left"][0],
            scene["right"][0],
            np.array([[96.0, 96.0]]),
            left.P,
            right.P,
        )


def test_a_parallel_rig_works_once_the_range_is_stated(scene):
    K = make_stereo_rig(width=SENSOR, height=SENSOR).left.K
    left = Camera(K, np.eye(3), np.array([0.0, 0.0, 648.0]), SENSOR, SENSOR)
    right = Camera(K, np.eye(3), np.array([-254.0, 0.0, 648.0]), SENSOR, SENSOR)
    match = match_reference_stereo(
        scene["left"][0],
        scene["right"][0],
        np.array([[96.0, 96.0]]),
        left.P,
        right.P,
        depth_range_mm=(400.0, 900.0),
    )
    # The images are of the converged rig, so nothing should match this one;
    # what matters is that it ran and reported rather than raised.
    assert match.n_points == 1


# --------------------------------------------------------------------------
# Matcher hand-off
# --------------------------------------------------------------------------


def hide_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import hl3.stereo.match`` fail, merged or not."""
    real = dic3d.importlib.import_module

    def refuse(name: str, *args, **kwargs):
        if name == "hl3.stereo.match":
            raise ImportError("no module named 'hl3.stereo.match'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(dic3d.importlib, "import_module", refuse)


def install_match(monkeypatch: pytest.MonkeyPatch, **attributes) -> types.ModuleType:
    module = types.ModuleType("hl3.stereo.match")
    for name, value in attributes.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, "hl3.stereo.match", module)
    return module


def test_a_missing_matcher_falls_back_to_the_builtin_search(monkeypatch, rig, scene):
    hide_match(monkeypatch)
    backend, name, reason = resolve_match_backend()
    assert backend is None and name is None
    assert "hl3.stereo.match" in reason and "built-in" in reason

    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, QUICK)
    assert run.match.matched_fraction == 1.0
    assert "not importable" in run.match.reason
    assert np.allclose(run.frames[1].displacement, SHIFTS[1], atol=5e-4)


def test_a_module_that_explodes_on_import_falls_back(monkeypatch, rig, scene):
    def refuse(name, *args, **kwargs):
        raise RuntimeError("cannot import name 'StereoMatchParams'")

    monkeypatch.setattr(dic3d.importlib, "import_module", refuse)
    backend, _, reason = resolve_match_backend()
    assert backend is None and "RuntimeError" in reason

    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, QUICK)
    assert run.match.matched_fraction == 1.0


def test_a_module_without_a_known_entry_point_falls_back(monkeypatch):
    install_match(monkeypatch, some_helper=lambda: None)
    backend, name, reason = resolve_match_backend()
    assert backend is None and name is None
    assert "none of the expected entry points" in reason


def test_the_module_entry_point_is_discovered_and_used(monkeypatch, rig, scene):
    seen: list[str] = []

    def fake(left, right, rig, params, *, points, initial_guess=None):
        seen.append("called")
        return match_reference_stereo(
            left, right, points, rig[0], rig[1], ICGNParams(subset_radius=10)
        )

    install_match(monkeypatch, match_stereo_pair=fake)
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, QUICK)
    assert seen == ["called"]
    assert run.match.backend == "hl3.stereo.match.match_stereo_pair"
    assert run.provenance["stereo_matcher"] == "hl3.stereo.match.match_stereo_pair"
    assert np.allclose(run.frames[1].displacement, SHIFTS[1], atol=5e-4)


def test_entry_points_are_tried_in_order(monkeypatch):
    install_match(
        monkeypatch,
        match_stereo_pair=lambda **kwargs: None,
        match_stereo=lambda **kwargs: None,
    )
    _, name, _ = resolve_match_backend()
    assert name == "hl3.stereo.match.match_stereo_pair"


def test_a_backend_that_does_not_fit_the_contract_falls_back(monkeypatch, rig, scene):
    def wrong(**kwargs):
        return {"nothing": np.zeros(3)}

    install_match(monkeypatch, match_stereo_pair=wrong)
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, QUICK)
    assert "failed" in run.match.reason and "fell back" in run.match.reason
    # The fallback is a complete matcher, so the run is not merely alive.
    assert run.match.matched_fraction == 1.0
    assert np.allclose(run.frames[1].displacement, SHIFTS[1], atol=5e-4)


def test_required_mode_refuses_to_fall_back(monkeypatch, rig, scene):
    hide_match(monkeypatch)
    config = dataclasses.replace(QUICK, match_mode=MatchMode.REQUIRED)
    with pytest.raises(MatchUnavailableError, match="hl3.stereo.match"):
        run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)


def test_required_mode_reports_a_broken_backend_rather_than_hiding_it(
    monkeypatch, rig, scene
):
    install_match(monkeypatch, match_stereo_pair=lambda **kwargs: "not a result")
    config = dataclasses.replace(QUICK, match_mode=MatchMode.REQUIRED)
    with pytest.raises(MatchUnavailableError, match="failed"):
        run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)


def test_internal_mode_never_looks_for_the_module(monkeypatch, rig, scene):
    def explode(name, *args, **kwargs):
        raise AssertionError(f"no lookup expected, got {name!r}")

    monkeypatch.setattr(dic3d.importlib, "import_module", explode)
    config = dataclasses.replace(QUICK, match_mode=MatchMode.INTERNAL)
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    assert run.match.seed_zncc is not None
    assert "epipolar depth search" in run.match.reason


def test_an_injected_backend_wins_over_the_module(monkeypatch, rig, scene):
    install_match(monkeypatch, match_stereo_pair=lambda **kwargs: None)

    def injected(left, right, points, P_left, P_right):
        return match_reference_stereo(
            left, right, points, P_left, P_right, ICGNParams(subset_radius=10)
        )

    config = dataclasses.replace(QUICK, match_backend=injected)
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    assert run.match.backend == "injected"
    assert run.match.matched_fraction == 1.0


def test_the_payload_is_trimmed_to_the_backend_signature(rig, scene):
    seen: list[str] = []

    def narrow(left, right, points, P_left, P_right):
        seen.append("called")
        return match_reference_stereo(
            left, right, points, P_left, P_right, ICGNParams(subset_radius=10)
        )

    config = dataclasses.replace(QUICK, match_backend=narrow)
    run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    assert seen  # a narrower signature than the payload is not an error


def test_a_backend_taking_kwargs_gets_the_canonical_names(rig, scene):
    captured: dict[str, object] = {}

    def greedy(**kwargs):
        captured.update(kwargs)
        return match_reference_stereo(
            kwargs["left"],
            kwargs["right"],
            kwargs["points"],
            kwargs["rig"][0],
            kwargs["rig"][1],
            ICGNParams(subset_radius=10),
        )

    config = dataclasses.replace(QUICK, match_backend=greedy)
    run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    # Unambiguous names only: no aliases for the same array, which a backend
    # reading kwargs by hand could bind the wrong way round.
    assert set(captured) == {
        "left",
        "right",
        "points",
        "rig",
        "P_left",
        "P_right",
        "params",
    }


@pytest.mark.parametrize("form", ["array", "mapping", "object"])
def test_a_backend_may_return_an_array_a_mapping_or_an_object(
    form, monkeypatch, rig, scene
):
    truth: dict[str, np.ndarray] = {}

    def backend(left, right, points, P_left, P_right):
        inner = match_reference_stereo(
            left, right, points, P_left, P_right, ICGNParams(subset_radius=10)
        )
        truth["x_right"] = inner.x_right
        if form == "array":
            return inner.x_right
        if form == "mapping":
            return {"x_right": inner.x_right, "zncc": inner.zncc}
        return types.SimpleNamespace(right_xy=inner.x_right, accepted=inner.valid)

    config = dataclasses.replace(QUICK, match_backend=backend)
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    assert np.allclose(run.match.x_right, truth["x_right"], equal_nan=True)
    assert run.match.matched_fraction == 1.0


def test_a_backends_own_quality_mask_is_honoured(rig, scene):
    """A point the backend excluded is reported as MASKED, not as a failure."""

    def backend(left, right, points, P_left, P_right):
        inner = match_reference_stereo(
            left, right, points, P_left, P_right, ICGNParams(subset_radius=10)
        )
        accepted = inner.valid.copy()
        accepted[0] = False
        return {"x_right": inner.x_right, "accepted": accepted}

    config = dataclasses.replace(QUICK, match_backend=backend)
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    assert run.match.status[0] == int(Status.MASKED)
    assert not run.match.valid[0]
    assert np.all(np.isnan(run.X_ref[0]))
    assert run.frames[1].reject[0] == int(RejectReason.NO_STEREO_MATCH)
    assert run.frames[1].valid[1:].all()


def test_the_builtin_search_completes_what_the_backend_missed(rig, scene):
    """A backend that gives up on half the field must not cost half the field."""

    def half_blind(left, right, points, P_left, P_right):
        inner = match_reference_stereo(
            left, right, points, P_left, P_right, ICGNParams(subset_radius=10)
        )
        x_right = inner.x_right.copy()
        x_right[::2] = np.nan
        return x_right

    config = dataclasses.replace(QUICK, match_backend=half_blind)
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    assert run.match.matched_fraction == 1.0
    assert "recovered" in run.match.reason
    assert np.allclose(run.frames[1].displacement, SHIFTS[1], atol=1.0e-3)


def test_required_mode_does_not_complete_the_backends_misses(rig, scene):
    """"The module or nothing" has to mean nothing else runs, including us."""

    def half_blind(left, right, points, P_left, P_right):
        inner = match_reference_stereo(
            left, right, points, P_left, P_right, ICGNParams(subset_radius=10)
        )
        x_right = inner.x_right.copy()
        x_right[::2] = np.nan
        return x_right

    config = dataclasses.replace(
        QUICK, match_backend=half_blind, match_mode=MatchMode.REQUIRED
    )
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    assert run.match.matched_fraction == pytest.approx(0.5, abs=0.1)
    assert "recovered" not in run.match.reason


def test_a_tilted_surface_the_backend_seeds_badly_is_still_measured(rig, scene):
    """The nominal-plane seed misses a 20 deg slope; the sweep picks it up."""
    run = run_stereo_sequence(
        scene["tilted_left"], scene["tilted_right"], rig, QUICK
    )
    assert run.match.matched_fraction > 0.98


def test_a_backend_returning_the_wrong_length_is_a_failure(rig, scene):
    def backend(left, right, points, P_left, P_right):
        return np.zeros((3, 2))

    config = dataclasses.replace(
        QUICK, match_backend=backend, match_mode=MatchMode.REQUIRED
    )
    with pytest.raises(MatchUnavailableError, match="no .* array"):
        run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)


def test_the_backends_own_geometric_gate_is_switched_off(monkeypatch, rig):
    """One epipolar gate, applied here, so a rejection can be attributed.

    A backend default -- ``StereoMatchParams`` ships a 1 px Sampson ceiling --
    would otherwise silently tighten a run whose stated gate is
    ``max_epipolar_px``, and its rejects would be indistinguishable from
    correlation failures.
    """
    captured: dict[str, object] = {}

    class Params:
        def __init__(self, icgn=None, max_sampson_px=1.0, margin=None):
            captured["icgn"] = icgn
            captured["max_sampson_px"] = max_sampson_px

    def backend(left, right, points, params):
        return np.full((points.shape[0], 2), np.nan)

    module = install_match(monkeypatch, match_stereo_pair=backend)
    backend.__module__ = module.__name__
    monkeypatch.setattr(module, "StereoMatchParams", Params, raising=False)

    params = dic3d._backend_params(
        backend, dataclasses.replace(QUICK, max_epipolar_px=3.0)
    )
    assert isinstance(params, Params)
    assert captured["max_sampson_px"] == math.inf
    assert captured["icgn"] is QUICK.stereo_params


def test_a_backend_without_a_params_class_gets_the_correlation_parameters(rig):
    def backend(left, right, points, params):
        return np.full((points.shape[0], 2), np.nan)

    assert dic3d._backend_params(backend, QUICK) is QUICK.stereo_params


# --------------------------------------------------------------------------
# Triangulation dispatch
# --------------------------------------------------------------------------


def test_unobserved_points_triangulate_to_nan_without_taking_the_batch_down(rig):
    x_left = np.array([[96.0, 96.0], [np.nan, 96.0], [100.0, 100.0]])
    x_right = np.array([[96.0, 96.0], [96.0, 96.0], [100.0, 100.0]])
    X = triangulate_correspondence(rig.left.P, rig.right.P, x_left, x_right)
    assert np.all(np.isnan(X[1]))
    assert np.all(np.isfinite(X[[0, 2]]))


def test_triangulation_rejects_mismatched_correspondences(rig):
    with pytest.raises(ValueError, match=r"\(n, 2\)"):
        triangulate_correspondence(
            rig.left.P, rig.right.P, np.zeros((3, 2)), np.zeros((4, 2))
        )


def test_an_all_nan_correspondence_returns_all_nan(rig):
    X = triangulate_correspondence(
        rig.left.P, rig.right.P, np.full((2, 2), np.nan), np.zeros((2, 2))
    )
    assert X.shape == (2, 3)
    assert np.all(np.isnan(X))


@pytest.mark.parametrize("method", list(Triangulator))
def test_every_triangulation_rung_measures_the_same_translation(
    method, rig, scene
):
    """Rung choice is an accuracy/cost trade, not a change of answer."""
    config = dataclasses.replace(QUICK, triangulator=method)
    run = correlate_stereo_pair(
        scene["left"][0],
        scene["right"][0],
        scene["left"][1],
        scene["right"][1],
        rig,
        config,
    )
    assert run.provenance["triangulator"] == method.value
    error = displacement_error(run.frames[1], SHIFTS[1])
    assert np.abs(error).max() < 1.0e-3  # 1 um


# --------------------------------------------------------------------------
# Rigid translation: the measurement itself
# --------------------------------------------------------------------------


def test_the_reference_frame_has_identically_zero_displacement(rigid_run):
    """Not "small": both views correlate the reference against itself."""
    frame = rigid_run.frames[0]
    assert frame.valid.all()
    assert np.array_equal(frame.displacement, np.zeros_like(frame.displacement))
    assert np.array_equal(frame.X[frame.valid], rigid_run.X_ref[frame.valid])


@pytest.mark.parametrize("index", [1, 2])
def test_a_rigid_translation_is_recovered_in_all_three_components(rigid_run, index):
    frame = rigid_run.frames[index]
    assert frame.valid_fraction == 1.0
    error = displacement_error(frame, SHIFTS[index])
    bias = np.abs(error.mean(axis=0))
    rms = np.sqrt((error**2).mean(axis=0))
    # 1 um is ~0.016 px in-plane on this rig: a tolerance the pipeline has to
    # earn, and ~1.5% of the smallest commanded component.
    assert np.all(bias[:2] < 5.0e-4)
    assert bias[2] < 1.0e-3
    assert np.all(rms[:2] < 5.0e-4)
    assert rms[2] < 1.5e-3


def test_the_recovered_field_is_uniform_across_the_specimen(rigid_run):
    """A rigid body has no strain: the spread over POIs is the real signature."""
    frame = rigid_run.frames[2]
    spread = frame.displacement[frame.valid].std(axis=0)
    assert np.all(spread[:2] < 5.0e-4)
    assert spread[2] < 1.5e-3


def test_the_displacement_magnitude_matches_the_commanded_move(rigid_run):
    frame = rigid_run.frames[1]
    truth = float(np.linalg.norm(SHIFTS[1]))
    assert np.allclose(frame.magnitude[frame.valid], truth, atol=1.5e-3)


def test_the_reconstructed_shape_is_the_plane_it_was_rendered_from(rigid_run):
    z = rigid_run.X_ref[:, 2]
    assert np.all(np.abs(z[np.isfinite(z)]) < 5.0e-3)


def test_the_deformed_shape_is_the_reference_shape_moved_bodily(rigid_run):
    frame = rigid_run.frames[2]
    moved = rigid_run.X_ref[frame.valid] + SHIFTS[2]
    assert np.allclose(frame.X[frame.valid], moved, atol=1.5e-3)


def test_a_tilted_plane_is_measured_as_accurately_as_a_facing_one(rig, scene):
    """The two views see genuinely different perspectives of a 20 deg slope."""
    run = run_stereo_sequence(
        scene["tilted_left"], scene["tilted_right"], rig, CONFIG
    )
    assert run.frames[1].valid_fraction > 0.98
    error = displacement_error(run.frames[1], SHIFTS[1])
    assert np.abs(error.mean(axis=0)).max() < 1.0e-3

    # The shape is the tilted plane, not a fit to it: check the normal.
    X = run.X_ref[np.all(np.isfinite(run.X_ref), axis=1)]
    centred = X - X.mean(axis=0)
    normal = np.linalg.svd(centred)[2][-1]
    expected = plane_basis(20.0)[2]
    angle = math.degrees(math.acos(min(1.0, abs(float(normal @ expected)))))
    assert angle < 0.5


def test_image_noise_costs_precision_but_not_accuracy(rig, scene):
    """2 grey levels of noise: the bias must stay far below the scatter."""
    config = dataclasses.replace(CONFIG, loop_closure=False)
    run = run_stereo_sequence(scene["noisy_left"], scene["noisy_right"], rig, config)
    frame = run.frames[1]
    assert frame.valid_fraction > 0.95
    error = displacement_error(frame, SHIFTS[1])
    bias = np.abs(error.mean(axis=0))
    scatter = error.std(axis=0)
    assert np.all(bias[:2] < 1.0e-3)
    assert bias[2] < 3.0e-3
    assert np.all(scatter[:2] < 2.0e-3)
    assert scatter[2] < 8.0e-3


def test_the_two_frame_wrapper_matches_the_sequence_entry_point(rig, scene):
    pair = correlate_stereo_pair(
        scene["left"][0],
        scene["right"][0],
        scene["left"][1],
        scene["right"][1],
        rig,
        QUICK,
    )
    sequence = run_stereo_sequence(
        scene["left"][:2], scene["right"][:2], rig, QUICK
    )
    assert np.allclose(
        pair.frames[1].displacement,
        sequence.frames[1].displacement,
        equal_nan=True,
    )


def test_a_known_correspondence_skips_the_search(rig, scene):
    points = np.array([[80.0, 80.0], [96.0, 96.0], [112.0, 112.0]])
    known = np.array([_project_plane(rig, point) for point in points])
    config = dataclasses.replace(QUICK, match_mode=MatchMode.INTERNAL)
    run = run_stereo_sequence(
        scene["left"][:2],
        scene["right"][:2],
        rig,
        config,
        points=points,
        right_points=known,
    )
    assert run.match.seed_zncc is None
    assert np.allclose(run.match.x_right, known, atol=0.05)
    assert np.allclose(run.frames[1].displacement, SHIFTS[1], atol=1.0e-3)


def test_a_supplied_correspondence_must_have_one_row_per_point(rig, scene):
    with pytest.raises(ValueError, match="right_points"):
        run_stereo_sequence(
            scene["left"][:2],
            scene["right"][:2],
            rig,
            QUICK,
            points=np.array([[96.0, 96.0]]),
            right_points=np.zeros((2, 2)),
        )


# --------------------------------------------------------------------------
# Run structure, fields and provenance
# --------------------------------------------------------------------------


def test_the_run_reports_its_grid_and_reshapes_fields_onto_it(rigid_run):
    ny, nx = rigid_run.grid_shape
    assert ny * nx == rigid_run.n_points
    for name in ("u", "v", "w", "magnitude", "x", "y", "z"):
        assert rigid_run.field(name).shape == (3, ny, nx)
    assert rigid_run.valid_mask().shape == (3, ny, nx)
    assert rigid_run.shape_field().shape == (ny, nx, 3)


def test_scattered_points_stay_a_flat_list(rig, scene):
    points = np.array([[70.0, 90.0], [96.0, 96.0], [120.0, 70.0]])
    run = run_stereo_sequence(
        scene["left"][:2], scene["right"][:2], rig, QUICK, points=points
    )
    assert run.grid_shape is None
    assert run.field("w").shape == (2, 3)
    assert run.shape_field().shape == (3, 3)


def test_field_masks_floats_but_not_bookkeeping(rigid_run):
    masked = rigid_run.field("u")
    assert not np.isnan(masked[rigid_run.valid_mask()]).any()
    assert rigid_run.field("reject").dtype.kind in "iu"
    assert not np.isnan(rigid_run.field("status_left").astype(float)).any()


def test_an_unknown_field_name_lists_the_known_ones(rigid_run):
    with pytest.raises(ValueError, match="unknown field"):
        rigid_run.field("epsilon_xx")


def test_the_run_keeps_both_2d_sub_runs_for_drill_down(rigid_run):
    assert rigid_run.left.n_frames == 3
    assert rigid_run.right is not None
    # The right view is tracked from where the reference match put it, not
    # from a grid of its own: that is what makes the pairing path-independent.
    tracked = rigid_run.match.valid
    assert np.allclose(rigid_run.right.points, rigid_run.match.x_right[tracked])
    assert np.allclose(rigid_run.left.points, rigid_run.points)


def test_provenance_records_the_geometry_and_the_gates(rigid_run):
    provenance = rigid_run.provenance
    assert provenance["triangulator"] == "dlt"
    assert provenance["distortion_model"] == "pinhole_L0"
    assert provenance["deterministic"] is True
    assert provenance["n_frames"] == 3
    assert provenance["n_points"] == rigid_run.n_points
    assert provenance["baseline_mm"] == pytest.approx(254.0, abs=1e-6)
    # Range along the optical axis, not the rig's z standoff: the cameras sit
    # at (+-127, 0, -648) and look at the origin.
    assert provenance["convergence_range_mm"] == pytest.approx(
        math.hypot(127.0, 648.0), rel=1e-9
    )
    assert provenance["matched_fraction"] == 1.0
    assert provenance["loop_closure"] is True
    assert provenance["loop_px_median"] < 0.01
    assert provenance["epipolar_sampson_px_median"] < 0.05
    assert provenance["reprojection_px_median"] < 0.05
    assert provenance["valid_fraction_min"] == 1.0


def test_the_run_is_reproducible_from_its_inputs(rig, scene):
    first = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, QUICK)
    second = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, QUICK)
    assert np.array_equal(first.X_ref, second.X_ref, equal_nan=True)
    assert np.array_equal(
        first.frames[1].displacement, second.frames[1].displacement, equal_nan=True
    )


def test_progress_is_reported_once_per_frame(rig, scene):
    seen: list[tuple[int, int]] = []
    run_stereo_sequence(
        scene["left"], scene["right"], rig, QUICK, progress=lambda i, n: seen.append(
            (i, n)
        )
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_capture_style_frames_are_accepted_and_their_metadata_survives(rig, scene):
    left = [
        types.SimpleNamespace(image=image, frame_index=10 + i, timestamp_s=0.5 * i)
        for i, image in enumerate(scene["left"][:2])
    ]
    right = [
        types.SimpleNamespace(image=image, frame_index=10 + i, timestamp_s=0.5 * i)
        for i, image in enumerate(scene["right"][:2])
    ]
    run = run_stereo_sequence(left, right, rig, QUICK)
    assert [frame.frame_index for frame in run.frames] == [10, 11]
    assert run.frames[1].timestamp_s == 0.5


def test_a_one_shot_iterable_is_consumed_exactly_once(rig, scene):
    left = iter(scene["left"][:2])
    right = iter(scene["right"][:2])
    run = run_stereo_sequence(left, right, rig, QUICK)
    assert run.n_frames == 2
    assert run.frames[1].valid.any()


def test_a_stack_of_images_is_accepted(rig, scene):
    run = run_stereo_sequence(
        np.stack(scene["left"][:2]), np.stack(scene["right"][:2]), rig, QUICK
    )
    assert run.n_frames == 2
    assert run.frames[1].valid_fraction == 1.0


# --------------------------------------------------------------------------
# Quality gates
# --------------------------------------------------------------------------


def test_the_loop_residual_is_computed_and_is_small_on_clean_images(rigid_run):
    """Spec S6.4: the truth-free consistency figure of the whole chain."""
    for frame in rigid_run.frames:
        residual = frame.loop_px[frame.valid]
        assert np.all(np.isfinite(residual))
        assert np.all(residual < 0.05)


def test_loop_closure_can_be_switched_off(rig, scene):
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, QUICK)
    assert np.all(np.isnan(run.frames[1].loop_px))
    assert run.provenance["loop_closure"] is False
    assert math.isnan(run.provenance["loop_px_median"])


def test_the_loop_gate_rejects_exactly_what_it_measures(rig, scene):
    config = dataclasses.replace(
        QUICK, loop_closure=True, max_loop_px=1.0e-9
    )
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    frame = run.frames[1]
    over = frame.loop_px > 1.0e-9
    assert over.any()
    assert np.all(frame.reject[over] == int(RejectReason.LOOP_CLOSURE))
    assert np.all(np.isnan(frame.displacement[over]))


def test_the_uncertainty_gate_rejects_a_field_it_cannot_locate(rig, scene):
    config = dataclasses.replace(QUICK, max_position_sigma_mm=1.0e-6)
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    frame = run.frames[1]
    assert frame.valid_fraction == 0.0
    assert np.all(frame.reject == int(RejectReason.UNCERTAINTY))
    # The uncertainty itself is still reported: the gate says why, it does not
    # erase the evidence.
    assert np.all(np.isfinite(frame.position_sigma_mm))


def test_position_uncertainty_scales_with_the_assumed_image_noise(rig, scene):
    runs = [
        run_stereo_sequence(
            scene["left"][:2],
            scene["right"][:2],
            rig,
            dataclasses.replace(QUICK, sigma_px=sigma),
        )
        for sigma in (0.5, 1.0)
    ]
    ratio = (
        np.nanmedian(runs[1].frames[0].position_sigma_mm)
        / np.nanmedian(runs[0].frames[0].position_sigma_mm)
    )
    assert ratio == pytest.approx(2.0, rel=1e-6)


def test_the_epipolar_gate_drops_the_correspondence_before_triangulation(rig, scene):
    config = dataclasses.replace(QUICK, max_epipolar_px=1.0e-9)
    run = run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)
    over = run.epipolar_px > 1.0e-9
    assert over.any()
    assert np.all(np.isnan(run.X_ref[over]))
    assert np.all(run.frames[1].reject[over] == int(RejectReason.EPIPOLAR))
    # No right-view correspondence survived, so there was nothing to track.
    assert run.right is None


def test_the_epipolar_residual_is_reported_for_every_matched_point(rigid_run):
    assert rigid_run.epipolar_px.shape == (rigid_run.n_points,)
    assert np.all(rigid_run.epipolar_px[rigid_run.match.valid] < 0.05)


def test_a_failed_stereo_match_costs_the_point_but_not_the_run(rig, scene):
    """A right reference image with no relation to the left one."""
    rng = np.random.default_rng(0)
    noise = rng.uniform(0.0, 255.0, scene["right"][0].shape)
    run = run_stereo_sequence(
        scene["left"][:2], [noise, scene["right"][1]], rig, QUICK
    )
    assert run.match.matched_fraction < 0.2
    assert run.frames[1].valid_fraction < 0.2
    counts = run.frames[1].reject_counts()
    assert counts[RejectReason.NO_STEREO_MATCH] > 0


def test_a_failed_temporal_match_is_attributed_to_the_view_that_failed(rig, scene):
    rng = np.random.default_rng(1)
    noise = rng.uniform(0.0, 255.0, scene["left"][1].shape)
    run = run_stereo_sequence(
        [scene["left"][0], noise], scene["right"][:2], rig, QUICK
    )
    frame = run.frames[1]
    assert frame.valid_fraction == 0.0
    assert np.all(frame.reject == int(RejectReason.LEFT_MATCH))
    assert np.all(np.isnan(frame.displacement))
    # The reference frame, and therefore the shape, survived intact.
    assert run.frames[0].valid_fraction == 1.0
    assert np.all(np.isfinite(run.X_ref))


def test_reject_counts_add_up_to_the_point_count(rigid_run):
    for frame in rigid_run.frames:
        assert sum(frame.reject_counts().values()) == frame.n_points


def test_invalid_points_are_nan_rather_than_stale(rig, scene):
    rng = np.random.default_rng(2)
    noise = rng.uniform(0.0, 255.0, scene["left"][1].shape)
    run = run_stereo_sequence(
        [scene["left"][0], noise], scene["right"][:2], rig, QUICK
    )
    frame = run.frames[1]
    assert np.all(np.isnan(frame.X[~frame.valid]))
    assert np.all(np.isnan(frame.displacement[~frame.valid]))
    assert np.all(np.isnan(run.field("w")[1]))


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


def test_the_two_views_must_have_the_same_number_of_frames(rig, scene):
    with pytest.raises(ValueError, match="same number of frames"):
        run_stereo_sequence(scene["left"], scene["right"][:2], rig, QUICK)


def test_the_two_views_must_share_a_pixel_grid(rig, scene):
    with pytest.raises(ValueError, match="pixel grid"):
        run_stereo_sequence(
            scene["left"][:2],
            [image[:-4] for image in scene["right"][:2]],
            rig,
            QUICK,
        )


def test_an_empty_sequence_is_refused(rig, scene):
    with pytest.raises(ValueError, match="at least one frame"):
        run_stereo_sequence([], [], rig, QUICK)


def test_a_colour_image_is_refused(rig, scene):
    colour = np.zeros((SENSOR, SENSOR, 3))
    with pytest.raises(ValueError, match="2-D greyscale"):
        run_stereo_sequence([colour], [colour], rig, QUICK)


def test_a_reference_index_outside_the_sequence_is_refused(rig, scene):
    config = dataclasses.replace(QUICK, reference_index=5)
    with pytest.raises(ValueError, match="reference_index"):
        run_stereo_sequence(scene["left"][:2], scene["right"][:2], rig, config)


@pytest.mark.parametrize(
    "points",
    [np.zeros((3, 3)), np.array([[np.nan, 1.0], [2.0, 3.0]])],
)
def test_bad_point_lists_are_refused(points, rig, scene):
    with pytest.raises(ValueError, match="points"):
        run_stereo_sequence(
            scene["left"][:2], scene["right"][:2], rig, QUICK, points=points
        )


def test_a_non_iterable_image_source_is_refused(rig):
    with pytest.raises(TypeError, match="left_images"):
        run_stereo_sequence(7, 7, rig, QUICK)


def test_a_later_reference_frame_is_honoured(rig, scene):
    """Frame 1 as the reference: displacement is measured from there."""
    config = dataclasses.replace(QUICK, reference_index=1)
    run = run_stereo_sequence(scene["left"], scene["right"], rig, config)
    # Not identically zero as it is for frame 0 of a default run: the seed
    # carried in from frame 0 makes the self-correlation converge to a
    # nanometre of zero instead of landing on it at the first iteration.
    assert np.abs(run.frames[1].displacement).max() < 1.0e-6
    expected = SHIFTS[2] - SHIFTS[1]
    error = displacement_error(run.frames[2], expected)
    assert np.abs(error).max() < 1.5e-3
    # Frame 0 is *behind* the reference, so its displacement is negative.
    back = displacement_error(run.frames[0], SHIFTS[0] - SHIFTS[1])
    assert np.abs(back).max() < 1.5e-3


def test_the_match_outcome_summarises_itself(rigid_run):
    match = rigid_run.match
    assert match.n_points == rigid_run.n_points
    assert match.matched_fraction == 1.0
    assert match.valid.sum() == match.n_points
    assert isinstance(match.backend, str) and match.backend
    assert isinstance(match.reason, str) and match.reason


def test_a_match_outcome_with_no_points_reports_zero_rather_than_dividing(rig):
    empty = MatchOutcome(
        points=np.zeros((0, 2)),
        x_right=np.zeros((0, 2)),
        zncc=np.zeros(0),
        status=np.zeros(0, dtype=np.int32),
        backend="test",
        reason="test",
    )
    assert empty.n_points == 0
    assert empty.matched_fraction == 0.0
