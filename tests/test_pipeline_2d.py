# SPDX-License-Identifier: Apache-2.0
"""Tests for the sequence-level 2D DIC pipeline.

Two image sources are used, for two different jobs:

* :class:`hl3.capture.MockCapture` -- hardware-free, deterministic, and moved
  by :func:`numpy.roll`, so frame ``i`` is an exact integer translation of
  ``(u, v) = (2i, i)``. It exercises the plumbing (grids, fields, metadata,
  reference updates) against a ground truth that has no interpolation error at
  all.
* A band-limited synthetic speckle pair, shifted with the Fourier shift
  theorem and block-averaged down to sensor pixels, for the sub-pixel accuracy
  checks. The generator never uses the solver's interpolant, so the residual
  measured here is the pipeline's, not the test's.

The strain hand-off is tested from both sides: with :mod:`hl3.strain` forced
absent, forced present but incompatible, and with an injected backend. The
pipeline must complete in every case, and only :attr:`StrainMode.REQUIRED` may
turn a missing strain module into a failed run.
"""

from __future__ import annotations

import dataclasses
import math
import sys
import types

import numpy as np
import pytest

from hl3.capture import MockCapture
from hl3.correlate import ICGNParams, Status, make_grid, warp_matrix
from hl3.pipeline import dic2d
from hl3.pipeline.dic2d import (
    Dic2DConfig,
    ReferenceMode,
    SeedMode,
    StrainMode,
    StrainUnavailableError,
    compose_total,
    correlate_pair,
    lattice_shape,
    resolve_strain_backend,
    run_sequence,
    vsg_size_px,
)

# --------------------------------------------------------------------------
# Image sources
# --------------------------------------------------------------------------


def mock_frames(count: int = 4, size: int = 96, seed: int = 3) -> list:
    return list(MockCapture(frame_count=count, shape=(size, size), seed=seed))


def mock_truth(index: int) -> tuple[float, float]:
    """``MockCapture`` rolls the base by ``(index, 2 * index)`` on ``(y, x)``."""
    return 2.0 * index, 1.0 * index


def _speckle_spectrum(size: int, oversample: int, seed: int) -> np.ndarray:
    """Fourier spectrum of a continuous Gaussian-speckle texture."""
    canvas = size * oversample
    count = max(1, round(0.08 * size * size))
    rng = np.random.default_rng(seed)
    ys = rng.uniform(0.0, canvas, count)
    xs = rng.uniform(0.0, canvas, count)

    impulses = np.zeros((canvas, canvas), dtype=np.float64)
    np.add.at(impulses, (ys.astype(np.int64), xs.astype(np.int64)), 1.0)

    fy = np.fft.fftfreq(canvas)[:, None]
    fx = np.fft.fftfreq(canvas)[None, :]
    sigma = 1.4 * oversample
    blur = np.exp(-2.0 * math.pi**2 * sigma**2 * (fx * fx + fy * fy))
    return np.fft.fft2(impulses) * blur


def _render(
    spectrum: np.ndarray, size: int, oversample: int, shift: tuple[float, float]
) -> np.ndarray:
    """Shift the texture by ``(u, v)`` px exactly, then integrate over pixels."""
    u, v = shift
    fy = np.fft.fftfreq(spectrum.shape[0])[:, None]
    fx = np.fft.fftfreq(spectrum.shape[1])[None, :]
    phase = np.exp(
        -2.0j * math.pi * (fx * (u * oversample) + fy * (v * oversample))
    )
    field = np.fft.ifft2(spectrum * phase).real
    return field.reshape(size, oversample, size, oversample).mean(axis=(1, 3))


def speckle_sequence(
    shifts: list[tuple[float, float]], size: int = 128, oversample: int = 6, seed: int = 20260828
) -> list[np.ndarray]:
    """One image per requested shift, normalised to 0..255 grey."""
    spectrum = _speckle_spectrum(size, oversample, seed)
    frames = [_render(spectrum, size, oversample, shift) for shift in shifts]
    low, high = np.percentile(frames[0], (0.5, 99.5))
    return [
        255.0 - 255.0 * np.clip((frame - low) / (high - low), 0.0, 1.0)
        for frame in frames
    ]


