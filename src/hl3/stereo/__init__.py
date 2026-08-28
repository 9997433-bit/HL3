"""HL3-3D stereo: pinhole cameras, triangulation, calibration, correspondence.

Lightweight reference implementation (NumPy only) of the geometry layer
described in ``.agent_workspace/round1/R1-O2-hl3-3d-spec.md``: the projection
and triangulation algebra of :mod:`hl3.stereo.triangulate`, the synthetic
calibration testbed of :mod:`hl3.stereo.calibrate`, and the reference-frame
stereo matcher of :mod:`hl3.stereo.match`. See those module docstrings for the
exact scope: pinhole L0 only, no lens distortion, no image rectification, no
Zhang planar calibration, and no non-parametric distortion field for stereo
microscopy (that layer stays blocked behind the patent-clearance opinion
required by spec section 10.4).
"""

from __future__ import annotations

from .calibrate import (
    Camera,
    StereoRig,
    add_pixel_noise,
    decompose_projection,
    intrinsics,
    look_at_extrinsics,
    make_stereo_rig,
    pose_errors,
    reconstruction_error,
    relative_pose,
    resection_dlt,
    rq3,
    run_synthetic_experiment,
    synth_complex_surface,
    synth_planar_target,
    synth_target_poses,
    umeyama,
    visible_mask,
)
from .match import (
    EpipolarResiduals,
    MatchSeed,
    StereoMatchParams,
    StereoMatchResult,
    epipolar_residuals,
    match_stereo_pair,
    plane_disparity,
    rig_fundamental,
)
from .triangulate import (
    camera_center,
    cheirality_mask,
    epipolar_distance,
    fundamental_from_projections,
    position_sigma,
    project,
    project_with_depth,
    projection_matrix,
    reprojection_residuals,
    reprojection_rmse,
    sampson_correct,
    sampson_distance,
    triangulate_dlt,
    triangulate_midpoint,
    triangulate_multiview_dlt,
    triangulate_nonlinear,
    triangulate_optimal,
    triangulation_covariance,
    triangulation_quality_mask,
)

__all__ = [
    "Camera",
    "EpipolarResiduals",
    "MatchSeed",
    "StereoMatchParams",
    "StereoMatchResult",
    "StereoRig",
    "add_pixel_noise",
    "camera_center",
    "cheirality_mask",
    "decompose_projection",
    "epipolar_distance",
    "epipolar_residuals",
    "fundamental_from_projections",
    "intrinsics",
    "look_at_extrinsics",
    "make_stereo_rig",
    "match_stereo_pair",
    "plane_disparity",
    "pose_errors",
    "position_sigma",
    "project",
    "project_with_depth",
    "projection_matrix",
    "reconstruction_error",
    "relative_pose",
    "reprojection_residuals",
    "reprojection_rmse",
    "resection_dlt",
    "rig_fundamental",
    "rq3",
    "run_synthetic_experiment",
    "sampson_correct",
    "sampson_distance",
    "synth_complex_surface",
    "synth_planar_target",
    "synth_target_poses",
    "triangulate_dlt",
    "triangulate_midpoint",
    "triangulate_multiview_dlt",
    "triangulate_nonlinear",
    "triangulate_optimal",
    "triangulation_covariance",
    "triangulation_quality_mask",
    "umeyama",
    "visible_mask",
]
