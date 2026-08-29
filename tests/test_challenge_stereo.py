# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from hl3.bench.challenge_stereo import translate_zip


def test_stereo_zip_absent_is_a_skip_not_a_crash() -> None:
    if translate_zip() is None:
        pytest.skip("Stereo Sample 1 Translate.zip is not in the Challenge cache")
    assert translate_zip().stat().st_size > 1_000_000


@pytest.mark.slow
def test_left_camera_diagnostic_if_cached() -> None:
    if translate_zip() is None:
        pytest.skip("Stereo Sample 1 Translate.zip is not in the Challenge cache")
    pytest.importorskip("PIL")
    from hl3.bench.challenge_stereo import run_left_camera_diagnostic

    payload = run_left_camera_diagnostic(
        subset=21, step=80, lens="35-mm", write=False
    )
    assert payload["calibration"] == "missing"
    assert "Stereo-DIC Challenge 3D score" in payload["claim"]
    assert payload["n_points"] > 0
    # 10 mm out-of-plane is not a 2D problem; low validity is the expected
    # diagnostic, not a silent success.