@pytest.fixture(scope="module")
def translation_sequence() -> tuple[list[np.ndarray], list[tuple[float, float]]]:
    shifts = [(0.0, 0.0), (0.37, -0.42), (1.63, 0.85), (2.5, -1.25)]
    return speckle_sequence(shifts), shifts


PAIR_CONFIG = Dic2DConfig(icgn=ICGNParams(subset_radius=10, step=10), margin=34)


# --------------------------------------------------------------------------
# Algebra that the pipeline owns
# --------------------------------------------------------------------------


def test_vsg_follows_the_gpg_formula():
    # L_VSG = (L_window - 1) * L_step + L_subset, iDICs GPG Eq. (7.2).
    assert vsg_size_px(21, 5, 5) == 41
    assert vsg_size_px(21, 5, 1) == 21
    for subset in (15, 21, 31):
        for step in (3, 5, 7):
            for window in (3, 5, 9):
                assert vsg_size_px(subset, step, window) == (
                    (window - 1) * step + subset
                )


def test_config_reports_its_own_vsg():
    config = Dic2DConfig(icgn=ICGNParams(subset_radius=10, step=5), strain_window=5)
    assert config.subset_size == 21
    assert config.l_vsg_px == 41


@pytest.mark.parametrize("bad", [0, -1])
def test_vsg_rejects_nonpositive_inputs(bad):
    with pytest.raises(ValueError):
        vsg_size_px(21, 5, bad)


def test_compose_total_matches_matrix_product():
    """``F_total = F_s @ F_a`` and the translations add, per spec section 2.9."""
    accumulated = np.array([[1.5, 0.02, -0.01, -0.8, 0.004, 0.015]])
    segment = np.array([[-0.7, 0.005, 0.02, 2.1, -0.03, 0.007]])
    total = compose_total(accumulated, segment)

    expected_f = warp_matrix(segment[0])[:2, :2] @ warp_matrix(accumulated[0])[:2, :2]
    assert total[0, 0] == pytest.approx(accumulated[0, 0] + segment[0, 0])
    assert total[0, 3] == pytest.approx(accumulated[0, 3] + segment[0, 3])
    assert np.allclose(
        np.array([[1.0 + total[0, 1], total[0, 2]], [total[0, 4], 1.0 + total[0, 5]]]),
        expected_f,
    )


def test_compose_total_is_identity_on_a_zero_accumulator():
    segment = np.array([[0.3, 0.01, 0.02, -0.4, 0.03, 0.04], [1.0, 0.0, 0.0, 2.0, 0.0, 0.0]])
    assert np.array_equal(compose_total(np.zeros_like(segment), segment), segment)


def test_compose_total_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        compose_total(np.zeros((2, 6)), np.zeros((3, 6)))
    with pytest.raises(ValueError):
        compose_total(np.zeros((2, 4)), np.zeros((2, 4)))


def test_lattice_shape_detects_grids_and_refuses_scattered_points():
    params = ICGNParams(subset_radius=6, step=7)
    grid = make_grid((80, 100), params, margin=12)
    ny, nx = lattice_shape(grid)
    assert ny * nx == grid.shape[0]
    assert lattice_shape(grid[:-1]) is None
    assert lattice_shape(np.array([[10.0, 10.0], [30.0, 12.0], [11.0, 40.0]])) is None
    assert lattice_shape(np.zeros((0, 2))) is None
    # A lattice listed in the wrong order must not be folded into a grid.
    assert lattice_shape(grid[::-1]) is None


# --------------------------------------------------------------------------
# End-to-end on MockCapture
# --------------------------------------------------------------------------


def test_mock_capture_sequence_recovers_the_integer_translations():
    config = Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=8), margin=20)
    run = run_sequence(MockCapture(frame_count=4, shape=(96, 96), seed=3), config)

    assert run.n_frames == 4
    assert run.n_points > 0
    assert run.grid_shape is not None
    assert run.grid_shape[0] * run.grid_shape[1] == run.n_points

    for frame in run.frames:
        u_true, v_true = mock_truth(frame.index)
        assert frame.valid_fraction == 1.0
        assert frame.reference_index == 0
        assert np.allclose(frame.u, u_true, atol=1e-6)
        assert np.allclose(frame.v, v_true, atol=1e-6)
        assert frame.zncc_median > 0.999


