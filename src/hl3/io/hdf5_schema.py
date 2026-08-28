"""HL3 HDF5 容器 schema：常量、位域与参考读写器。

本模块是 ``docs/schema-hdf5.md``（规范版本 ``1.0.0-draft.2``）的**机器可读镜像**。
规范散文里出现的每一个组名、属性名、数据集名、枚举取值与 flags 位，在这里都有对应
常量；任何一处改动都必须同步改另一处，`tests/test_hdf5_schema.py` 会做交叉断言。

依赖策略（R1-O3 铁律 L3「格式公开」的落地方式）：

* 常量、位域、路径助手、规范化 JSON 与哈希 **只依赖标准库**，`import hl3.io.hdf5_schema`
  在没有 h5py、甚至没有 numpy 的环境里也必须成功。
* 只有真正碰文件的三个入口（:func:`write_synthetic_hl3`、:func:`read_analysis`、
  :func:`validate_file`）需要 h5py。缺失时它们抛 :class:`Hdf5Unavailable`，调用方
  （及 CI）据此跳过而不是失败 —— 见 :data:`HAS_H5PY` 与 :func:`skip_reason`。

Round 2 的可执行验收点是一个**微型合成位移场**：均匀单轴拉伸叠加刚体平移，位移与应变
都有解析解，因此往返读写可以逐位断言，而不需要任何外部数据集。

    python -m hl3.io.hdf5_schema selftest
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntFlag
from pathlib import Path
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "SCHEMA_MAJOR",
    "SCHEMA_MINOR",
    "WRITER_ID",
    "FieldFlags",
    "INVALID_FLAG_MASK",
    "RESERVED_FLAG_MASK",
    "PLUGIN_FLAG_MASK",
    "valid_mask",
    "has_reserved_flag_bits",
    "vsg_size_px",
    "canonical_json",
    "content_hash",
    "analysis_path",
    "fields_path",
    "grid_path",
    "strain_path",
    "camera_path",
    "sequence_path",
    "SyntheticSpec",
    "AnalysisData",
    "write_synthetic_hl3",
    "read_analysis",
    "validate_file",
    "Hdf5Unavailable",
    "HAS_H5PY",
    "skip_reason",
]

# --------------------------------------------------------------------------------------
# 1. 版本
# --------------------------------------------------------------------------------------

#: 写入 ``/@hl3_schema_version``。冻结条件见 docs/schema-hdf5.md §12.1；在冻结前
#: 一律带 ``-draft.N`` 后缀且不承诺兼容。
SCHEMA_VERSION = "1.0.0-draft.2"
SCHEMA_MAJOR = 1
SCHEMA_MINOR = 0

#: 本参考实现能读的最高主版本号。更高的主版本必须拒绝（规范 §11.2 条 1）。
SUPPORTED_MAJOR = 1

WRITER_ID = f"hl3-io-ref {SCHEMA_VERSION} (python-reference)"

#: 规范的哈希算法。没装 ``blake3`` 时降级到 blake2b-256，并如实写进 ``@hash_algo``。
HASH_ALGO_BLAKE3 = "blake3-256"
HASH_ALGO_FALLBACK = "blake2b-256"

# --------------------------------------------------------------------------------------
# 2. 根属性与顶层组（docs/schema-hdf5.md §3）
# --------------------------------------------------------------------------------------

A_SCHEMA_VERSION = "hl3_schema_version"
A_WRITER = "hl3_writer"
A_UUID = "uuid"
A_CREATED_UTC = "created_utc"
A_MODIFIED_UTC = "modified_utc"
A_HASH_ALGO = "hash_algo"
A_METROLOGY_CERTIFIED = "metrology_certified"
A_GENERATOR_PLATFORM = "generator_platform"
A_LAYOUT_HINT = "layout_hint"

#: 根组必填属性。
ROOT_REQUIRED_ATTRS: tuple[str, ...] = (
    A_SCHEMA_VERSION,
    A_WRITER,
    A_UUID,
    A_CREATED_UTC,
    A_MODIFIED_UTC,
    A_HASH_ALGO,
)

G_PROJECT = "project"
G_CAMERAS = "cameras"
G_CALIBRATIONS = "calibrations"
G_SEQUENCES = "sequences"
G_ANALOG = "analog"
G_AOIS = "aois"
G_ANALYSES = "analyses"
G_DERIVED = "derived"
G_PROVENANCE = "provenance"
G_THUMBNAILS = "thumbnails"

#: 顶层组白名单。除 ``project`` 外均可缺省（空工程合法）。未列出的顶层组不是错误，
#: 但读取器改写文件时必须原样保留（规范 §11.2 条 3）。
TOP_LEVEL_GROUPS: tuple[str, ...] = (
    G_PROJECT,
    G_CAMERAS,
    G_CALIBRATIONS,
    G_SEQUENCES,
    G_ANALOG,
    G_AOIS,
    G_ANALYSES,
    G_DERIVED,
    G_PROVENANCE,
    G_THUMBNAILS,
)

# --------------------------------------------------------------------------------------
# 3. 子组与数据集名（§4–§10）
# --------------------------------------------------------------------------------------

# /project
SG_UNITS = "units"
SG_COORDINATE_SYSTEMS = "coordinate_systems"
UNITS_REQUIRED_ATTRS: tuple[str, ...] = ("length", "time", "angle", "strain_display")
DS_TRANSFORM = "transform"
DS_SCALE = "scale"
DS_COVARIANCE = "covariance"

# /cameras/<cam_id>
CAMERA_REQUIRED_ATTRS: tuple[str, ...] = (
    "label",
    "role",
    "width_px",
    "height_px",
    "pixel_aspect",
    "bit_depth",
    "shutter",
    "rolling_readout_us",
    "coord_system",
)

# /calibrations/<cal_id>
SG_TARGET = "target"
DS_K = "K"
DS_DIST = "dist"
DS_R = "R"
DS_T = "t"
DS_PARAM_NAMES = "param_names"
DS_RESIDUALS = "residuals"

# /sequences/<seq_id>
SG_FRAMES = "frames"
SG_IMAGES = "images"
DS_FRAME_INDEX = "index"
DS_TIMESTAMP_S = "timestamp_s"
DS_TRIGGER_ID = "trigger_id"
DS_ROI_OFFSET = "roi_offset"
DS_IMAGE_DATA = "data"
DS_PATHS = "paths"
DS_HASHES = "hashes"

# /aois/<aoi_id>
SG_POLYGONS = "polygons"
SG_SEEDS = "seeds"
DS_VERTICES = "vertices"
DS_MASK = "mask"
DS_VALID_FRAMES = "valid_frames"

# /analyses/<ana_id>
SG_GRID = "grid"
SG_FIELDS = "fields"
SG_STRAIN = "strain"
SG_UNCERTAINTY = "uncertainty"
SG_DIAGNOSTICS = "diagnostics"
SG_NEIGHBORS = "neighbors"
SG_CELLS = "cells"
DS_CONFIG = "config"
DEFAULT_STRAIN_ID = "default"

ANALYSIS_REQUIRED_ATTRS: tuple[str, ...] = (
    "label",
    "type",
    "created_utc",
    "kernel_version",
    "config_hash",
    "input_hash",
    "sequence",
    "aoi",
    "reference_policy",
)

# grid/
DS_POINT_ID = "point_id"
DS_REF_XY = "ref_xy"
DS_VALID = "valid"
DS_OFFSETS = "offsets"
DS_NODES = "nodes"
DS_TYPES = "types"
DS_IDX = "idx"
GRID_REQUIRED_ATTRS: tuple[str, ...] = ("kind", "window", "shape_function", "n_shape_params")

# fields/
DS_U = "u"
DS_V = "v"
DS_W = "w"
DS_X, DS_Y, DS_Z = "X", "Y", "Z"
DS_X0, DS_Y0, DS_Z0 = "X0", "Y0", "Z0"
DS_DISPARITY = "disparity"
DS_P_SHAPE = "p_shape"
DS_ZNCC = "zncc"
DS_SIGMA = "sigma"
DS_ITERS = "iters"
DS_FLAGS = "flags"

#: ``fields/`` 下必填数据集（2D 与 3D 共有部分）。
FIELDS_REQUIRED: tuple[str, ...] = (DS_U, DS_V, DS_ZNCC, DS_FLAGS)
#: 立体/多目额外必填。
FIELDS_REQUIRED_3D: tuple[str, ...] = (DS_W,)

#: ``fields/u`` 与 ``fields/v`` 的单位属性。未标定的 2D 分析必须写 ``"px"``。
A_SPACE = "space"
SPACE_VALUES: frozenset[str] = frozenset({"px", "m"})

# strain/<strain_id>
DS_EXX, DS_EYY, DS_EXY = "exx", "eyy", "exy"
DS_E1, DS_E2, DS_THETA_P = "e1", "e2", "theta_p"
DS_GAMMA_MAX, DS_VON_MISES = "gamma_max", "von_mises"
STRAIN_REQUIRED_ATTRS: tuple[str, ...] = ("tensor", "method", "window_pts", "vsg_px")
STRAIN_REQUIRED: tuple[str, ...] = (DS_EXX, DS_EYY, DS_EXY)

# uncertainty/
DS_U_STD, DS_V_STD, DS_W_STD = "u_std", "v_std", "w_std"
DS_COV_UVW = "cov_uvw"
SG_STRAIN_STD = "strain_std"
UNCERTAINTY_REQUIRED: tuple[str, ...] = (DS_U_STD, DS_V_STD)

# diagnostics/
DIAGNOSTICS_REQUIRED_ATTRS: tuple[str, ...] = (
    "solve_wall_s",
    "threads",
    "device",
    "rng_seed",
    "deterministic",
)
DS_PER_FRAME_TIME_S = "per_frame_time_s"
DS_CONVERGENCE_HIST = "convergence_hist"

# /provenance
DS_PROVENANCE_LOG = "log"
SG_INPUTS = "inputs"

# --------------------------------------------------------------------------------------
# 4. 枚举取值（未知取值必须报错，不得静默猜测 —— §6.1、§11.2 条 4）
# --------------------------------------------------------------------------------------

ANALYSIS_TYPES: frozenset[str] = frozenset({"2d", "stereo", "multiview"})
STEREO_TYPES: frozenset[str] = frozenset({"stereo", "multiview"})
CAMERA_ROLES: frozenset[str] = frozenset(
    {"primary", "secondary", "auxiliary", "thermal", "reference"}
)
SHUTTER_KINDS: frozenset[str] = frozenset({"global", "rolling"})
COORD_SYSTEM_KINDS: frozenset[str] = frozenset(
    {"image", "sensor", "camera", "rig", "world", "specimen", "plot", "user"}
)
CALIB_METHODS: frozenset[str] = frozenset(
    {"planar_target_zhang", "bundle_adjust", "self_calib", "imported", "scale_only"}
)
DISTORTION_MODELS: frozenset[str] = frozenset(
    {
        "none",
        "brown_conrady_k3p2",
        "brown_conrady_k6p2s4",
        "division_k1",
        "opencv_fisheye",
        "telecentric",
        "stereo_microscope",
        "generic_poly2d",
    }
)
#: 畸变模型 → ``dist`` 数组长度。``None`` 表示长度由 ``@model_params`` / ``@poly_order`` 决定。
DISTORTION_PARAM_COUNT: dict[str, int | None] = {
    "none": 0,
    "brown_conrady_k3p2": 5,
    "brown_conrady_k6p2s4": 12,
    "division_k1": 1,
    "opencv_fisheye": 4,
    "telecentric": 2,
    "stereo_microscope": None,
    "generic_poly2d": None,
}
IMAGE_STORAGE: frozenset[str] = frozenset({"embedded", "external", "none"})
AOI_MODES: frozenset[str] = frozenset(
    {"static", "tracked_rigid", "tracked_deformable", "per_frame"}
)
GRID_KINDS: frozenset[str] = frozenset({"regular", "scattered", "fe_mesh", "marker_set"})
SUBSET_WINDOWS: frozenset[str] = frozenset({"square", "circular", "adaptive"})
SHAPE_FUNCTIONS: frozenset[str] = frozenset({"rigid", "affine", "quadratic"})
#: 二维情形下形函数参数个数（插件形函数自报 ``@n_shape_params``）。
SHAPE_PARAM_COUNT: dict[str, int] = {"rigid": 2, "affine": 6, "quadratic": 12}
STRAIN_TENSORS: frozenset[str] = frozenset(
    {"engineering", "green_lagrange", "euler_almansi", "hencky", "logarithmic"}
)
STRAIN_METHODS: frozenset[str] = frozenset(
    {"local_plane_fit", "savitzky_golay", "fe_gradient", "spline_global"}
)
UQ_METHODS: frozenset[str] = frozenset(
    {"propagated", "bootstrap", "repeat_static", "synthetic_calibrated"}
)
REFERENCE_POLICY_KINDS: frozenset[str] = frozenset({"fixed", "incremental", "multi"})
SYNC_METHODS: frozenset[str] = frozenset(
    {"hardware_trigger", "timestamp_match", "manual_offset", "none"}
)

# --------------------------------------------------------------------------------------
# 5. flags 位域（§9.5，跨版本稳定，不得复用已分配位）
# --------------------------------------------------------------------------------------


class FieldFlags(IntFlag):
    """``fields/flags`` 的位域定义。位号一经分配永不复用。"""

    CONVERGED = 0x00000001
    MASKED = 0x00000002
    SEEDED = 0x00000004
    EXTRAPOLATED = 0x00000008
    EDGE_CLAMPED = 0x00000010
    LOW_CONTRAST = 0x00000020
    EPIPOLAR_REJECT = 0x00000040
    TRIANGULATION_ILL = 0x00000080
    OUTLIER_FILTERED = 0x00000100
    INTERPOLATED_FILL = 0x00000200
    GPU_PATH = 0x00000400
    ROLLING_CORRECTED = 0x00000800


#: bit 0–11 已分配。
ASSIGNED_FLAG_MASK = 0x00000FFF
#: bit 12–23 由规范未来版本分配；当前写入器不得置位。
RESERVED_FLAG_MASK = 0x00FFF000
#: bit 24–31 插件私有，语义写入 ``config``。
PLUGIN_FLAG_MASK = 0xFF000000

#: 只要命中其中任何一位，该点即不可用于统计。
INVALID_FLAG_MASK = (
    FieldFlags.MASKED | FieldFlags.OUTLIER_FILTERED | FieldFlags.INTERPOLATED_FILL
)


def valid_mask(flags: Any) -> Any:
    """规范 §9.5 的有效性判据，供所有读取器统一口径。

    有效 ⇔ 未被掩膜/离群/填补，且已收敛。接受标量或 numpy 数组，返回同形布尔值。
    """
    invalid = int(INVALID_FLAG_MASK)
    converged = int(FieldFlags.CONVERGED)
    return ((flags & invalid) == 0) & ((flags & converged) != 0)


def has_reserved_flag_bits(flags: Any) -> bool:
    """写入器自检：置位了规范保留位 (12–23) 的文件不合规。"""
    import builtins

    if hasattr(flags, "any"):
        return builtins.bool((flags & RESERVED_FLAG_MASK).any())
    return (int(flags) & RESERVED_FLAG_MASK) != 0


def describe_flags(value: int) -> list[str]:
    """把一个 flags 值展开成可读名字列表，未知位记为 ``bit<N>``。"""
    names = [f.name for f in FieldFlags if value & int(f)]
    leftover = value & ~ASSIGNED_FLAG_MASK
    names += [f"bit{i}" for i in range(32) if leftover & (1 << i)]
    return names


# --------------------------------------------------------------------------------------
# 6. 派生量与路径助手
# --------------------------------------------------------------------------------------


def vsg_size_px(window_pts: int, step_px: int, subset_px: int) -> float:
    """等效虚拟应变片尺寸（像素）：``(window_pts - 1) * step_px + subset_px``。

    与 R1-O3 §3.5 的 C++ ``vsg_size_px`` 同一定义。``@vsg_px`` 是必填字段，因为空间
    分辨率与噪声的权衡是 DIC 结果最容易被误读之处。
    """
    if window_pts < 1 or window_pts % 2 == 0:
        raise ValueError(f"window_pts 必须为正奇数，收到 {window_pts}")
    if subset_px < 1 or subset_px % 2 == 0:
        raise ValueError(f"subset_px 必须为正奇数，收到 {subset_px}")
    if step_px < 1:
        raise ValueError(f"step_px 必须为正整数，收到 {step_px}")
    return float((window_pts - 1) * step_px + subset_px)


def shape_param_count(shape_function: str) -> int:
    """内置形函数的参数个数（二维）。插件形函数请直接读 ``@n_shape_params``。"""
    try:
        return SHAPE_PARAM_COUNT[shape_function]
    except KeyError as exc:
        raise ValueError(
            f"未知形函数 {shape_function!r}；插件形函数必须自报 @n_shape_params"
        ) from exc


def camera_path(cam_id: str) -> str:
    return f"/{G_CAMERAS}/{cam_id}"


def sequence_path(seq_id: str) -> str:
    return f"/{G_SEQUENCES}/{seq_id}"


def analysis_path(ana_id: str) -> str:
    return f"/{G_ANALYSES}/{ana_id}"


def grid_path(ana_id: str) -> str:
    return f"{analysis_path(ana_id)}/{SG_GRID}"


def fields_path(ana_id: str) -> str:
    return f"{analysis_path(ana_id)}/{SG_FIELDS}"


def strain_path(ana_id: str, strain_id: str = DEFAULT_STRAIN_ID) -> str:
    return f"{analysis_path(ana_id)}/{SG_STRAIN}/{strain_id}"


def uncertainty_path(ana_id: str) -> str:
    return f"{analysis_path(ana_id)}/{SG_UNCERTAINTY}"


def diagnostics_path(ana_id: str) -> str:
    return f"{analysis_path(ana_id)}/{SG_DIAGNOSTICS}"


# --------------------------------------------------------------------------------------
# 7. 规范化 JSON 与哈希（附录 B、§2.5）
# --------------------------------------------------------------------------------------


def _canon_float(x: float) -> str:
    if math.isnan(x) or math.isinf(x):
        raise ValueError("规范化 JSON 不允许 NaN/Inf；请改用字符串哨兵或省略该键")
    return "%.17g" % x


def canonical_json(obj: Any) -> str:
    """按 docs/schema-hdf5.md 附录 B 规范化。

    键按 Unicode 码点升序、无多余空白、浮点 ``%.17g``、UTF-8 不转义非 ASCII、
    省略值为 ``None`` 的键、数组顺序保持不变。``@config_hash`` 的可复现性依赖这些规则，
    所以这里手写序列化而不是走 ``json.dumps``（后者无法定制浮点格式）。
    """
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return _canon_float(obj)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(canonical_json(v) for v in obj) + "]"
    if isinstance(obj, dict):
        items = sorted(((str(k), v) for k, v in obj.items() if v is not None), key=lambda kv: kv[0])
        body = ",".join(f"{json.dumps(k, ensure_ascii=False)}:{canonical_json(v)}" for k, v in items)
        return "{" + body + "}"
    raise TypeError(f"不可规范化的类型：{type(obj).__name__}")


def content_hash(data: bytes | str) -> tuple[str, str]:
    """返回 ``(hexdigest, algo)``。

    规范算法是 BLAKE3-256。标准库没有 BLAKE3，因此装了 ``blake3`` 就用它，否则降级到
    blake2b-256 —— 降级必须如实写进根属性 ``@hash_algo``，不能假装是 BLAKE3。
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    try:
        import blake3  # type: ignore[import-not-found]

        return blake3.blake3(data).hexdigest(), HASH_ALGO_BLAKE3
    except ImportError:
        return hashlib.blake2b(data, digest_size=32).hexdigest(), HASH_ALGO_FALLBACK


