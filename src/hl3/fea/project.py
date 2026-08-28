# SPDX-License-Identifier: Apache-2.0
"""Scattered DIC samples onto the vertices of a triangle mesh, and back.

The DIC↔FE comparison of spec R1-O1 section 4.1 (roadmap item B6, ``R3-F4``
section S4) needs one geometric primitive before it needs anything else: a DIC
result lives on *its own* point cloud -- a POI lattice in image coordinates,
holes included -- and the FE model lives on *its own* mesh. Nothing can be
compared until one of them is expressed on the other's support. This module is
that primitive, in both directions:

* :func:`project_to_nodes` -- scattered ``(x, y, value)`` samples to nodal
  values (DIC → FE);
* :func:`interpolate_at_points` -- nodal values sampled back at arbitrary
  points (FE → DIC).

Both run through the same point location (:func:`locate_points`), so a
round trip is consistent by construction rather than by coincidence.

Three projections, and why there is more than one
-------------------------------------------------
``method="barycentric"`` (default) is the *lumped* L2 projection: a sample at
``x`` inside a triangle contributes to that triangle's three nodes with weights
equal to its barycentric coordinates -- which are exactly the P1 shape
functions ``N_i(x)`` -- and each node reports the weighted mean::

    a_i = sum_p N_i(x_p) v_p / sum_p N_i(x_p)

It is a weighted average, so it is *monotone*: a nodal value can never leave the
range of the samples that made it. That is the property you want when the field
being projected is going into a residual map, because an overshoot at a node
would read as a spurious strain concentration. Its cost is that it is only
exact for a constant field: for a linear field the node reports the value at the
weighted centroid of its support, which is not the node unless the samples
happen to be symmetric around it. Section 4 of the report quantifies this.

``method="least_squares"`` is the *consistent* L2 projection, i.e. the honest
one: the nodal vector that minimises ``||A a - v||^2`` where ``A[p, i] =
N_i(x_p)``. It reproduces any field the mesh can represent -- constant, linear,
piecewise linear on the mesh -- to rounding error, which makes it the right
choice when the projected field is going to be differentiated or compared to a
FE solution node by node. It is not monotone and can overshoot next to a jump.
The normal equations are solved matrix-free by conjugate gradients (three
non-zeros per row, so both ``A x`` and ``A^T r`` are one gather and one
``np.add.at``), starting from the lumped solution: no dense ``N x N`` matrix is
ever formed, and the null space -- nodes the data cannot determine -- keeps the
lumped answer instead of drifting.

``method="nearest"`` does no interpolation at all: each node takes the value of
the nearest sample within ``max_distance``. It is the fallback for a point cloud
too sparse for the mesh (fewer samples than nodes, or samples that miss whole
elements), and it is deliberately unglamorous, because reporting a nearest-value
fill *as* a nearest-value fill is better than silently widening a barycentric
support until something is found.

Failure conventions, matching :mod:`hl3.strain.pls` and
:mod:`hl3.stereo.triangulate`:

* broken calling code raises :class:`ValueError` -- wrong shapes, node indices
  out of range, degenerate (zero-area) triangles, unknown method names,
  non-positive tolerances;
* missing measurements propagate as ``nan`` -- a node no sample supports gets
  ``nan``, never a value extrapolated from the far side of the mesh, and the
  reason is recoverable from :class:`NodalProjection` (``n_samples`` is 0 there);
* samples that fall outside the mesh, or that carry ``nan`` values, are dropped
  and *counted* (``n_outside``, ``n_dropped``), because a projection that
  quietly ignored 90% of a field looks exactly like one that used all of it.

Coordinates are plain 2-D and unitless here: pass pixels and get a projection in
pixels, pass millimetres and get millimetres. What must not happen is mixing
them, which is why nothing in this module guesses a scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

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

PROJECTION_METHODS = ("barycentric", "least_squares", "nearest")

# Barycentric slack for "inside". A coordinate of -1e-9 means the sample missed
# the element by a billionth of its own size, which is a rounding artefact of
# the 2x2 solve, not a sample outside the mesh. Raise it (0.01 .. 0.05) to admit
# DIC points that genuinely sit just outside the meshed boundary; the accepted
# coordinates are then clipped to the element and renormalised, so the result
# stays a convex combination of the three nodes and the projection stays
# monotone.
DEFAULT_BARY_TOL = 1e-9

# Relative residual at which the consistent-projection CG stops. The normal
# equations are assembled in double precision from O(1) shape functions, so
# 1e-10 is ~4 decades above the noise floor of the assembly itself and costs a
# few dozen iterations on the meshes this module is meant for.
DEFAULT_CG_TOL = 1e-10

# Zero-area test for a triangle, relative to its own longest edge squared.
_AREA_EPS = 1e-12

# Candidate (point, triangle) pairs processed per chunk. Bounds peak memory of
# the location pass at a few tens of MB independently of the input size.
_PAIR_CHUNK = 1 << 20


@dataclass(frozen=True)
class TriMesh:
    """A 2-D triangle mesh: node coordinates and vertex indices.

    ``nodes`` is ``(N, 2)`` float, ``triangles`` is ``(T, 3)`` int holding node
    indices. Winding is free -- every barycentric formula here is written on the
    signed area, so clockwise and counter-clockwise elements both work and a
    mesh may mix them (which imported meshes do).

    The constructor validates and copies into contiguous ``float64`` /
    ``int64``, so a :class:`TriMesh` is always usable: no out-of-range index, no
    repeated vertex inside an element, no zero-area element, no ``nan``
    coordinate. Those are all *caller* errors -- there is no sensible value to
    return for a projection onto a mesh that folds -- so they raise here, once,
    instead of producing quiet ``nan`` later.
    """

    nodes: np.ndarray
    triangles: np.ndarray

    def __post_init__(self) -> None:
        nodes = np.array(self.nodes, dtype=float, copy=True)
        if nodes.ndim != 2 or nodes.shape[1] != 2:
            raise ValueError(
                f"nodes must be an (N, 2) array of 2-D coordinates, got shape "
                f"{nodes.shape}"
            )
        if nodes.shape[0] < 3:
            raise ValueError(
                f"a triangle mesh needs at least 3 nodes, got {nodes.shape[0]}"
            )
        if not np.all(np.isfinite(nodes)):
            bad = int(np.flatnonzero(~np.all(np.isfinite(nodes), axis=1))[0])
            raise ValueError(
                f"nodes must be finite; node {bad} is {tuple(nodes[bad])}"
            )

        tris = np.asarray(self.triangles)
        if tris.dtype.kind not in "iu":
            as_float = np.asarray(self.triangles, dtype=float)
            if not np.all(np.isfinite(as_float)) or np.any(
                as_float != np.floor(as_float)
            ):
                raise ValueError(
                    f"triangles must be integer node indices, got dtype {tris.dtype}"
                )
        tris = np.array(tris, dtype=np.int64, copy=True)
        if tris.ndim != 2 or tris.shape[1] != 3:
            raise ValueError(
                f"triangles must be a (T, 3) array of node indices, got shape "
                f"{tris.shape}"
            )
        if tris.shape[0] < 1:
            raise ValueError("a triangle mesh needs at least 1 element, got 0")
        if tris.min() < 0 or tris.max() >= nodes.shape[0]:
            raise ValueError(
                f"triangle node indices must lie in [0, {nodes.shape[0]}), got "
                f"[{int(tris.min())}, {int(tris.max())}]"
            )
        repeated = (
            (tris[:, 0] == tris[:, 1])
            | (tris[:, 1] == tris[:, 2])
            | (tris[:, 2] == tris[:, 0])
        )
        if repeated.any():
            first = int(np.flatnonzero(repeated)[0])
            raise ValueError(
                f"triangle {first} repeats a node index ({tris[first].tolist()}); "
                "it has no interior and no barycentric coordinates"
            )

        corners = nodes[tris]  # (T, 3, 2)
        twice_area = _twice_signed_area(corners)
        edges = np.diff(np.concatenate([corners, corners[:, :1]], axis=1), axis=1)
        scale = np.max(np.sum(edges * edges, axis=2), axis=1)  # longest edge^2
        degenerate = np.abs(twice_area) <= _AREA_EPS * scale
        if degenerate.any():
            first = int(np.flatnonzero(degenerate)[0])
            raise ValueError(
                f"triangle {first} ({tris[first].tolist()}) is degenerate: "
                f"|2A| = {abs(float(twice_area[first])):.3e} against a longest "
                f"edge^2 of {float(scale[first]):.3e}. Collinear vertices have no "
                "unique barycentric coordinates, so the mesh must be repaired "
                "rather than projected onto"
            )

        nodes.flags.writeable = False
        tris.flags.writeable = False
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "triangles", tris)

    @property
    def n_nodes(self) -> int:
        return int(self.nodes.shape[0])

    @property
    def n_triangles(self) -> int:
        return int(self.triangles.shape[0])

    @property
    def areas(self) -> np.ndarray:
        """Unsigned element areas, shape ``(T,)``."""
        return 0.5 * np.abs(_twice_signed_area(self.nodes[self.triangles]))

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """``(xmin, ymin, xmax, ymax)`` of the node cloud."""
        lo = self.nodes.min(axis=0)
        hi = self.nodes.max(axis=0)
        return (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))

    def node_valence(self) -> np.ndarray:
        """Elements incident on each node, shape ``(N,)`` int.

        Zero marks an orphan node: no element references it, so no sample can
        ever support it and its projected value is ``nan`` by construction.
        Importers produce these routinely (a mesh trimmed to a surface keeps the
        full node table), which is why this is a query rather than an error.
        """
        counts = np.zeros(self.n_nodes, dtype=np.int64)
        np.add.at(counts, self.triangles.ravel(), 1)
        return counts


@dataclass(frozen=True)
class PointLocation:
    """Which element each query point landed in, and where inside it.

    ``triangle`` is ``(P,)`` int with ``-1`` for points outside every element;
    ``bary`` is ``(P, 3)`` holding the barycentric coordinates against
    ``mesh.triangles[triangle]``, with ``nan`` rows where ``triangle == -1``.
    Accepted rows are non-negative and sum to 1 to rounding error, so they can
    be used directly as interpolation weights.
    """

    triangle: np.ndarray
    bary: np.ndarray
    n_candidates: int = 0

    @property
    def inside(self) -> np.ndarray:
        return self.triangle >= 0

    @property
    def n_inside(self) -> int:
        return int(np.count_nonzero(self.inside))


@dataclass(frozen=True)
class NodalProjection:
    """Nodal values and the provenance needed to judge them.

    ``values`` is ``(N,)`` for a scalar field or ``(N, K)`` when several
    components were projected at once (the ``u, v`` pair, or a whole strain
    triplet); the component axis is passed through untouched, and the weights
    are computed once for all of them.

    Everything else is the audit trail. ``n_samples`` is how many samples
    actually reached each node, ``weight`` is the sum of their shape functions
    (the diagonal of the lumped mass matrix, i.e. how well the node is
    supported), and ``filled_by_nearest`` marks nodes whose value did not come
    from the requested method at all but from the nearest-sample fallback. A
    projection is not interpretable without these: coverage of 0.6 with the
    remaining 0.4 nearest-filled is a different result from coverage of 1.0, and
    a colour map of ``values`` alone cannot tell them apart.
    """

    values: np.ndarray
    n_samples: np.ndarray
    weight: np.ndarray
    nearest_distance: np.ndarray
    filled_by_nearest: np.ndarray
    method: str
    n_points: int
    n_located: int
    n_outside: int
    n_dropped: int
    iterations: int = 0
    residual: float = float("nan")
    mesh_bounds: tuple[float, float, float, float] = (float("nan"),) * 4

    @property
    def valid(self) -> np.ndarray:
        """Nodes that carry a value, shape ``(N,)``."""
        if self.values.ndim == 1:
            return np.isfinite(self.values)
        return np.all(np.isfinite(self.values), axis=1)

    @property
    def n_nodes(self) -> int:
        return int(self.values.shape[0])

    @property
    def coverage(self) -> float:
        """Fraction of nodes with a value, in ``[0, 1]``."""
        if self.n_nodes == 0:
            return 0.0
        return float(np.count_nonzero(self.valid)) / float(self.n_nodes)


def _twice_signed_area(corners: np.ndarray) -> np.ndarray:
    """``2A`` for triangles given as ``(..., 3, 2)`` corner coordinates."""
    a = corners[..., 0, :]
    b = corners[..., 1, :]
    c = corners[..., 2, :]
    return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (
        c[..., 0] - a[..., 0]
    ) * (b[..., 1] - a[..., 1])


def _check_mesh(mesh: object) -> None:
    """Insist on a validated :class:`TriMesh` rather than a raw array pair.

    ``TypeError`` and not ``ValueError`` here: the rest of this module answers a
    malformed *value* with ``ValueError`` and a missing measurement with
    ``nan``, but a wrong *type* is neither -- and accepting a bare ``(nodes,
    triangles)`` tuple would mean re-validating the mesh on every call or, worse,
    skipping the validation that :class:`TriMesh` exists to perform.
    """
    if not isinstance(mesh, TriMesh):
        raise TypeError(
            f"mesh must be a TriMesh (build one with TriMesh(nodes, triangles)), "
            f"got {type(mesh).__name__}"
        )


def _as_points(points: np.ndarray, name: str = "points") -> np.ndarray:
    arr = np.asarray(points, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(
            f"{name} must be an (P, 2) array of 2-D coordinates, got shape "
            f"{arr.shape}"
        )
    return arr


def _as_positive(value: float, name: str) -> float:
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")
    return out


def _ragged_ranges(starts: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Concatenated ``range(start, start + count)`` for each pair, vectorised."""
    total = int(counts.sum())
    if total == 0:
        return np.empty(0, dtype=np.int64)
    offsets = np.repeat(np.cumsum(counts) - counts, counts)
    return np.repeat(starts, counts) + (np.arange(total, dtype=np.int64) - offsets)