def test_reference_frame_is_correlated_rather_than_assumed():
    """Frame 0 against itself must come out exactly zero, not be shortcut."""
    config = Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=8), margin=20)
    run = run_sequence(MockCapture(frame_count=2, shape=(96, 96), seed=5), config)

    first = run.frames[0]
    assert np.all(first.status == int(Status.CONVERGED))
    assert np.allclose(first.p_total, 0.0, atol=1e-9)
    assert np.allclose(first.zncc, 1.0, atol=1e-9)
    # It really went through the solver: iterations were spent on it.
    assert np.all(first.iterations >= 1)


def test_capture_metadata_reaches_the_result():
    frames = list(MockCapture(frame_count=3, shape=(96, 96), seed=1, camera_id="cam-7"))
    config = Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=12), margin=20)
    run = run_sequence(frames, config)

    assert [f.camera_id for f in run.frames] == ["cam-7"] * 3
    assert [f.frame_index for f in run.frames] == [0, 1, 2]
    timestamps = [f.timestamp_s for f in run.frames]
    assert timestamps == sorted(timestamps)
    assert timestamps[1] == pytest.approx(1.0 / 30.0)


def test_dropped_capture_frames_keep_their_source_numbering():
    """A dropped acquisition must not renumber the frames that survived."""
    source = MockCapture(frame_count=4, shape=(96, 96), seed=2, drop_indices={1})
    # A gap in the sequence is a jump in displacement, which is what the
    # integer search is for; a carried seed alone would not bridge it.
    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=12, search_radius=8),
        margin=24,
        seed_mode=SeedMode.SOLVER,
    )
    run = run_sequence(source, config)

    assert run.n_frames == 3
    assert [f.index for f in run.frames] == [0, 1, 2]
    assert [f.frame_index for f in run.frames] == [0, 2, 3]
    # Ground truth follows the *source* index, which is the point of keeping it.
    for frame in run.frames:
        u_true, v_true = mock_truth(frame.frame_index)
        assert np.allclose(frame.u, u_true, atol=1e-6)
        assert np.allclose(frame.v, v_true, atol=1e-6)


def test_progress_callback_reports_every_frame():
    seen: list[tuple[int, int]] = []
    config = Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=16), margin=20)
    run_sequence(
        MockCapture(frame_count=3, shape=(96, 96), seed=4),
        config,
        progress=lambda done, total: seen.append((done, total)),
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_runs_are_bit_for_bit_reproducible():
    config = Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=12), margin=20)
    first = run_sequence(mock_frames(3), config)
    second = run_sequence(mock_frames(3), config)
    assert np.array_equal(first.field("u", masked=False), second.field("u", masked=False))
    assert np.array_equal(first.field("status"), second.field("status"))
    assert np.array_equal(first.field("zncc", masked=False), second.field("zncc", masked=False))


# --------------------------------------------------------------------------
# Sub-pixel accuracy through the pipeline
# --------------------------------------------------------------------------


def test_subpixel_translation_sequence(translation_sequence):
    images, shifts = translation_sequence
    run = run_sequence(images, PAIR_CONFIG)

    assert run.provenance["reference_updates"] == ()
    for frame, (u_true, v_true) in zip(run.frames, shifts):
        assert frame.valid_fraction == 1.0
        errors = np.concatenate((frame.u - u_true, frame.v - v_true))
        assert float(np.mean(np.abs(errors))) < 5e-3
        assert abs(float(np.mean(frame.u - u_true))) < 5e-3


def test_correlate_pair_matches_a_two_frame_sequence(translation_sequence):
    images, shifts = translation_sequence
    pair = correlate_pair(images[0], images[2], PAIR_CONFIG)
    assert pair.n_frames == 2
    assert np.allclose(pair.frames[1].u, shifts[2][0], atol=0.02)
    assert np.allclose(pair.frames[1].v, shifts[2][1], atol=0.02)


