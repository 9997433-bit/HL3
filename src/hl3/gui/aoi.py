# SPDX-License-Identifier: Apache-2.0
"""Polygon area-of-interest sidecar (JSON), independent of any GUI toolkit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["PolygonAOI", "load_aoi", "save_aoi"]


@dataclass(frozen=True)
class PolygonAOI:
    """Closed polygon in reference-image pixel coordinates."""

    vertices: np.ndarray  # (N, 2) float64, N >= 3
    name: str = "aoi"
    units: str = "px"

    def __post_init__(self) -> None:
        verts = np.asarray(self.vertices, dtype=np.float64)
        if verts.ndim != 2 or verts.shape[1] != 2:
            raise ValueError(f"vertices must be (N, 2), got {verts.shape}")
        if verts.shape[0] < 3:
            raise ValueError("a polygon needs at least 3 vertices")
        if not np.all(np.isfinite(verts)):
            raise ValueError("vertices must be finite")
        object.__setattr__(self, "vertices", np.ascontiguousarray(verts))

    def contains(self, xy: np.ndarray) -> np.ndarray:
        """Point-in-polygon for ``xy`` shape ``(P, 2)``. Uses even-odd winding."""
        pts = np.asarray(xy, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 2:
            raise ValueError(f"xy must be (P, 2), got {pts.shape}")
        verts = self.vertices
        x, y = pts[:, 0], pts[:, 1]
        x0, y0 = verts[:, 0], verts[:, 1]
        x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
        # Ray casting
        inside = np.zeros(pts.shape[0], dtype=bool)
        for xa, ya, xb, yb in zip(x0, y0, x1, y1):
            cond = ((ya > y) != (yb > y)) & (
                x < (xb - xa) * (y - ya) / (yb - ya + 1e-30) + xa
            )
            inside ^= cond
        return inside

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "units": self.units,
            "vertices": self.vertices.tolist(),
        }


def save_aoi(path: str | Path, aoi: PolygonAOI) -> None:
    target = Path(path)
    target.write_text(json.dumps(aoi.to_dict(), indent=2, sort_keys=True) + "\n")


def load_aoi(path: str | Path) -> PolygonAOI:
    payload = json.loads(Path(path).read_text())
    return PolygonAOI(
        vertices=np.asarray(payload["vertices"], dtype=np.float64),
        name=str(payload.get("name", "aoi")),
        units=str(payload.get("units", "px")),
    )
