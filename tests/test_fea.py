# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

import numpy as np

from hl3.fea import TriMesh, interpolate_at_points, project_to_nodes


def test_constant_field_round_trip() -> None:
    nodes = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    triangles = np.array([[0, 1, 2], [1, 3, 2]])
    mesh = TriMesh(nodes, triangles)
    samples = np.array([[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]])
    values = np.full(4, 3.0)
    nodal = project_to_nodes(mesh, samples, values, method="barycentric")
    np.testing.assert_allclose(nodal.values, 3.0, atol=1e-12)
    back = interpolate_at_points(mesh, nodal.values, samples)
    np.testing.assert_allclose(back, 3.0, atol=1e-12)


def test_linear_field_least_squares() -> None:
    nodes = np.array([[0.0, 0.0], [2.0, 0.0], [0.0, 2.0]])
    triangles = np.array([[0, 1, 2]])
    mesh = TriMesh(nodes, triangles)
    rng = np.random.default_rng(0)
    samples = rng.random((40, 2)) * 0.9
    # stay inside the triangle x>=0, y>=0, x+y<=2
    samples = samples[samples[:, 0] + samples[:, 1] < 1.8]
    truth = 2.0 * samples[:, 0] + 3.0 * samples[:, 1]
    nodal = project_to_nodes(mesh, samples, truth, method="least_squares")
    recovered = interpolate_at_points(mesh, nodal.values, samples)
    assert float(np.nanmax(np.abs(recovered - truth))) < 1e-8
