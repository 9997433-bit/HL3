# SPDX-License-Identifier: Apache-2.0
"""hl3.io.hdf5_schema 的一致性测试。

分两层：

1. **无依赖层** —— 常量、位域、规范化 JSON、VSG 公式。这些必须在没有 h5py 的机器上
   也能跑，因为「格式公开」的前提是任何人都能拿到 schema 定义。
2. **容器层** —— 写→验→读往返与故意构造的非法文件。需要 h5py，缺失时整体跳过。
"""

from __future__ import annotations

import numpy as np
import pytest

from hl3.io import hdf5_schema as hs

h5py = pytest.importorskip("h5py", reason=hs.skip_reason() or "")


# ----------------------------------------------------------------------------------
# 1. 无依赖层
# ----------------------------------------------------------------------------------


def test_flag_bits_are_disjoint_and_within_assigned_range():
    seen = 0
    for flag in hs.FieldFlags:
        assert seen & int(flag) == 0, f"{flag.name} 与已分配位重叠"
        seen |= int(flag)
    assert seen == hs.ASSIGNED_FLAG_MASK
    assert hs.ASSIGNED_FLAG_MASK & hs.RESERVED_FLAG_MASK == 0
    assert hs.RESERVED_FLAG_MASK & hs.PLUGIN_FLAG_MASK == 0
    assert hs.ASSIGNED_FLAG_MASK | hs.RESERVED_FLAG_MASK | hs.PLUGIN_FLAG_MASK == 0xFFFFFFFF


def test_valid_mask_matches_spec_predicate():
    F = hs.FieldFlags
    flags = np.array(
        [
            int(F.CONVERGED),
            int(F.CONVERGED | F.SEEDED),
            int(F.CONVERGED | F.MASKED),
            int(F.CONVERGED | F.OUTLIER_FILTERED),
            int(F.CONVERGED | F.INTERPOLATED_FILL),
            0,
            int(F.CONVERGED | F.EDGE_CLAMPED | F.GPU_PATH),
        ],
        dtype=np.uint32,
    )
    assert hs.valid_mask(flags).tolist() == [True, True, False, False, False, False, True]


def test_reserved_bits_are_rejected():
    ok = np.array([int(hs.FieldFlags.CONVERGED)], dtype=np.uint32)
    bad = np.array([int(hs.FieldFlags.CONVERGED) | (1 << 12)], dtype=np.uint32)
    assert not hs.has_reserved_flag_bits(ok)
    assert hs.has_reserved_flag_bits(bad)
    assert "bit12" in hs.describe_flags(int(bad[0]))


def test_vsg_formula_and_argument_guards():
    # docs/schema-hdf5.md §9.3: (window_pts - 1) * step_px + subset_px
    assert hs.vsg_size_px(5, 7, 29) == 57.0
    assert hs.vsg_size_px(1, 7, 29) == 29.0
    for bad in ((4, 7, 29), (5, 7, 30), (5, 0, 29)):
        with pytest.raises(ValueError):
            hs.vsg_size_px(*bad)


def test_canonical_json_follows_appendix_b():
    out = hs.canonical_json({"b": 1, "a": 0.5, "drop": None, "u": "中", "l": [1, True]})
    assert out == '{"a":0.5,"b":1,"l":[1,true],"u":"中"}'  # 排序、无空白、省略 None、不转义
    assert hs.canonical_json(0.1) == "0.10000000000000001"  # 17 位有效数字，往返无损
    with pytest.raises(ValueError):
        hs.canonical_json(float("nan"))


def test_config_hash_is_order_independent():
    a = {"subset_px": 29, "step_px": 7, "shape": "affine"}
    b = {"shape": "affine", "step_px": 7, "subset_px": 29}
    assert hs.config_hash(a)[0] == hs.config_hash(b)[0]
    assert hs.config_hash(a)[1] in (hs.HASH_ALGO_BLAKE3, hs.HASH_ALGO_FALLBACK)


def test_shape_param_counts_match_spec_notation():
    assert hs.shape_param_count("rigid") == 2
    assert hs.shape_param_count("affine") == 6
    assert hs.shape_param_count("quadratic") == 12
    with pytest.raises(ValueError):
        hs.shape_param_count("irregular_plugin")


def test_default_chunks_never_exceed_shape():
    assert hs.default_chunks((3, 20)) == (3, 20)
    assert hs.default_chunks((1000, 100000)) == (16, 4096)
    assert hs.default_chunks((0, 5)) is None


def test_distortion_param_counts_cover_every_model():
    assert set(hs.DISTORTION_PARAM_COUNT) == set(hs.DISTORTION_MODELS)


