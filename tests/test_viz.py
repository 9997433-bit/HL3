# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

import numpy as np

from hl3.viz import save_field


def test_builtin_png_and_ppm(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HL3_VIZ_BACKEND", "builtin")
    field = np.linspace(-1.0, 1.0, 64).reshape(8, 8)
    png = tmp_path / "u.png"
    ppm = tmp_path / "u.ppm"
    info = save_field(png, field, quantity="u", backend="builtin")
    assert png.is_file() and png.stat().st_size > 32
    assert info.backend == "builtin"
    save_field(ppm, field, quantity="u", backend="builtin")
    assert ppm.read_bytes()[:2] == b"P6"
