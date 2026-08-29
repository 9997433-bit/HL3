# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hl3.bench.download import cache_root, load_manifest
from hl3.bench.challenge2d import read_sample15_linecut, sample14_dir, sample15_dir
from hl3.stereo.calib_io import load_projection_matrix


def test_manifest_points_at_official_drive_ids() -> None:
    manifest = load_manifest()
    files = manifest["datasets"]["2d_challenge_1.0"]["files"]
    assert files["Sample14.zip"] == "13lG8piOhYXqMdvIFmmmRq9wzodoCAXhX"
    assert "1w0f7g6Jshbwl0k6mXwu3GjBd5hWUuGKH" in manifest["denied"]["sem_dic_round_robin"]["folder_id"]


def test_sem_dic_download_is_refused() -> None:
    from hl3.bench.download import download

    with pytest.raises(PermissionError, match="RUL-04"):
        download("sem")


def test_cache_root_honours_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HL3_CHALLENGE_ROOT", str(tmp_path))
    assert cache_root() == tmp_path.resolve()


def test_projection_matrix_round_trip(tmp_path: Path) -> None:
    matrix = np.array(
        [[1000.0, 0.0, 500.0, 0.0], [0.0, 1000.0, 400.0, 0.0], [0.0, 0.0, 1.0, 0.0]]
    )
    path = tmp_path / "P.txt"
    path.write_text("1000,0,500,0\n0;1000;400;0\n0 0 1 0\n")
    loaded = load_projection_matrix(path)
    np.testing.assert_allclose(loaded, matrix)


def test_sample15_linecut_parser_if_cached() -> None:
    folder = sample15_dir()
    if folder is None:
        pytest.skip("Sample 15 is not in the Challenge cache")
    table = read_sample15_linecut(next(folder.rglob("*.xlsx")))
    assert "y" in table and "k200" in table
    assert table["y"].shape[0] >= 100


@pytest.mark.slow
def test_sample15_linecut_rmse_if_cached() -> None:
    if sample15_dir() is None:
        pytest.skip("Sample 15 is not in the Challenge cache")
    pytest.importorskip("PIL")
    from hl3.bench.challenge2d import run_sample15

    # step=32 is a faster smoke than the published step=16 protocol;
    # write=False so the test cannot clobber the canonical JSON.
    payload = run_sample15(
        subset=21, step=32, k=200, search_radius=16, write=False
    )
    assert payload["valid_fraction"] > 0.5
    assert payload["linecut_rmse_px"] < 2.0


def test_sample14_present_or_skip() -> None:
    if sample14_dir() is None:
        pytest.skip("Sample 14 is not in the Challenge cache")
    tifs = list(sample14_dir().rglob("*.tif"))
    assert len(tifs) >= 2