def test_seed_modes_agree_on_a_well_posed_sequence(translation_sequence):
    """PREV_FRAME is an accelerator, not a different answer."""
    images, _ = translation_sequence
    prev = run_sequence(images, PAIR_CONFIG)
    zero = run_sequence(
        images, dataclasses.replace(PAIR_CONFIG, seed_mode=SeedMode.ZERO)
    )

    assert np.allclose(
        prev.field("u", masked=False), zero.field("u", masked=False), atol=1e-4
    )
    # And it is not doing more work: a carried seed starts inside the basin.
    later = slice(1, None)
    assert prev.field("iterations")[later].sum() <= zero.field("iterations")[later].sum()


# --------------------------------------------------------------------------
# Fields
# --------------------------------------------------------------------------


def test_fields_are_gridded_and_masked():
    config = Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=10), margin=20)
    run = run_sequence(mock_frames(3), config)
    ny, nx = run.grid_shape

    displacement = run.field("u")
    assert displacement.shape == (3, ny, nx)
    assert displacement.dtype == np.float64
    assert np.all(np.isfinite(displacement))

    status = run.field("status")
    assert status.shape == (3, ny, nx)
    assert np.issubdtype(status.dtype, np.integer)
    assert np.all(status == int(Status.CONVERGED))
    assert run.valid_mask().shape == (3, ny, nx)


def test_failed_points_are_nan_in_masked_fields_and_diagnosed_in_status():
    """A POI whose subset leaves the image is a defined outcome, not a number."""
    params = ICGNParams(subset_radius=8, step=10)
    good = make_grid((96, 96), params, margin=20)
    points = np.vstack((good, [[1.0, 1.0]]))
    run = run_sequence(mock_frames(2), Dic2DConfig(icgn=params), points=points)

    assert run.grid_shape is None  # not a lattice any more
    assert run.field("u").shape == (2, points.shape[0])
    assert np.all(np.isnan(run.field("u")[:, -1]))
    assert not np.any(np.isnan(run.field("u")[:, :-1]))
    assert np.all(run.field("status")[:, -1] == int(Status.OUT_OF_BOUNDS))
    assert np.all(np.isfinite(run.field("u", masked=False)[:, -1]))
    assert run.frames[0].status_counts()[Status.OUT_OF_BOUNDS] == 1


def test_field_rejects_unknown_names():
    run = run_sequence(mock_frames(2), Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=16), margin=20))
    with pytest.raises(ValueError, match="unknown field"):
        run.field("E_xx")


def test_shape_function_gradients_are_exposed_but_not_turned_into_strain():
    """The pipeline reports ``p``'s gradients; tensors belong to hl3.strain."""
    run = run_sequence(mock_frames(2), Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=16), margin=20))
    for name in ("u_x", "u_y", "v_x", "v_y"):
        assert np.allclose(run.field(name), 0.0, atol=1e-4)


# --------------------------------------------------------------------------
# Reference updates
# --------------------------------------------------------------------------


def test_every_n_reference_updates_still_report_total_displacement():
    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=10),
        margin=24,
        reference_mode=ReferenceMode.EVERY_N,
        reference_every_n=1,
    )
    run = run_sequence(mock_frames(4), config)

    # Each frame is one frame away from its reference, so it promotes itself
    # as soon as it has been solved; frame 0 *is* the reference already.
    assert run.reference_updates == (1, 2, 3)
    assert [f.reference_index for f in run.frames] == [0, 0, 1, 2]
    for frame in run.frames:
        u_true, v_true = mock_truth(frame.index)
        assert frame.valid_fraction == 1.0
        assert np.allclose(frame.u, u_true, atol=1e-3)
        assert np.allclose(frame.v, v_true, atol=1e-3)