def config_hash(config: dict[str, Any]) -> tuple[str, str]:
    """``@config_hash``：规范化 config JSON 的哈希。"""
    return content_hash(canonical_json(config))


def utc_now() -> str:
    """ISO 8601 UTC 字符串，微秒精度，带 ``Z`` 后缀（§2.4）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


# --------------------------------------------------------------------------------------
# 8. 默认分块（附录 A）
# --------------------------------------------------------------------------------------


def default_chunks(shape: tuple[int, ...], kind: str = "field") -> tuple[int, ...] | None:
    """附录 A 的默认分块，按实际形状收缩。形状含 0 时返回 ``None``（不分块）。"""
    if any(d <= 0 for d in shape):
        return None
    caps: dict[str, tuple[int, ...]] = {
        "field": (16, 4096),
        "p_shape": (8, 2048, 1 << 30),
        "cov_uvw": (8, 2048, 1 << 30),
        "image": (1, 1 << 30, 1 << 30),
        "analog": (65536,),
        "log": (1024,),
    }
    cap = caps.get(kind)
    if cap is None or len(cap) != len(shape):
        return tuple(shape)
    return tuple(min(d, c) for d, c in zip(shape, cap))


# --------------------------------------------------------------------------------------
# 9. h5py 可用性
# --------------------------------------------------------------------------------------


class Hdf5Unavailable(ImportError):
    """h5py 未安装时由文件级入口抛出。"""


try:  # pragma: no cover - 取决于环境
    import h5py as _h5py

    HAS_H5PY = True
except ImportError:  # pragma: no cover
    _h5py = None  # type: ignore[assignment]
    HAS_H5PY = False

_SKIP_MSG = (
    "hl3.io.hdf5_schema 的读写入口需要 h5py（`pip install 'hl3[hdf5]'` 或 `pip install h5py`）。"
    "常量、位域与路径助手不需要 h5py，可正常导入。"
)


def skip_reason() -> str | None:
    """给 pytest ``skipif`` 用：可用时返回 ``None``，否则返回人话原因。"""
    return None if HAS_H5PY else _SKIP_MSG


def _require_h5py():
    if not HAS_H5PY:
        raise Hdf5Unavailable(_SKIP_MSG)
    return _h5py


def _compression_kwargs() -> tuple[dict[str, Any], str]:
    """附录 A 默认是 zstd-3+shuffle，但 zstd 是 HDF5 插件过滤器。

    没有 ``hdf5plugin`` 时退回 HDF5 内置的 gzip，并把实际使用的编码如实写进
    ``@compression`` —— 读取器靠这个属性而不是靠猜。
    """
    try:  # pragma: no cover - 取决于环境
        import hdf5plugin  # type: ignore[import-not-found]

        return dict(hdf5plugin.Zstd(clevel=3)), "zstd:3"
    except ImportError:
        return {"compression": "gzip", "compression_opts": 4, "shuffle": True}, "gzip:4+shuffle"


def _write_dataset(group, name: str, data, *, kind: str = "field", **attrs):
    kwargs, label = _compression_kwargs()
    chunks = default_chunks(tuple(data.shape), kind)
    # 极小数据集压缩得不偿失，也无法分块（HDF5 要求 chunk 维度 > 0）。
    if chunks is None or data.size < 64:
        dset = group.create_dataset(name, data=data)
    else:
        dset = group.create_dataset(name, data=data, chunks=chunks, **kwargs)
        dset.attrs["chunk"] = list(chunks)
        dset.attrs["compression"] = label
    for key, value in attrs.items():
        dset.attrs[key] = value
    return dset


# --------------------------------------------------------------------------------------
# 10. 合成位移场
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SyntheticSpec:
    """微型合成算例：均匀单轴拉伸 + 刚体平移，位移与应变均有解析解。

    位移场（参考帧为第 0 帧，`f` 为帧序号）::

        u(x, y, f) = tx * f + exx_per_frame * f * (x - x0)
        v(x, y, f) = ty * f - poisson * exx_per_frame * f * (y - y0)

    于是 ``exx = exx_per_frame * f``、``eyy = -poisson * exx_per_frame * f``、``exy = 0``
    逐点精确成立。往返测试可以直接断言解析值，不需要任何外部数据。
    """

    n_frames: int = 3
    grid_nx: int = 5
    grid_ny: int = 4
    subset_px: int = 29
    step_px: int = 7
    origin_px: tuple[float, float] = (40.0, 30.0)
    translation_px_per_frame: tuple[float, float] = (0.25, -0.10)
    exx_per_frame: float = 1.0e-3
    poisson: float = 0.30
    window_pts: int = 5
    sigma_u_px: float = 0.01
    image_size_px: tuple[int, int] = (128, 128)

    @property
    def n_points(self) -> int:
        return self.grid_nx * self.grid_ny

    @property
    def vsg_px(self) -> float:
        return vsg_size_px(self.window_pts, self.step_px, self.subset_px)

    def to_config(self) -> dict[str, Any]:
        """写进 ``/analyses/<id>/config`` 的求解配置（规范化后参与 ``@config_hash``）。"""
        return {
            "correlator": "hl3.synthetic",
            "criterion": "znssd",
            "interp": "bspline5",
            "shape_function": "affine",
            "subset_px": self.subset_px,
            "step_px": self.step_px,
            "conv_tol": 1.0e-5,
            "max_iters": 50,
            "deterministic": True,
            "synthetic": {
                "exx_per_frame": self.exx_per_frame,
                "poisson": self.poisson,
                "translation_px_per_frame": list(self.translation_px_per_frame),
            },
        }


def synthetic_fields(spec: SyntheticSpec) -> dict[str, Any]:
    """按 :class:`SyntheticSpec` 生成参考网格、位移场与应变场（纯 numpy，无随机数）。"""
    import numpy as np

    x0, y0 = spec.origin_px
    xs = x0 + spec.step_px * np.arange(spec.grid_nx, dtype=np.float64)
    ys = y0 + spec.step_px * np.arange(spec.grid_ny, dtype=np.float64)
    gx, gy = np.meshgrid(xs, ys, indexing="xy")
    ref_xy = np.stack([gx.ravel(), gy.ravel()], axis=1)  # (P, 2) 行主序，y 外 x 内

    f = np.arange(spec.n_frames, dtype=np.float64)[:, None]  # (F, 1)
    tx, ty = spec.translation_px_per_frame
    dx = ref_xy[None, :, 0] - x0
    dy = ref_xy[None, :, 1] - y0

    u = tx * f + spec.exx_per_frame * f * dx
    v = ty * f - spec.poisson * spec.exx_per_frame * f * dy

    exx = np.broadcast_to(spec.exx_per_frame * f, u.shape).copy()
    eyy = np.broadcast_to(-spec.poisson * spec.exx_per_frame * f, u.shape).copy()
    exy = np.zeros_like(exx)

    flags = np.full(u.shape, int(FieldFlags.CONVERGED), dtype=np.uint32)
    # 第 0 帧、第 0 点作为种子点，用来验证位域确实被读回来。
    flags[:, 0] |= int(FieldFlags.SEEDED)

    return {
        "ref_xy": ref_xy,
        "point_id": np.arange(spec.n_points, dtype=np.uint64),
        "u": u.astype(np.float32),
        "v": v.astype(np.float32),
        "zncc": np.full(u.shape, 0.999, dtype=np.float32),
        "sigma": np.full(u.shape, 0.02, dtype=np.float32),
        "iters": np.full(u.shape, 4, dtype=np.uint16),
        "flags": flags,
        "exx": exx.astype(np.float32),
        "eyy": eyy.astype(np.float32),
        "exy": exy.astype(np.float32),
        "u_std": np.full(u.shape, spec.sigma_u_px, dtype=np.float32),
        "v_std": np.full(u.shape, spec.sigma_u_px, dtype=np.float32),
    }


def _regular_grid_neighbors(nx: int, ny: int):
    """4-邻接 CSR。用 CSR 而不是定长 k 邻居，是为了让边界点自然地少邻居。"""
    import numpy as np

    offsets = [0]
    idx: list[int] = []
    for j in range(ny):
        for i in range(nx):
            for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ii, jj = i + di, j + dj
                if 0 <= ii < nx and 0 <= jj < ny:
                    idx.append(jj * nx + ii)
            offsets.append(len(idx))
    return np.asarray(offsets, dtype=np.int64), np.asarray(idx, dtype=np.int32)


# --------------------------------------------------------------------------------------
# 11. 参考写入器
# --------------------------------------------------------------------------------------


def write_synthetic_hl3(
    path: str | Path,
    spec: SyntheticSpec | None = None,
    *,
    analysis_id: str = "ana_01",
    camera_id: str = "cam0",
    sequence_id: str = "seq0",
    aoi_id: str = "aoi0",
    project_name: str = "hl3 synthetic conformance sample",
) -> Path:
    """写一个体积最小但结构合规的 ``.hl3``，内含合成位移场与解析应变场。

    这是 `spec/conformance/` 里「2D 完整（单相机 + 未标定 px 单位 + 应变 + UQ）」用例的
    生成器。位移单位写 ``"px"`` 而不是假借 1 px = 1 mm —— 未标定就是未标定。

    需要 h5py；缺失时抛 :class:`Hdf5Unavailable`。
    """
    h5py = _require_h5py()
    import numpy as np

    spec = spec or SyntheticSpec()
    path = Path(path)
    data = synthetic_fields(spec)
    now = utc_now()
    cfg = spec.to_config()
    cfg_hash, algo = config_hash(cfg)
    in_hash, _ = content_hash(
        canonical_json(
            {
                "sequence": sequence_id,
                "aoi": aoi_id,
                "calibration": None,
                "images": "synthetic:none",
                "n_frames": spec.n_frames,
            }
        )
    )
    vlen_str = h5py.string_dtype(encoding="utf-8")
    n_frames, n_points = spec.n_frames, spec.n_points
    width, height = spec.image_size_px

    with h5py.File(path, "w") as f:
        # ---- 根属性 (§3) ----------------------------------------------------------
        f.attrs[A_SCHEMA_VERSION] = SCHEMA_VERSION
        f.attrs[A_WRITER] = WRITER_ID
        f.attrs[A_UUID] = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"hl3-synthetic/{cfg_hash}"))
        f.attrs[A_CREATED_UTC] = now
        f.attrs[A_MODIFIED_UTC] = now
        f.attrs[A_HASH_ALGO] = algo
        f.attrs[A_GENERATOR_PLATFORM] = "python-reference"
        f.attrs[A_LAYOUT_HINT] = "frame_major"

        # ---- /project (§4) --------------------------------------------------------
        proj = f.create_group(G_PROJECT)
        proj.attrs["name"] = project_name
        proj.attrs["description"] = "R2-O3 合成算例：单轴拉伸 + 刚体平移，位移与应变均有解析解"
        units = proj.create_group(SG_UNITS)
        units.attrs["length"] = "mm"
        units.attrs["time"] = "s"
        units.attrs["angle"] = "deg"
        units.attrs["strain_display"] = "microstrain"

        cs_root = proj.create_group(SG_COORDINATE_SYSTEMS)
        world = cs_root.create_group("world")
        world.attrs["kind"] = "world"
        world.attrs["parent"] = ""
        world.create_dataset(DS_TRANSFORM, data=np.eye(4, dtype=np.float64))
        img_cs = cs_root.create_group(f"image_{camera_id}")
        img_cs.attrs["kind"] = "image"
        img_cs.attrs["parent"] = "world"
        img_cs.attrs["camera"] = camera_id
        img_cs.attrs["pixel_origin"] = "center"
        img_cs.create_dataset(DS_TRANSFORM, data=np.eye(4, dtype=np.float64))

        # ---- /cameras (§5) --------------------------------------------------------
        cam = f.create_group(G_CAMERAS).create_group(camera_id)
        cam.attrs["label"] = "synthetic camera"
        cam.attrs["role"] = "primary"
        cam.attrs["width_px"] = np.int32(width)
        cam.attrs["height_px"] = np.int32(height)
        cam.attrs["pixel_pitch_um"] = 0.0  # 0 = 未知
        cam.attrs["pixel_aspect"] = 1.0
        cam.attrs["bit_depth"] = np.int32(8)
        cam.attrs["shutter"] = "global"
        cam.attrs["rolling_readout_us"] = 0.0
        cam.attrs["coord_system"] = f"image_{camera_id}"

        # ---- /sequences (§7) ------------------------------------------------------
        seq = f.create_group(G_SEQUENCES).create_group(sequence_id)
        seq.attrs["label"] = "synthetic sequence"
        seq.attrs["frame_count"] = np.int64(n_frames)
        seq.attrs["fps_nominal"] = 1.0
        seq.attrs["epoch_utc"] = now
        frames = seq.create_group(SG_FRAMES)
        frames.create_dataset(DS_FRAME_INDEX, data=np.arange(n_frames, dtype=np.int64))
        frames.create_dataset(DS_TIMESTAMP_S, data=np.arange(n_frames, dtype=np.float64))
        imgs = seq.create_group(SG_IMAGES).create_group(camera_id)
        # @storage="none"：只留结果、丢弃图像。分析结果仍完全可读，但不可重算。
        imgs.attrs["storage"] = "none"
        imgs.attrs["format"] = "tiff"

        # ---- /aois (§8.2) ---------------------------------------------------------
        aoi = f.create_group(G_AOIS).create_group(aoi_id)
        aoi.attrs["label"] = "full field"
        aoi.attrs["sequence"] = sequence_id
        aoi.attrs["reference_camera"] = camera_id
        aoi.attrs["mode"] = "static"
        x0, y0 = spec.origin_px
        x1 = x0 + spec.step_px * (spec.grid_nx - 1)
        y1 = y0 + spec.step_px * (spec.grid_ny - 1)
        poly = aoi.create_group(SG_POLYGONS).create_group("0")
        poly.attrs["role"] = "outer"
        poly.create_dataset(
            DS_VERTICES,
            data=np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64),
        )
        seeds = aoi.create_group(SG_SEEDS)
        seeds.create_dataset("xy", data=data["ref_xy"][:1].copy())
        seeds.create_dataset("auto", data=np.zeros(1, dtype=np.uint8))

        # ---- /analyses (§9) -------------------------------------------------------
        ana = f.create_group(G_ANALYSES).create_group(analysis_id)
        ana.attrs["label"] = "synthetic 2d"
        ana.attrs["type"] = "2d"
        ana.attrs["created_utc"] = now
        ana.attrs["kernel_version"] = WRITER_ID
        ana.attrs["config_hash"] = cfg_hash
        ana.attrs["input_hash"] = in_hash
        ana.attrs["sequence"] = sequence_id
        ana.attrs["aoi"] = aoi_id
        ana.attrs["reference_policy"] = canonical_json({"kind": "fixed", "frame": 0})
        ana.create_dataset(DS_CONFIG, data=canonical_json(cfg), dtype=vlen_str)

        grid = ana.create_group(SG_GRID)
        grid.attrs["kind"] = "regular"
        grid.attrs["subset_px"] = np.int32(spec.subset_px)
        grid.attrs["step_px"] = np.int32(spec.step_px)
        grid.attrs["window"] = "square"
        grid.attrs["shape_function"] = "affine"
        grid.attrs["n_shape_params"] = np.int32(shape_param_count("affine"))
        grid.create_dataset(DS_POINT_ID, data=data["point_id"])
        grid.create_dataset(DS_REF_XY, data=data["ref_xy"])
        grid.create_dataset(DS_VALID, data=np.ones(n_points, dtype=np.uint8))
        nb_off, nb_idx = _regular_grid_neighbors(spec.grid_nx, spec.grid_ny)
        nb = grid.create_group(SG_NEIGHBORS)
        nb.create_dataset(DS_OFFSETS, data=nb_off)
        nb.create_dataset(DS_IDX, data=nb_idx)

        ana.create_group(SG_FRAMES).create_dataset(
            DS_FRAME_INDEX, data=np.arange(n_frames, dtype=np.int64)
        )

        fields = ana.create_group(SG_FIELDS)
        _write_dataset(fields, DS_U, data["u"], space="px")
        _write_dataset(fields, DS_V, data["v"], space="px")
        _write_dataset(fields, DS_ZNCC, data["zncc"])
        _write_dataset(fields, DS_SIGMA, data["sigma"])
        _write_dataset(fields, DS_ITERS, data["iters"])
        _write_dataset(fields, DS_FLAGS, data["flags"])

        strain = ana.create_group(SG_STRAIN).create_group(DEFAULT_STRAIN_ID)
        strain.attrs["tensor"] = "engineering"
        strain.attrs["method"] = "local_plane_fit"
        strain.attrs["window_pts"] = np.int32(spec.window_pts)
        strain.attrs["vsg_px"] = spec.vsg_px
        for name in (DS_EXX, DS_EYY, DS_EXY):
            _write_dataset(strain, name, data[name])

        unc = ana.create_group(SG_UNCERTAINTY)
        unc.attrs["method"] = "synthetic_calibrated"
        unc.attrs["sigma_u_px_floor"] = spec.sigma_u_px
        unc.attrs["sigma_v_px_floor"] = spec.sigma_u_px
        unc.attrs["image_noise_sigma_dn"] = 0.0
        _write_dataset(unc, DS_U_STD, data["u_std"])
        _write_dataset(unc, DS_V_STD, data["v_std"])

        diag = ana.create_group(SG_DIAGNOSTICS)
        diag.attrs["solve_wall_s"] = 0.0
        diag.attrs["threads"] = np.int32(1)
        diag.attrs["device"] = "cpu"
        diag.attrs["rng_seed"] = np.uint64(0x484C33)
        diag.attrs["deterministic"] = np.uint8(1)

        # ---- /provenance (§10) ----------------------------------------------------
        prov = f.create_group(G_PROVENANCE)
        entries = [
            canonical_json(
                {
                    "ts": now,
                    "actor": "python",
                    "event": "project.create",
                    "detail": {"writer": WRITER_ID, "hash_algo": algo},
                }
            ),
            canonical_json(
                {
                    "ts": now,
                    "actor": "python",
                    "event": "analysis.write_synthetic",
                    "detail": {"analysis": analysis_id, "config_hash": cfg_hash},
                }
            ),
        ]
        prov.create_dataset(
            DS_PROVENANCE_LOG, data=np.array(entries, dtype=object), dtype=vlen_str, maxshape=(None,)
        )

    return path


# --------------------------------------------------------------------------------------
# 12. 参考读取器
# --------------------------------------------------------------------------------------


@dataclass
class AnalysisData:
    """:func:`read_analysis` 的返回值。字段名与 schema 路径一一对应。"""

    analysis_id: str
    schema_version: str
    writer: str
    hash_algo: str
    analysis_type: str
    space: str
    config: dict[str, Any]
    config_hash: str
    ref_xy: Any
    point_id: Any
    frame_index: Any
    u: Any
    v: Any
    zncc: Any
    flags: Any
    w: Any | None = None
    sigma: Any | None = None
    iters: Any | None = None
    strain: dict[str, Any] = field(default_factory=dict)
    strain_attrs: dict[str, Any] = field(default_factory=dict)
    uncertainty: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> Any:
        """按 §9.5 判据得到的 ``(F, P)`` 布尔掩膜。"""
        return valid_mask(self.flags)

    @property
    def vsg_px(self) -> float | None:
        value = self.strain_attrs.get("vsg_px")
        return None if value is None else float(value)


def _attrs_to_dict(obj) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in obj.attrs.items():
        out[key] = value.item() if hasattr(value, "item") and getattr(value, "ndim", 1) == 0 else value
    return out


def read_analysis(
    path: str | Path,
    analysis_id: str | None = None,
    *,
    strain_id: str = DEFAULT_STRAIN_ID,
) -> AnalysisData:
    """纯 h5py 参考读取器：不依赖 HL3 其余任何代码即可取出全部关键结果。

    ``analysis_id`` 为 ``None`` 时取 ``/analyses`` 下第一个（按名字排序）。
    """
    h5py = _require_h5py()

    with h5py.File(Path(path), "r") as f:
        version = str(f.attrs[A_SCHEMA_VERSION])
        major = int(version.split(".", 1)[0])
        if major > SUPPORTED_MAJOR:
            raise ValueError(
                f"文件 schema 主版本 {major} 高于本读取器支持的 {SUPPORTED_MAJOR}；拒绝读取"
            )
        if G_ANALYSES not in f:
            raise KeyError("文件不含 /analyses 组")
        if analysis_id is None:
            analysis_id = sorted(f[G_ANALYSES].keys())[0]
        ana = f[f"{G_ANALYSES}/{analysis_id}"]

        ana_type = str(ana.attrs["type"])
        if ana_type not in ANALYSIS_TYPES:
            raise ValueError(f"未知分析类型 {ana_type!r}")

        fields = ana[SG_FIELDS]
        space = str(fields[DS_U].attrs.get(A_SPACE, "px"))
        if space not in SPACE_VALUES:
            raise ValueError(f"未知位移单位 @space={space!r}（只允许 'px' 或 'm'）")

        strain_data: dict[str, Any] = {}
        strain_attrs: dict[str, Any] = {}
        strain_grp_path = f"{SG_STRAIN}/{strain_id}"
        if strain_grp_path in ana:
            grp = ana[strain_grp_path]
            tensor = str(grp.attrs["tensor"])
            if tensor not in STRAIN_TENSORS:
                raise ValueError(f"未知应变张量 {tensor!r}")
            strain_attrs = _attrs_to_dict(grp)
            strain_data = {k: grp[k][()] for k in grp if isinstance(grp[k], h5py.Dataset)}

        uncertainty: dict[str, Any] = {}
        if SG_UNCERTAINTY in ana:
            grp = ana[SG_UNCERTAINTY]
            method = str(grp.attrs["method"])
            if method not in UQ_METHODS:
                raise ValueError(f"未知不确定度方法 {method!r}")
            uncertainty = {k: grp[k][()] for k in grp if isinstance(grp[k], h5py.Dataset)}
            uncertainty.update(_attrs_to_dict(grp))

        diagnostics = _attrs_to_dict(ana[SG_DIAGNOSTICS]) if SG_DIAGNOSTICS in ana else {}

        return AnalysisData(
            analysis_id=analysis_id,
            schema_version=version,
            writer=str(f.attrs[A_WRITER]),
            hash_algo=str(f.attrs[A_HASH_ALGO]),
            analysis_type=ana_type,
            space=space,
            config=json.loads(ana[DS_CONFIG][()]),
            config_hash=str(ana.attrs["config_hash"]),
            ref_xy=ana[f"{SG_GRID}/{DS_REF_XY}"][()],
            point_id=ana[f"{SG_GRID}/{DS_POINT_ID}"][()],
            frame_index=ana[f"{SG_FRAMES}/{DS_FRAME_INDEX}"][()],
            u=fields[DS_U][()],
            v=fields[DS_V][()],
            w=fields[DS_W][()] if DS_W in fields else None,
            zncc=fields[DS_ZNCC][()],
            sigma=fields[DS_SIGMA][()] if DS_SIGMA in fields else None,
            iters=fields[DS_ITERS][()] if DS_ITERS in fields else None,
            flags=fields[DS_FLAGS][()],
            strain=strain_data,
            strain_attrs=strain_attrs,
            uncertainty=uncertainty,
            diagnostics=diagnostics,
        )


# --------------------------------------------------------------------------------------
# 13. 结构验证器（`hl3 validate` 的最小前身）
# --------------------------------------------------------------------------------------


def validate_file(path: str | Path, *, strict: bool = False) -> list[str]:
    """检查结构、必填字段与交叉引用完整性，返回违规描述列表（空 = 合规）。

    ``strict=True`` 追加 SHOULD 级检查。这是规范 §12 里 ``hl3 validate`` 的最小前身；
    完整版还要做哈希校验与单位可解析性。
    """
    h5py = _require_h5py()
    problems: list[str] = []

    def need_attrs(obj, names, where: str) -> None:
        for name in names:
            if name not in obj.attrs:
                problems.append(f"{where}: 缺必填属性 @{name}")

    with h5py.File(Path(path), "r") as f:
        need_attrs(f, ROOT_REQUIRED_ATTRS, "/")
        version = str(f.attrs.get(A_SCHEMA_VERSION, ""))
        if version:
            try:
                major = int(version.split(".", 1)[0])
            except ValueError:
                problems.append(f"/: @{A_SCHEMA_VERSION}={version!r} 不是语义化版本")
            else:
                if major > SUPPORTED_MAJOR:
                    problems.append(f"/: 主版本 {major} 高于本读取器支持的 {SUPPORTED_MAJOR}")
        algo = str(f.attrs.get(A_HASH_ALGO, ""))
        if algo and algo not in (HASH_ALGO_BLAKE3, HASH_ALGO_FALLBACK):
            problems.append(f"/: 未知 @{A_HASH_ALGO}={algo!r}")

        if G_PROJECT not in f:
            problems.append("/: 缺必需组 /project")
        else:
            need_attrs(f[G_PROJECT], ("name",), "/project")
            if SG_UNITS not in f[G_PROJECT]:
                problems.append("/project: 缺 units 组")
            else:
                need_attrs(f[f"{G_PROJECT}/{SG_UNITS}"], UNITS_REQUIRED_ATTRS, "/project/units")

        for cam_id, cam in f.get(G_CAMERAS, {}).items():
            need_attrs(cam, CAMERA_REQUIRED_ATTRS, camera_path(cam_id))
            role = str(cam.attrs.get("role", ""))
            if role and role not in CAMERA_ROLES:
                problems.append(f"{camera_path(cam_id)}: 未知 @role={role!r}")
            shutter = str(cam.attrs.get("shutter", ""))
            if shutter and shutter not in SHUTTER_KINDS:
                problems.append(f"{camera_path(cam_id)}: 未知 @shutter={shutter!r}")

        for cal_id, cal in f.get(G_CALIBRATIONS, {}).items():
            where = f"/{G_CALIBRATIONS}/{cal_id}"
            for cam_id, cam_cal in cal.get("cameras", {}).items():
                model = str(cam_cal[DS_DIST].attrs.get("model", "")) if DS_DIST in cam_cal else ""
                if model not in DISTORTION_MODELS:
                    problems.append(f"{where}/cameras/{cam_id}: 未知或缺失畸变模型 @model={model!r}")
                else:
                    expected = DISTORTION_PARAM_COUNT[model]
                    got = int(cam_cal[DS_DIST].shape[0]) if cam_cal[DS_DIST].shape else 0
                    if expected is not None and got != expected:
                        problems.append(
                            f"{where}/cameras/{cam_id}: @model={model} 要求 dist 长度 {expected}，实际 {got}"
                        )
            if strict and DS_COVARIANCE not in cal:
                problems.append(f"{where}: 无标定协方差，不能用于 uncertainty/@method='propagated'")

        for ana_id, ana in f.get(G_ANALYSES, {}).items():
            where = analysis_path(ana_id)
            need_attrs(ana, ANALYSIS_REQUIRED_ATTRS, where)
            ana_type = str(ana.attrs.get("type", ""))
            if ana_type and ana_type not in ANALYSIS_TYPES:
                problems.append(f"{where}: 未知 @type={ana_type!r}")
            if DS_CONFIG not in ana:
                problems.append(f"{where}: 缺 config 数据集")
            for ref_attr, group in (("sequence", G_SEQUENCES), ("aoi", G_AOIS)):
                ref = ana.attrs.get(ref_attr)
                if ref is not None and f"{group}/{ref}" not in f:
                    problems.append(f"{where}: @{ref_attr}={ref!r} 指向不存在的 /{group}/{ref}")
            cal_ref = ana.attrs.get("calibration")
            if cal_ref is None and ana_type in STEREO_TYPES:
                problems.append(f"{where}: @type={ana_type} 必须给出 @calibration")
            if cal_ref is not None and f"{G_CALIBRATIONS}/{cal_ref}" not in f:
                problems.append(f"{where}: @calibration={cal_ref!r} 指向不存在的标定")

            if SG_GRID not in ana:
                problems.append(f"{where}: 缺 grid 组")
            else:
                grid = ana[SG_GRID]
                need_attrs(grid, GRID_REQUIRED_ATTRS, f"{where}/grid")
                kind = str(grid.attrs.get("kind", ""))
                if kind and kind not in GRID_KINDS:
                    problems.append(f"{where}/grid: 未知 @kind={kind!r}")
                if kind == "regular" and "step_px" not in grid.attrs:
                    problems.append(f"{where}/grid: @kind='regular' 必须给 @step_px")
                for name in (DS_POINT_ID, DS_REF_XY, DS_VALID):
                    if name not in grid:
                        problems.append(f"{where}/grid: 缺数据集 {name}")
                if DS_REF_XY in grid:
                    shape = grid[DS_REF_XY].shape
                    if len(shape) != 2 or shape[1] not in (2, 3):
                        problems.append(f"{where}/grid/ref_xy: 形状必须为 (P,2) 或 (P,3)，实际 {shape}")

            if SG_FIELDS not in ana:
                problems.append(f"{where}: 缺 fields 组")
                continue
            fields = ana[SG_FIELDS]
            required = FIELDS_REQUIRED + (FIELDS_REQUIRED_3D if ana_type in STEREO_TYPES else ())
            for name in required:
                if name not in fields:
                    problems.append(f"{where}/fields: 缺必填数据集 {name}")
            if DS_U in fields and DS_V in fields and fields[DS_U].shape != fields[DS_V].shape:
                problems.append(
                    f"{where}/fields: u{fields[DS_U].shape} 与 v{fields[DS_V].shape} 形状不一致"
                )
            if DS_U in fields:
                space = str(fields[DS_U].attrs.get(A_SPACE, ""))
                if space not in SPACE_VALUES:
                    problems.append(f"{where}/fields/u: @space 必须为 'px' 或 'm'，实际 {space!r}")
            if DS_FLAGS in fields:
                flags = fields[DS_FLAGS][()]
                if has_reserved_flag_bits(flags):
                    problems.append(f"{where}/fields/flags: 置位了规范保留位 (bit 12–23)")
            if DS_U in fields and SG_FRAMES in ana and DS_FRAME_INDEX in ana[SG_FRAMES]:
                n_solved = int(ana[f"{SG_FRAMES}/{DS_FRAME_INDEX}"].shape[0])
                if n_solved != int(fields[DS_U].shape[0]):
                    problems.append(
                        f"{where}: frames/index 长度 {n_solved} 与 fields/u 帧数 "
                        f"{fields[DS_U].shape[0]} 不一致"
                    )

            for strain_id, grp in ana.get(SG_STRAIN, {}).items():
                s_where = f"{where}/strain/{strain_id}"
                need_attrs(grp, STRAIN_REQUIRED_ATTRS, s_where)
                tensor = str(grp.attrs.get("tensor", ""))
                if tensor and tensor not in STRAIN_TENSORS:
                    problems.append(f"{s_where}: 未知 @tensor={tensor!r}")
                method = str(grp.attrs.get("method", ""))
                if method and method not in STRAIN_METHODS:
                    problems.append(f"{s_where}: 未知 @method={method!r}")
                for name in STRAIN_REQUIRED:
                    if name not in grp:
                        problems.append(f"{s_where}: 缺必填数据集 {name}")

            if SG_UNCERTAINTY in ana:
                grp = ana[SG_UNCERTAINTY]
                u_where = f"{where}/uncertainty"
                method = str(grp.attrs.get("method", ""))
                if method not in UQ_METHODS:
                    problems.append(f"{u_where}: 未知或缺失 @method={method!r}")
                for name in UNCERTAINTY_REQUIRED:
                    if name not in grp:
                        problems.append(f"{u_where}: 缺必填数据集 {name}")
                if ana_type in STEREO_TYPES and DS_W_STD not in grp:
                    problems.append(f"{u_where}: 立体分析必须给出 w_std")
                if method == "bootstrap" and "bootstrap_draws" not in grp.attrs:
                    problems.append(f"{u_where}: @method='bootstrap' 必须给 @bootstrap_draws")

            if SG_DIAGNOSTICS not in ana:
                problems.append(f"{where}: 缺 diagnostics 组")
            else:
                need_attrs(ana[SG_DIAGNOSTICS], DIAGNOSTICS_REQUIRED_ATTRS, f"{where}/diagnostics")

            if strict and "git_sha" not in ana.attrs:
                problems.append(f"{where}: 应当写 @git_sha")

        if strict and A_GENERATOR_PLATFORM not in f.attrs:
            problems.append(f"/: 应当写 @{A_GENERATOR_PLATFORM}")
        if strict and G_PROVENANCE not in f:
            problems.append("/: 应当写 /provenance")

    return problems


# --------------------------------------------------------------------------------------
# 14. 自检
# --------------------------------------------------------------------------------------


def _selftest() -> int:
    """写→验→读→比对解析解。h5py 缺失时打印跳过原因并返回 0。"""
    reason = skip_reason()
    if reason is not None:
        print(f"SKIP: {reason}")
        return 0

    import tempfile

    import numpy as np

    spec = SyntheticSpec()
    with tempfile.TemporaryDirectory() as tmp:
        path = write_synthetic_hl3(Path(tmp) / "synthetic.hl3", spec)
        problems = validate_file(path, strict=False)
        if problems:
            print("FAIL: 验证不通过")
            for p in problems:
                print("  -", p)
            return 1

        data = read_analysis(path)
        expected = synthetic_fields(spec)
        assert np.array_equal(data.u, expected["u"]), "u 往返不一致"
        assert np.array_equal(data.v, expected["v"]), "v 往返不一致"
        assert np.array_equal(data.strain[DS_EXX], expected["exx"]), "exx 往返不一致"
        assert data.space == "px", "未标定 2D 必须写 px"
        assert data.valid.all(), "合成算例应全部有效"
        assert data.vsg_px == spec.vsg_px

        size_kb = path.stat().st_size / 1024.0
        print(f"OK  schema={data.schema_version}  hash_algo={data.hash_algo}")
        print(f"OK  往返一致：u/v/exx  形状={data.u.shape}  vsg={data.vsg_px} px  空间单位={data.space}")
        print(f"OK  strict 违规数={len(validate_file(path, strict=True))}  文件体积={size_kb:.1f} KiB")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        raise SystemExit(_selftest())
    print(__doc__)