class _CellIndex:
    """Uniform-bin index over triangle bounding boxes.

    Point location is the only part of this module that is not O(P + N) by
    inspection: done naively it is O(P x T), which is 10^10 operations for a
    modest 100k-sample cloud on a 100k-element mesh. Binning triangle bounding
    boxes into a uniform grid and testing a point only against the triangles of
    its own cell brings it back to O(P) with a small constant, and -- unlike a
    tree -- it builds and queries with pure vectorised NumPy, no per-node Python.

    The resolution is chosen so that the *expansion* (a triangle is listed in
    every cell its bounding box touches) stays bounded: a mesh with wildly
    mixed element sizes would otherwise list one big triangle in thousands of
    cells. The build halves the resolution until the expansion fits the budget,
    ending at a single cell -- i.e. brute force -- for a pathological mesh,
    which is slow but never wrong.
    """

    def __init__(self, mesh: TriMesh, *, max_expansion: float = 8.0) -> None:
        corners = mesh.nodes[mesh.triangles]
        self.lo = corners.min(axis=1)  # (T, 2)
        self.hi = corners.max(axis=1)
        x0, y0, x1, y1 = mesh.bounds
        self.origin = np.array([x0, y0], dtype=float)
        self.node_lo = np.array([x0, y0], dtype=float)
        self.node_hi = np.array([x1, y1], dtype=float)
        span = np.array([x1 - x0, y1 - y0], dtype=float)
        # A flat or vertical mesh has zero span on one axis; one cell there.
        self.span = np.where(span > 0.0, span, 1.0)
        edges = self.hi - self.lo
        self.max_edge = float(edges.max()) if edges.size else 0.0

        n_tri = mesh.n_triangles
        res = int(min(512, max(1, round(math.sqrt(n_tri)))))
        while True:
            self.res = res
            cell_lo = self._cell_of(self.lo)
            cell_hi = self._cell_of(self.hi)
            counts = np.prod(cell_hi - cell_lo + 1, axis=1)
            total = int(counts.sum())
            if res == 1 or total <= max_expansion * n_tri + 64:
                break
            res = max(1, res // 2)

        # (triangle, cell) pairs: expand each bounding box over its cell range.
        tri_ids = np.repeat(np.arange(n_tri, dtype=np.int64), counts)
        widths = (cell_hi[:, 0] - cell_lo[:, 0] + 1)[tri_ids]
        local = _ragged_ranges(np.zeros(n_tri, dtype=np.int64), counts)
        ix = cell_lo[tri_ids, 0] + local % widths
        iy = cell_lo[tri_ids, 1] + local // widths
        cell_ids = iy * self.res + ix

        n_cells = self.res * self.res
        cell_counts = np.zeros(n_cells, dtype=np.int64)
        np.add.at(cell_counts, cell_ids, 1)
        self.offsets = np.zeros(n_cells + 1, dtype=np.int64)
        np.cumsum(cell_counts, out=self.offsets[1:])
        order = np.argsort(cell_ids, kind="stable")
        self.items = tri_ids[order]

    def _cell_of(self, xy: np.ndarray) -> np.ndarray:
        frac = (xy - self.origin) / self.span
        idx = np.floor(frac * self.res).astype(np.int64)
        return np.clip(idx, 0, self.res - 1)

    def candidates(
        self, points: np.ndarray, pad: float = 0.0
    ) -> tuple[np.ndarray, np.ndarray]:
        """``(point_index, triangle_index)`` pairs worth testing exactly.

        Points that are not finite, or that lie outside the mesh bounding box,
        produce no pairs at all: they cannot be inside any element, and a
        DIC cloud usually has a lot of them (the field is rectangular, the
        specimen is not).
        """
        finite = np.all(np.isfinite(points), axis=1)
        probe = np.where(finite[:, None], points, self.origin)
        in_box = finite & np.all(
            (probe >= self.node_lo - pad) & (probe <= self.node_hi + pad), axis=1
        )
        safe = np.where(in_box[:, None], probe, self.origin)
        cells = self._cell_of(safe)
        cell_ids = cells[:, 1] * self.res + cells[:, 0]
        counts = np.where(
            in_box, self.offsets[cell_ids + 1] - self.offsets[cell_ids], 0
        )
        pair_point = np.repeat(np.arange(points.shape[0], dtype=np.int64), counts)
        slots = _ragged_ranges(self.offsets[cell_ids], counts)
        return pair_point, self.items[slots]


def locate_points(
    mesh: TriMesh,
    points: np.ndarray,
    *,
    bary_tol: float = DEFAULT_BARY_TOL,
) -> PointLocation:
    """Find the element containing each point and its barycentric coordinates.

    Parameters
    ----------
    mesh
        The target mesh.
    points
        ``(P, 2)`` query coordinates in the mesh's own coordinate system. Points
        holding ``nan`` are reported as outside rather than raising: a DIC point
        cloud carries dropouts, and a dropout is missing data, not a bug.
    bary_tol
        Slack on "inside", in barycentric units (so it scales with the element,
        not with the mesh). ``1e-9`` admits only rounding; a value like ``0.02``
        admits samples up to 2% of an element outside the boundary and clips
        them onto it.

    Returns
    -------
    PointLocation
        ``triangle`` (``-1`` where outside) and ``bary`` (``nan`` rows where
        outside, otherwise non-negative and summing to 1).

    Notes
    -----
    A point on a shared edge or at a node is inside several elements. The choice
    is made deterministically -- highest minimum barycentric coordinate, ties
    broken by the lowest element index -- so two runs on the same input, and two
    machines running the same input, agree exactly. Any interpolated *value* is
    identical whichever of the tied elements is chosen, since P1 fields are
    continuous across an edge; what the rule protects is the ``triangle`` field
    itself and everything downstream that keys off it.
    """
    _check_mesh(mesh)
    pts = _as_points(points)
    tol = float(bary_tol)
    if not math.isfinite(tol) or tol < 0.0:
        raise ValueError(f"bary_tol must be finite and >= 0, got {bary_tol!r}")

    n_points = pts.shape[0]
    tri_out = np.full(n_points, -1, dtype=np.int64)
    bary_out = np.full((n_points, 3), np.nan)
    if n_points == 0:
        return PointLocation(triangle=tri_out, bary=bary_out, n_candidates=0)

    index = _CellIndex(mesh)
    # A barycentric slack of ``tol`` lets a point sit at most ``tol`` times the
    # element height outside it, which is bounded by ``tol * max_edge``; the
    # bounding-box rejection has to be that much looser or it would throw away
    # exactly the points the slack was asked to admit.
    pair_point, pair_tri = index.candidates(pts, pad=tol * index.max_edge)
    n_candidates = int(pair_point.size)
    if n_candidates == 0:
        return PointLocation(triangle=tri_out, bary=bary_out, n_candidates=0)

    corners_all = mesh.nodes[mesh.triangles]
    best_score = np.full(n_points, -np.inf)

    for start in range(0, n_candidates, _PAIR_CHUNK):
        stop = min(start + _PAIR_CHUNK, n_candidates)
        p_idx = pair_point[start:stop]
        t_idx = pair_tri[start:stop]
        corners = corners_all[t_idx]
        a = corners[:, 0, :]
        v0 = corners[:, 1, :] - a
        v1 = corners[:, 2, :] - a
        v2 = pts[p_idx] - a
        det = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        l1 = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / det
        l2 = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / det
        l0 = 1.0 - l1 - l2
        bary = np.stack([l0, l1, l2], axis=1)
        score = np.min(bary, axis=1)
        score = np.where(np.isfinite(score), score, -np.inf)
        hit = score >= -tol
        if not hit.any():
            continue
        p_hit = p_idx[hit]
        s_hit = score[hit]
        t_hit = t_idx[hit]
        b_hit = bary[hit]
        # Deterministic pick: best score first, lowest element index on a tie.
        # The lexsort key order is minor-to-major, so element index is the
        # tie-break and the (point, -score) pair leads.
        order = np.lexsort((t_hit, -s_hit, p_hit))
        p_sorted = p_hit[order]
        first = np.ones(p_sorted.size, dtype=bool)
        first[1:] = p_sorted[1:] != p_sorted[:-1]
        cand_p = p_sorted[first]
        cand_s = s_hit[order][first]
        cand_t = t_hit[order][first]
        cand_b = b_hit[order][first]
        take = cand_s > best_score[cand_p]
        if take.any():
            sel_p = cand_p[take]
            best_score[sel_p] = cand_s[take]
            tri_out[sel_p] = cand_t[take]
            bary_out[sel_p] = cand_b[take]

    inside = tri_out >= 0
    if inside.any():
        # Clip the tolerance slack away and renormalise, so the weights stay a
        # convex combination: without this a sample admitted at -tol would carry
        # a negative weight into the projection and could push a nodal value
        # outside the range of its own samples.
        clipped = np.clip(bary_out[inside], 0.0, None)
        clipped /= clipped.sum(axis=1, keepdims=True)
        bary_out[inside] = clipped

    return PointLocation(
        triangle=tri_out, bary=bary_out, n_candidates=n_candidates
    )


def _as_values(values: np.ndarray, n_points: int) -> tuple[np.ndarray, bool]:
    arr = np.asarray(values, dtype=float)
    scalar = arr.ndim == 1
    if scalar:
        arr = arr[:, None]
    if arr.ndim != 2:
        raise ValueError(
            f"values must be (P,) or (P, K), got shape {np.asarray(values).shape}"
        )
    if arr.shape[0] != n_points:
        raise ValueError(
            f"values must have one row per point, got {arr.shape[0]} values for "
            f"{n_points} points"
        )
    return arr, scalar


def _nearest_fill(
    mesh: TriMesh,
    points: np.ndarray,
    values: np.ndarray,
    usable: np.ndarray,
    targets: np.ndarray,
    max_distance: float | None,
    chunk: int = 4096,
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest usable sample for each target node.

    Returns ``(value_rows, distance)`` with ``nan`` where nothing qualified.
    Brute force in chunks: O(N_target x P) distance evaluations, vectorised.
    A k-d tree would be O(N log P), but SciPy is not a dependency of this
    package (see ``R1-G3``) and a hand-rolled tree is a lot of surface area for
    a fallback path. For the mesh sizes this module is used on today the flat
    scan is milliseconds; when that stops being true, the replacement is a
    ``scipy.spatial.cKDTree`` behind the optional-dependency guard, not a
    change to this function's contract.
    """
    n_comp = values.shape[1]
    out = np.full((targets.size, n_comp), np.nan)
    dist = np.full(targets.size, np.nan)
    src_idx = np.flatnonzero(usable)
    if src_idx.size == 0 or targets.size == 0:
        return out, dist
    src_xy = points[src_idx]
    limit = math.inf if max_distance is None else max_distance
    for start in range(0, targets.size, chunk):
        stop = min(start + chunk, targets.size)
        block = mesh.nodes[targets[start:stop]]
        d2 = np.sum((block[:, None, :] - src_xy[None, :, :]) ** 2, axis=2)
        best = np.argmin(d2, axis=1)
        best_d = np.sqrt(d2[np.arange(best.size), best])
        ok = best_d <= limit
        rows = np.arange(start, stop)[ok]
        out[rows] = values[src_idx[best[ok]]]
        dist[rows] = best_d[ok]
    return out, dist


def _least_squares_nodes(
    tri_nodes: np.ndarray,
    weights: np.ndarray,
    values: np.ndarray,
    lumped: np.ndarray,
    solvable: np.ndarray,
    n_nodes: int,
    tol: float,
    max_iter: int,
) -> tuple[np.ndarray, int, float]:
    """Consistent P1 projection by matrix-free conjugate gradients.

    Solves ``A^T A a = A^T v`` where ``A[p, i] = N_i(x_p)``. ``A`` has exactly
    three non-zeros per row, so both products are one gather and one scatter and
    the whole solve is O(iterations x samples) with no assembly.

    Starting from the lumped solution matters twice over: it is already close,
    so the iteration count is small, and its component in the null space (nodes
    the samples cannot determine, e.g. one sample supporting three nodes) is
    what the solution keeps -- CG only moves inside the Krylov space, which is
    orthogonal to the null space. Unsupported nodes therefore stay at the lumped
    ``nan``-to-be rather than picking up an arbitrary value.
    """
    n_comp = values.shape[1]
    flat_nodes = tri_nodes.ravel()
    flat_w = weights.ravel()
    mask = solvable[:, None]

    def a_mul(x: np.ndarray) -> np.ndarray:
        """``A x``: nodal field -> sample field, ``(N, K) -> (S, K)``."""
        return np.einsum("pj,pjk->pk", weights, x[tri_nodes])

    def at_mul(r: np.ndarray) -> np.ndarray:
        """``A^T r``: sample field -> nodal field, ``(S, K) -> (N, K)``."""
        out = np.empty((n_nodes, n_comp))
        for k in range(n_comp):
            out[:, k] = np.bincount(
                flat_nodes,
                weights=flat_w * np.repeat(r[:, k], 3),
                minlength=n_nodes,
            )
        return out

    def normal_mul(x: np.ndarray) -> np.ndarray:
        return at_mul(a_mul(x)) * mask

    x = np.where(mask, lumped, 0.0)
    rhs = at_mul(values) * mask
    r = rhs - normal_mul(x)
    # Jacobi preconditioner: diag(A^T A)_i = sum_p N_i(x_p)^2.
    diag = np.bincount(flat_nodes, weights=flat_w**2, minlength=n_nodes)
    inv_diag = np.where(
        solvable & (diag > 0.0), 1.0 / np.where(diag > 0.0, diag, 1.0), 0.0
    )
    z = r * inv_diag[:, None]
    p = z.copy()
    rz = float(np.sum(r * z))
    scale = float(np.linalg.norm(rhs)) or 1.0
    residual = float(np.linalg.norm(r)) / scale

    iterations = 0
    while iterations < max_iter and residual > tol and rz > 0.0:
        ap = normal_mul(p)
        denom = float(np.sum(p * ap))
        if denom <= 0.0:  # exhausted the range space; nothing left to correct
            break
        alpha = rz / denom
        x += alpha * p
        r -= alpha * ap
        iterations += 1
        residual = float(np.linalg.norm(r)) / scale
        z = r * inv_diag[:, None]
        rz_new = float(np.sum(r * z))
        p = z + (rz_new / rz) * p
        rz = rz_new
    return x, iterations, residual


def project_to_nodes(
    mesh: TriMesh,
    points: np.ndarray,
    values: np.ndarray,
    *,
    method: str = "barycentric",
    bary_tol: float = DEFAULT_BARY_TOL,
    min_samples: int = 1,
    max_distance: float | None = None,
    fill_nearest: bool = False,
    cg_tol: float = DEFAULT_CG_TOL,
    max_iter: int | None = None,
    location: PointLocation | None = None,
) -> NodalProjection:
    """Project scattered ``(x, y, value)`` samples onto mesh nodes.

    Parameters
    ----------
    mesh
        Target :class:`TriMesh`.
    points
        ``(P, 2)`` sample coordinates, in the mesh's coordinate system. For a
        DIC field this is the POI reference position (``grid/ref_xy`` of
        ``docs/schema-hdf5.md`` section 9.1) after whatever rigid mapping takes
        image coordinates to model coordinates -- this module does not invent
        that mapping, it consumes it.
    values
        ``(P,)`` or ``(P, K)`` sample values. ``nan`` marks a sample the DIC did
        not solve; such samples are dropped, and a row of a ``(P, K)`` block is
        dropped as a whole so that all components describe the same support.
    method
        One of :data:`PROJECTION_METHODS`. See the module docstring for what
        each one is exact for.
    bary_tol
        Passed to :func:`locate_points`.
    min_samples
        Nodes reached by fewer than this many samples are ``nan``. The default
        of 1 keeps every supported node; raising it is the cheap way to refuse
        nodes whose value rests on a single measurement.
    max_distance
        Cut-off for ``method="nearest"`` and for ``fill_nearest``, in coordinate
        units. ``None`` means unlimited, which on a mesh larger than the DIC
        field will happily fill a far corner from the nearest edge sample -- so
        set it to something like the POI pitch unless you want that.
    fill_nearest
        Fill nodes the primary method left empty with the nearest sample value.
        Off by default, and always recorded in ``filled_by_nearest``: an
        interpolated node and a nearest-copied node must remain distinguishable
        downstream.
    cg_tol, max_iter
        Convergence controls for ``method="least_squares"``. The achieved
        relative residual is reported in ``NodalProjection.residual`` and
        callers that care should check it.
    location
        A :class:`PointLocation` for these exact points, if one has already been
        computed (projecting ``u``, ``v`` and three strain components separately
        should locate once, not five times).

    Returns
    -------
    NodalProjection
        Nodal values plus the support statistics described in that class.
    """
    _check_mesh(mesh)
    if method not in PROJECTION_METHODS:
        raise ValueError(
            f"method must be one of {PROJECTION_METHODS}, got {method!r}"
        )
    pts = _as_points(points)
    vals, scalar = _as_values(values, pts.shape[0])
    if isinstance(min_samples, bool) or min_samples != int(min_samples):
        raise ValueError(f"min_samples must be an integer, got {min_samples!r}")
    min_samples = int(min_samples)
    if min_samples < 1:
        raise ValueError(f"min_samples must be >= 1, got {min_samples}")
    if max_distance is not None:
        max_distance = _as_positive(max_distance, "max_distance")
    cg_tol = _as_positive(cg_tol, "cg_tol")
    if max_iter is not None:
        if isinstance(max_iter, bool) or max_iter != int(max_iter) or max_iter < 1:
            raise ValueError(f"max_iter must be an integer >= 1, got {max_iter!r}")
        max_iter = int(max_iter)

    n_nodes = mesh.n_nodes
    n_comp = vals.shape[1]
    finite_pts = np.all(np.isfinite(pts), axis=1)
    finite_vals = np.all(np.isfinite(vals), axis=1)
    usable = finite_pts & finite_vals
    n_dropped = int(np.count_nonzero(finite_pts & ~finite_vals))

    n_samples = np.zeros(n_nodes, dtype=np.int64)
    weight = np.zeros(n_nodes)
    nearest_distance = np.full(n_nodes, np.nan)
    filled = np.zeros(n_nodes, dtype=bool)
    iterations = 0
    residual = float("nan")
    n_located = 0
    n_outside = 0

    if method == "nearest":
        node_vals, node_dist = _nearest_fill(
            mesh,
            pts,
            vals,
            usable,
            np.arange(n_nodes, dtype=np.int64),
            max_distance,
        )
        nearest_distance = node_dist
        n_samples = np.where(np.isfinite(node_dist), 1, 0).astype(np.int64)
        weight = np.where(np.isfinite(node_dist), 1.0, 0.0)
        node_vals = np.where(np.isfinite(node_dist)[:, None], node_vals, np.nan)
    else:
        if location is None:
            location = locate_points(mesh, pts, bary_tol=bary_tol)
        elif location.triangle.shape[0] != pts.shape[0]:
            raise ValueError(
                f"location has {location.triangle.shape[0]} entries for "
                f"{pts.shape[0]} points"
            )
        inside = location.inside & usable
        n_located = int(np.count_nonzero(inside))
        n_outside = int(np.count_nonzero(finite_pts & finite_vals & ~location.inside))

        tri_nodes = mesh.triangles[location.triangle[inside]]  # (S, 3)
        w = location.bary[inside]  # (S, 3)
        v = vals[inside]  # (S, K)

        flat_nodes = tri_nodes.ravel()
        flat_w = w.ravel()
        weight = np.bincount(flat_nodes, weights=flat_w, minlength=n_nodes)
        n_samples = np.bincount(
            flat_nodes, weights=(flat_w > 0.0).astype(float), minlength=n_nodes
        ).astype(np.int64)
        num = np.empty((n_nodes, n_comp))
        for k in range(n_comp):
            num[:, k] = np.bincount(
                flat_nodes,
                weights=(w * v[:, k : k + 1]).ravel(),
                minlength=n_nodes,
            )

        # Two masks, deliberately different. ``solvable`` is the support of the
        # operator -- the nodes the samples can say anything about at all -- and
        # is what the solve runs over. ``supported`` additionally applies
        # ``min_samples`` and is what the caller gets to see. Filtering before
        # the solve instead would fix the rejected nodes at zero and pull their
        # neighbours towards it, which is a silent bias, not a rejection.
        solvable = weight > 0.0
        supported = solvable & (n_samples >= min_samples)
        safe = np.where(solvable, weight, 1.0)[:, None]
        lumped = np.where(solvable[:, None], num / safe, 0.0)

        if method == "barycentric":
            node_vals = np.where(supported[:, None], lumped, np.nan)
        else:
            if max_iter is None:
                max_iter = max(50, 4 * int(np.count_nonzero(solvable)))
            solved, iterations, residual = _least_squares_nodes(
                tri_nodes,
                w,
                v,
                lumped,
                solvable,
                n_nodes,
                cg_tol,
                max_iter,
            )
            node_vals = np.where(supported[:, None], solved, np.nan)

    if fill_nearest:
        missing = np.flatnonzero(~np.all(np.isfinite(node_vals), axis=1))
        if missing.size:
            fill_vals, fill_dist = _nearest_fill(
                mesh, pts, vals, usable, missing, max_distance
            )
            got = np.all(np.isfinite(fill_vals), axis=1)
            rows = missing[got]
            node_vals[rows] = fill_vals[got]
            nearest_distance[rows] = fill_dist[got]
            filled[rows] = True

    return NodalProjection(
        values=node_vals[:, 0] if scalar else node_vals,
        n_samples=n_samples,
        weight=weight,
        nearest_distance=nearest_distance,
        filled_by_nearest=filled,
        method=method,
        n_points=int(pts.shape[0]),
        n_located=n_located,
        n_outside=n_outside,
        n_dropped=n_dropped,
        iterations=iterations,
        residual=residual,
        mesh_bounds=mesh.bounds,
    )


def interpolate_at_points(
    mesh: TriMesh,
    nodal_values: np.ndarray,
    points: np.ndarray,
    *,
    bary_tol: float = DEFAULT_BARY_TOL,
    location: PointLocation | None = None,
) -> np.ndarray:
    """Sample a P1 nodal field at arbitrary points (FE → DIC).

    The other half of the comparison: with the FE solution interpolated onto the
    DIC point cloud, the two fields live on the same support and their
    difference is a residual map rather than an apples-to-oranges plot.

    ``nodal_values`` is ``(N,)`` or ``(N, K)``; the result has one row per point
    with the same trailing shape. Points outside the mesh are ``nan``, and so
    are points inside an element with a ``nan`` node -- a hole in the nodal field
    is not interpolated across, it propagates.
    """
    _check_mesh(mesh)
    pts = _as_points(points)
    nodal = np.asarray(nodal_values, dtype=float)
    scalar = nodal.ndim == 1
    if scalar:
        nodal = nodal[:, None]
    if nodal.ndim != 2 or nodal.shape[0] != mesh.n_nodes:
        raise ValueError(
            f"nodal_values must be (N,) or (N, K) with N = {mesh.n_nodes}, got "
            f"shape {np.asarray(nodal_values).shape}"
        )

    if location is None:
        location = locate_points(mesh, pts, bary_tol=bary_tol)
    elif location.triangle.shape[0] != pts.shape[0]:
        raise ValueError(
            f"location has {location.triangle.shape[0]} entries for "
            f"{pts.shape[0]} points"
        )

    out = np.full((pts.shape[0], nodal.shape[1]), np.nan)
    inside = location.inside
    if inside.any():
        tri_nodes = mesh.triangles[location.triangle[inside]]
        w = location.bary[inside]
        out[inside] = np.einsum("pj,pjk->pk", w, nodal[tri_nodes])
    return out[:, 0] if scalar else out