def test_incremental_reference_updates_trigger_on_zncc():
    images = speckle_sequence([(0.0, 0.0), (0.6, 0.3), (1.2, 0.6)])
    rng = np.random.default_rng(11)
    noisy = [np.clip(im + rng.normal(0.0, 3.0, im.shape), 0.0, 255.0) for im in images]

    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=10, step=12, zncc_min=0.5),
        margin=34,
        reference_mode=ReferenceMode.INCREMENTAL,
        reference_zncc=0.999,
    )
    run = run_sequence(noisy, config)

    assert run.reference_updates != ()
    assert run.provenance["reference_mode"] == "incremental"
    last = run.frames[-1]
    assert last.valid_fraction > 0.9
    assert float(np.nanmean(run.field("u")[-1])) == pytest.approx(1.2, abs=0.05)
    assert float(np.nanmean(run.field("v")[-1])) == pytest.approx(0.6, abs=0.05)


def test_a_lost_track_is_never_re_anchored_by_guesswork():
    """A point that failed at the switch cannot be placed in the new reference."""
    params = ICGNParams(subset_radius=8, step=10)
    points = np.vstack((make_grid((96, 96), params, margin=24), [[1.0, 1.0]]))
    config = Dic2DConfig(
        icgn=params,
        reference_mode=ReferenceMode.EVERY_N,
        reference_every_n=1,
    )
    run = run_sequence(mock_frames(3), config, points=points)

    assert run.frames[0].status[-1] == int(Status.OUT_OF_BOUNDS)
    assert run.frames[1].status[-1] == int(Status.OUT_OF_BOUNDS)
    # Frame 1 promoted itself to reference, and the failed point could not come
    # along: from frame 2 on it has no reference position at all, and says so
    # instead of reporting a displacement.
    assert run.frames[2].status[-1] == int(Status.NO_INITIAL_GUESS)
    assert np.all(np.isnan(run.field("u")[:, -1]))
    # The surviving points are unaffected.
    assert np.all(run.field("status")[:, :-1] == int(Status.CONVERGED))


def test_a_frame_where_nothing_converged_is_not_promoted_to_reference():
    params = ICGNParams(subset_radius=8, step=10)
    config = Dic2DConfig(
        icgn=params,
        margin=24,
        reference_mode=ReferenceMode.INCREMENTAL,
        reference_zncc=0.999,
    )
    frames = mock_frames(2)
    flat = np.full_like(frames[1].image, 128.0, dtype=np.float64)
    run = run_sequence([frames[0].image, flat, frames[1].image], config)

    assert run.frames[1].valid_fraction == 0.0
    assert not run.frames[1].reference_updated
    assert run.frames[2].reference_index == 0
    assert math.isnan(run.frames[1].zncc_median)


def test_reference_updates_require_a_leading_reference_frame():
    with pytest.raises(ValueError, match="reference_index == 0"):
        Dic2DConfig(reference_index=2, reference_mode=ReferenceMode.INCREMENTAL)


def test_a_later_reference_frame_is_allowed_when_fixed():
    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=12, search_radius=8),
        margin=24,
        reference_index=2,
        seed_mode=SeedMode.SOLVER,
    )
    run = run_sequence(mock_frames(3), config)

    assert all(f.reference_index == 2 for f in run.frames)
    assert np.allclose(run.frames[2].u, 0.0, atol=1e-6)
    # Frame 0 sits two steps *before* the reference, hence negative motion.
    assert np.allclose(run.frames[0].u, -4.0, atol=1e-6)
    assert np.allclose(run.frames[0].v, -2.0, atol=1e-6)


# --------------------------------------------------------------------------
# Input contracts
# --------------------------------------------------------------------------


def test_a_plain_image_stack_is_accepted():
    stack = np.stack([frame.image for frame in mock_frames(3)]).astype(np.float64)
    run = run_sequence(stack, Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=16), margin=20))
    assert run.n_frames == 3
    assert np.allclose(run.frames[2].u, 4.0, atol=1e-6)


def test_mismatched_frame_shapes_are_refused():
    frames = [np.zeros((40, 40)), np.zeros((40, 41))]
    with pytest.raises(ValueError, match="share the reference shape"):
        run_sequence(frames)


def test_non_2d_frames_are_refused():
    with pytest.raises(ValueError, match="2-D greyscale"):
        run_sequence([np.zeros((8, 8)), np.zeros((8, 8, 3))])


def test_an_empty_sequence_is_refused():
    with pytest.raises(ValueError, match="at least one frame"):
        run_sequence([])


