# SPDX-License-Identifier: Apache-2.0
"""DIC ↔ FE geometry: scattered measurements on a triangle mesh, both ways.

Stage S4 of the implementation plan, and the first executable piece of the
"FEA closed loop" that ``R2-F1`` scores as B6 and ``R3-F4`` section S4 puts on
the critical path. Deliberately narrow: this package owns the *geometric*
hand-off between a DIC point cloud and a finite-element mesh, and nothing else.

::

    from hl3.fea import TriMesh, project_to_nodes, interpolate_at_points

    mesh = TriMesh(nodes, triangles)                      # (N, 2), (T, 3)
    nodal = project_to_nodes(mesh, poi_xy, u)             # DIC -> FE
    at_poi = interpolate_at_points(mesh, fe_u, poi_xy)    # FE  -> DIC
    residual = at_poi - u                                 # same support, at last

What this package does *not* do, and must not be read as doing:

* it does not compare a DIC field to an FE field. A residual is only meaningful
  once both sides went through the same filter chain -- an FE field sampled at
  the POI is unsmoothed while a DIC strain field carries a virtual strain gauge
  of ``(window_pts - 1) * step + subset`` pixels (:mod:`hl3.strain.vsg`), and
  differencing them without matching that is the classic way to publish a
  filter artefact as a model error. The equivalent-VSG comparison report and
  the normalised-residual ``z`` test are the next piece, and they sit on top of
  this one;
* it does not import or write mesh files. VTK / Exodus / Abaqus ``inp`` import
  belongs to an IO module with its own dependency footprint; here a mesh is two
  arrays, which is also what makes the package testable without any of them;
* it does not solve anything on the mesh. Global FE-DIC (``mode=GLOBAL_FE``) is
  a v1.x beta module by ``RUL-05``; a projection is not a solver, and calling
  one the other is the misrepresentation that rule exists to prevent.

Everything here is pure NumPy, double precision, deterministic and free of
random state: the same inputs give bit-identical outputs, which is a
prerequisite for the projection ever appearing in a validation report.
"""

from __future__ import annotations

from .project import (
    DEFAULT_BARY_TOL,
    DEFAULT_CG_TOL,
    PROJECTION_METHODS,
    NodalProjection,
    PointLocation,
    TriMesh,
    interpolate_at_points,
    locate_points,
    project_to_nodes,
)

__all__ = [
    "DEFAULT_BARY_TOL",
    "DEFAULT_CG_TOL",
    "PROJECTION_METHODS",
    "NodalProjection",
    "PointLocation",
    "TriMesh",
    "interpolate_at_points",
    "locate_points",
    "project_to_nodes",
]