# ----------------------------------------------------------------------------------
# 2. 容器层
# ----------------------------------------------------------------------------------


@pytest.fixture
def sample(tmp_path):
    spec = hs.SyntheticSpec()
    return hs.write_synthetic_hl3(tmp_path / "synthetic.hl3", spec), spec


def test_synthetic_sample_validates(sample):
    path, _ = sample
    assert hs.validate_file(path) == []


def test_strict_mode_reports_should_level_gaps(sample):
    path, _ = sample
    # 参考写入器不是内核，没有 @git_sha 可写；strict 必须点出来，证明它不是空跑。
    assert any("git_sha" in p for p in hs.validate_file(path, strict=True))


def test_roundtrip_matches_analytic_solution(sample):
    path, spec = sample
    data = hs.read_analysis(path)
    expected = hs.synthetic_fields(spec)

    assert data.u.shape == (spec.n_frames, spec.n_points)
    np.testing.assert_array_equal(data.u, expected["u"])
    np.testing.assert_array_equal(data.v, expected["v"])
    np.testing.assert_array_equal(data.strain["exx"], expected["exx"])
    np.testing.assert_array_equal(data.ref_xy, expected["ref_xy"])

    # 均匀单轴拉伸：exx 逐帧恒定，exy 恒为 0。
    for f in range(spec.n_frames):
        np.testing.assert_allclose(data.strain["exx"][f], spec.exx_per_frame * f, rtol=1e-6)
    np.testing.assert_array_equal(data.strain["exy"], 0.0)


def test_units_and_metadata_survive_roundtrip(sample):
    path, spec = sample
    data = hs.read_analysis(path)
    assert data.space == "px"  # 未标定 2D 不得假借 1 px = 1 mm
    assert data.analysis_type == "2d"
    assert data.schema_version == hs.SCHEMA_VERSION
    assert data.vsg_px == spec.vsg_px
    assert data.diagnostics["deterministic"] == 1
    assert data.diagnostics["device"] == "cpu"
    assert data.config["subset_px"] == spec.subset_px
    assert hs.config_hash(spec.to_config())[0] == data.config_hash


def test_valid_mask_and_seed_flag_roundtrip(sample):
    path, _spec = sample
    data = hs.read_analysis(path)
    assert data.valid.all()
    seeded = data.flags & int(hs.FieldFlags.SEEDED) != 0
    assert seeded[:, 0].all() and not seeded[:, 1:].any()


def test_writer_is_deterministic(tmp_path):
    spec = hs.SyntheticSpec()
    a = hs.read_analysis(hs.write_synthetic_hl3(tmp_path / "a.hl3", spec))
    b = hs.read_analysis(hs.write_synthetic_hl3(tmp_path / "b.hl3", spec))
    np.testing.assert_array_equal(a.u, b.u)
    assert a.config_hash == b.config_hash


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda f: f.attrs.__delitem__(hs.A_SCHEMA_VERSION), hs.A_SCHEMA_VERSION),
        (lambda f: f["/analyses/ana_01/fields/u"].attrs.__setitem__(hs.A_SPACE, "mm"), "@space"),
        (lambda f: f["/analyses/ana_01"].attrs.__setitem__("type", "4d"), "@type"),
        (lambda f: f["/analyses/ana_01"].attrs.__setitem__("sequence", "ghost"), "不存在"),
        (lambda f: f["/analyses/ana_01/strain/default"].attrs.__setitem__("tensor", "nope"), "@tensor"),
        (lambda f: del_dataset(f, "/analyses/ana_01/fields/v"), "缺必填数据集 v"),
    ],
)
def test_validator_catches_illegal_files(sample, mutate, needle):
    path, _ = sample
    with h5py.File(path, "r+") as f:
        mutate(f)
    problems = hs.validate_file(path)
    assert any(needle in p for p in problems), problems


def test_reader_rejects_reserved_flag_bits(sample):
    path, _ = sample
    with h5py.File(path, "r+") as f:
        dset = f["/analyses/ana_01/fields/flags"]
        dset[0, 0] = int(dset[0, 0]) | (1 << 20)
    assert any("保留位" in p for p in hs.validate_file(path))


def test_reader_rejects_future_major_version(sample):
    path, _ = sample
    with h5py.File(path, "r+") as f:
        f.attrs[hs.A_SCHEMA_VERSION] = "2.0.0"
    with pytest.raises(ValueError, match="主版本"):
        hs.read_analysis(path)
    assert any("主版本" in p for p in hs.validate_file(path))


def del_dataset(f, path):
    del f[path]