def test_a_reference_outside_the_sequence_is_refused():
    config = Dic2DConfig(icgn=ICGNParams(subset_radius=4, step=8), reference_index=5)
    with pytest.raises(ValueError, match="outside the"):
        run_sequence(mock_frames(2), config)


def test_malformed_points_are_refused():
    frames = mock_frames(2)
    with pytest.raises(ValueError, match=r"\(n, 2\)"):
        run_sequence(frames, points=np.zeros((4, 3)))
    with pytest.raises(ValueError, match="finite"):
        run_sequence(frames, points=np.array([[np.nan, 1.0]]))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reference_index": -1},
        {"reference_every_n": 0},
        {"reference_zncc": 1.5},
        {"strain_window": 4},
        {"strain_window": 1},
        {"margin": -1},
    ],
)
def test_configuration_errors_are_caught_at_construction(kwargs):
    with pytest.raises((ValueError, TypeError)):
        Dic2DConfig(**kwargs)


def test_configuration_rejects_wrong_types():
    with pytest.raises(TypeError):
        Dic2DConfig(icgn="21x21")
    with pytest.raises(TypeError):
        Dic2DConfig(strain_backend=object())


def test_unusable_image_container_is_refused():
    with pytest.raises(TypeError, match="images must be"):
        run_sequence(42)


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def test_provenance_records_the_analysis_parameters():
    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=10, step=5, search_radius=3),
        margin=24,
        strain_window=5,
    )
    run = run_sequence(mock_frames(2, size=96), config)
    provenance = run.provenance

    assert provenance["solver"] == "hl3.correlate.icgn_first_order"
    assert provenance["subset_size"] == 21
    assert provenance["step"] == 5
    assert provenance["search_radius"] == 3
    assert provenance["l_vsg_px"] == vsg_size_px(21, 5, 5)
    assert provenance["image_shape"] == (96, 96)
    assert provenance["n_frames"] == 2
    assert provenance["n_points"] == run.n_points
    assert provenance["grid_shape"] == run.grid_shape
    assert provenance["deterministic"] is True
    assert provenance["valid_fraction_min"] == 1.0
    assert set(provenance["strain"]) == {"mode", "available", "backend", "reason"}


# --------------------------------------------------------------------------
# Optional strain hand-off
# --------------------------------------------------------------------------


