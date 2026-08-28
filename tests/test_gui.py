# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from hl3.gui.aoi import PolygonAOI, load_aoi, save_aoi


def test_gui_package_imports_without_matplotlib() -> None:
    import hl3.gui as gui

    assert hasattr(gui, "PolygonAOI")


def test_polygon_contains_square(tmp_path: Path) -> None:
    aoi = PolygonAOI(vertices=np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float))
    pts = np.array([[5.0, 5.0], [20.0, 5.0], [0.1, 0.1]])
    mask = aoi.contains(pts)
    assert bool(mask[0]) is True
    assert bool(mask[1]) is False
    path = tmp_path / "aoi.json"
    save_aoi(path, aoi)
    loaded = load_aoi(path)
    np.testing.assert_allclose(loaded.vertices, aoi.vertices)
    json.loads(path.read_text())


def test_viewer_help_does_not_need_gui_libraries() -> None:
    from hl3.gui.viewer import main

    assert main(["--help"]) == 0
    assert main(["-h"]) == 0


def test_viewer_module_entry_prints_help() -> None:
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "hl3.gui.viewer", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout
