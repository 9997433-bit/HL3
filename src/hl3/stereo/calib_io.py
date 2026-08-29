# SPDX-License-Identifier: Apache-2.0
"""Load published camera matrices. No microscope/SEM distortion models.

This module only ingests a 3x4 projection that already exists on disk. It does
not implement Brown–Conrady, Zhang planar calibration, or the non-parametric
stereo-microscopy distortion field. That last layer stays blocked behind the
patent-clearance opinion required by spec section 10.4.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

__all__ = ["load_projection_matrix", "projections_from_json"]


def load_projection_matrix(path: Path) -> np.ndarray:
    """Read a 3x4 projection matrix from ``.txt`` / ``.csv`` / ``.json`` / ``.npy``.

    Semicolon- or comma-delimited 3x4 tables are accepted. This is an ingest
    helper for Challenge-provided calibration dumps, not a Zhang solver.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".npy":
        matrix = np.load(path)
    elif suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        matrix = np.asarray(payload.get("P", payload), dtype=np.float64)
    else:
        text = path.read_text(encoding="utf-8")
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.replace(";", " ")
            line = line.replace(",", " ")
            values = [float(item) for item in line.split()]
            if values:
                rows.append(values)
        matrix = np.asarray(rows, dtype=np.float64)
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (3, 4):
        raise ValueError(f"{path}: expected a 3x4 projection, got {matrix.shape}")
    return matrix


def projections_from_json(path: Path) -> tuple[np.ndarray, np.ndarray]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    left = np.asarray(payload["P_left"], dtype=np.float64)
    right = np.asarray(payload["P_right"], dtype=np.float64)
    if left.shape != (3, 4) or right.shape != (3, 4):
        raise ValueError("P_left and P_right must be 3x4")
    return left, right