def hide_strain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import hl3.strain`` fail, whether or not the module is merged."""

    def refuse(name: str, *args, **kwargs):
        if name == "hl3.strain":
            raise ImportError("no module named 'hl3.strain'")
        return _real_import(name, *args, **kwargs)

    _real_import = dic2d.importlib.import_module
    monkeypatch.setattr(dic2d.importlib, "import_module", refuse)


def install_strain(monkeypatch: pytest.MonkeyPatch, **attributes) -> types.ModuleType:
    """Put a stand-in ``hl3.strain`` in front of the real lookup."""
    module = types.ModuleType("hl3.strain")
    for name, value in attributes.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, "hl3.strain", module)
    return module


def stub_strain(u, v, valid=None, window=5, step_px=1.0):
    """A minimal well-behaved backend: central differences over the grid."""
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    u_x, u_y = np.gradient(u, step_px, axis=(1, 0))
    v_x, v_y = np.gradient(v, step_px, axis=(1, 0))
    return {
        "E_xx": u_x + 0.5 * (u_x**2 + v_x**2),
        "E_yy": v_y + 0.5 * (u_y**2 + v_y**2),
        "E_xy": 0.5 * (u_y + v_x + u_x * u_y + v_x * v_y),
    }


def test_missing_strain_module_downgrades_the_run(monkeypatch):
    hide_strain(monkeypatch)
    run = run_sequence(
        mock_frames(2), Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=16), margin=20)
    )

    assert run.strain.available is False
    assert "hl3.strain" in run.strain.reason
    assert run.strain.frames == ()
    assert run.strain.names == ()
    assert run.provenance["strain"]["available"] is False
    # The expensive half of the run survived the missing module.
    assert np.allclose(run.frames[1].u, 2.0, atol=1e-6)


def test_strain_field_on_a_downgraded_run_says_why(monkeypatch):
    hide_strain(monkeypatch)
    run = run_sequence(
        mock_frames(2), Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=16), margin=20)
    )
    with pytest.raises(StrainUnavailableError, match="hl3.strain"):
        run.strain_field("E_xx")


def test_required_strain_turns_a_missing_module_into_a_failure(monkeypatch):
    hide_strain(monkeypatch)
    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16),
        margin=20,
        strain_mode=StrainMode.REQUIRED,
    )
    with pytest.raises(StrainUnavailableError, match="hl3.strain"):
        run_sequence(mock_frames(2), config)


def test_strain_off_never_looks_for_the_module(monkeypatch):
    def explode(name, *args, **kwargs):
        raise AssertionError(f"strain lookup must not happen, got {name!r}")

    monkeypatch.setattr(dic2d.importlib, "import_module", explode)
    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16),
        margin=20,
        strain_mode=StrainMode.OFF,
    )
    run = run_sequence(mock_frames(2), config)
    assert run.strain.available is False
    assert run.strain.reason == "strain_mode is OFF"


def test_a_module_that_explodes_on_import_downgrades(monkeypatch):
    """A half-merged strain module must not take a correlation run with it."""

    def refuse(name, *args, **kwargs):
        raise RuntimeError("cannot import name 'DEFAULT_WINDOW' from hl3.strain.pls")

    monkeypatch.setattr(dic2d.importlib, "import_module", refuse)
    backend, name, reason = resolve_strain_backend()
    assert backend is None and name is None
    assert "RuntimeError" in reason and "not importable" in reason

    run = run_sequence(
        mock_frames(2), Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=16), margin=20)
    )
    assert run.strain.available is False
    assert np.allclose(run.frames[1].u, 2.0, atol=1e-6)


def test_a_module_without_a_known_entry_point_downgrades(monkeypatch):
    install_strain(monkeypatch, some_helper=lambda: None)
    backend, name, reason = resolve_strain_backend()
    assert backend is None and name is None
    assert "none of the expected entry points" in reason


def test_the_module_entry_point_is_discovered_and_called(monkeypatch):
    install_strain(monkeypatch, compute_strain=stub_strain)
    config = Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=10), margin=20)
    run = run_sequence(mock_frames(3), config)

    assert run.strain.available is True
    assert run.strain.backend == "hl3.strain.compute_strain"
    assert run.strain.names == ("E_xx", "E_xy", "E_yy")
    field = run.strain_field("E_xx")
    assert field.shape == (3,) + run.grid_shape
    # Rigid translation: every Green-Lagrange component must vanish, up to the
    # solver's own residual on the displacements that were differenced.
    assert np.allclose(field, 0.0, atol=1e-5)


def test_entry_points_are_tried_in_order(monkeypatch):
    install_strain(monkeypatch, compute_strain=stub_strain, strain_fields=stub_strain)
    backend, name, _ = resolve_strain_backend()
    assert name == "hl3.strain.strain_fields"
    assert backend is stub_strain


def test_an_injected_backend_wins_over_the_module(monkeypatch):
    install_strain(monkeypatch, compute_strain=stub_strain)

    def other(u, v, **kwargs):
        return {"E_xx": np.zeros_like(np.asarray(u, dtype=np.float64))}

    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16), margin=20, strain_backend=other
    )
    run = run_sequence(mock_frames(2), config)
    assert run.strain.backend == "other"
    assert run.strain.names == ("E_xx",)


def test_the_payload_is_trimmed_to_the_backend_signature():
    seen: list[set[str]] = []

    def narrow(u, v):
        seen.append({"u", "v"})
        return {"E_xx": np.zeros_like(np.asarray(u, dtype=np.float64))}

    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16), margin=20, strain_backend=narrow
    )
    run = run_sequence(mock_frames(2), config)
    assert run.strain.available is True
    assert len(seen) == run.n_frames


def test_a_backend_taking_var_keywords_gets_the_whole_payload():
    captured: dict[str, object] = {}

    def greedy(**kwargs):
        captured.update(kwargs)
        return {"E_xx": np.zeros_like(np.asarray(kwargs["u"], dtype=np.float64))}

    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16), margin=20, strain_backend=greedy
    )
    run = run_sequence(mock_frames(2), config)

    assert run.strain.available is True
    assert {"x", "y", "u", "v", "valid", "zncc", "window", "step_px", "grid_shape"} <= set(
        captured
    )
    assert captured["window"] == config.strain_window
    assert captured["step_px"] == float(config.step)
    assert np.asarray(captured["u"]).shape == run.grid_shape


def test_a_grid_backend_is_offered_gridded_arrays_first():
    shapes: list[tuple[int, ...]] = []

    def grid_only(u, v, valid):
        u = np.asarray(u, dtype=np.float64)
        if u.ndim != 2:
            raise ValueError("this backend needs a lattice")
        shapes.append(u.shape)
        return {"E_xx": np.zeros_like(u)}

    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16), margin=20, strain_backend=grid_only
    )
    run = run_sequence(mock_frames(2), config)
    assert run.strain.available is True
    assert shapes == [run.grid_shape] * run.n_frames


def test_a_flat_backend_is_still_reached_when_the_grid_call_fails():
    shapes: list[tuple[int, ...]] = []

    def flat_only(u, v):
        u = np.asarray(u, dtype=np.float64)
        if u.ndim != 1:
            raise ValueError("this backend needs a point list")
        shapes.append(u.shape)
        return {"E_xx": np.zeros_like(u)}

    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16), margin=20, strain_backend=flat_only
    )
    run = run_sequence(mock_frames(2), config)
    assert run.strain.available is True
    assert shapes == [(run.n_points,)] * run.n_frames


def test_an_incompatible_backend_is_reported_not_raised():
    def hostile(**kwargs):
        raise RuntimeError("strain module still under construction")

    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16), margin=20, strain_backend=hostile
    )
    run = run_sequence(mock_frames(2), config)

    assert run.strain.available is False
    assert "still under construction" in run.strain.reason
    assert run.provenance["strain"]["backend"] == "hostile"
    assert np.allclose(run.frames[1].u, 2.0, atol=1e-6)


def test_an_incompatible_backend_fails_the_run_when_strain_is_required():
    def hostile(**kwargs):
        raise RuntimeError("no strain today")

    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16),
        margin=20,
        strain_backend=hostile,
        strain_mode=StrainMode.REQUIRED,
    )
    with pytest.raises(StrainUnavailableError, match="no strain today"):
        run_sequence(mock_frames(2), config)


def test_a_backend_returning_nothing_useful_is_reported():
    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16),
        margin=20,
        strain_backend=lambda **kwargs: 42,
    )
    run = run_sequence(mock_frames(2), config)
    assert run.strain.available is False
    assert "mapping" in run.strain.reason


def test_an_object_returning_backend_is_unpacked():
    class Gradients:
        def __init__(self, u):
            self.u_x = np.zeros_like(u)
            self.v_y = np.zeros_like(u)
            self.window = 5  # not an array; must be dropped, not crash

    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16),
        margin=20,
        strain_backend=lambda u, **kwargs: Gradients(np.asarray(u, dtype=np.float64)),
    )
    run = run_sequence(mock_frames(2), config)
    assert run.strain.available is True
    assert run.strain.names == ("u_x", "v_y")


def test_strain_field_rejects_unknown_names():
    config = Dic2DConfig(
        icgn=ICGNParams(subset_radius=8, step=16), margin=20, strain_backend=stub_strain
    )
    run = run_sequence(mock_frames(2), config)
    with pytest.raises(ValueError, match="unknown strain field"):
        run.strain_field("E_zz")


def test_the_real_strain_module_is_used_when_it_is_importable():
    """Whatever hl3.strain currently is, the pipeline's verdict must be honest."""
    backend, name, reason = resolve_strain_backend()
    run = run_sequence(
        mock_frames(2), Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=16), margin=20)
    )
    assert reason
    if backend is None:
        assert run.strain.available is False
        assert run.strain.frames == ()
    elif run.strain.available:
        assert run.strain.backend == name
        assert len(run.strain.frames) == run.n_frames
        assert run.strain.names
    else:
        # Present but not callable with this payload: say so, keep the run.
        assert name in run.strain.reason
