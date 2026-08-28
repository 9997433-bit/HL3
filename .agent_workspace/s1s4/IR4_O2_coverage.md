ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# IR4-O2 `src/hl3` 测试覆盖率报告

本报告只做**测量与分析**，不改动 `tests/` 下的任何文件。第 5 节给出 10 条
推荐用例，标注了实现代价，供后续 owner 挑选实现。

## 0. 复现方式

`pytest-cov` 不在 `pyproject.toml` 的 `[project.optional-dependencies]` 里，
需要单独装：

```bash
pip3 install pytest-cov            # 本次实测 pytest-cov 7.1.0 / coverage 7.15.4
python3 -m pytest --cov=hl3 --cov-report=term-missing -q
python3 -m pytest --cov=hl3 --cov-branch --cov-context=test -q   # 得到"哪条用例覆盖哪个模块"
```

运行环境：Python 3.12.3、Linux、CPU-only。可选依赖状态：
`numpy` / `matplotlib` / `h5py` 可用；**`tkinter`、`blake3`、`scipy` 缺失**。
这一点很关键——它意味着 `hl3.gui.viewer` 的"有 tk"分支在本 CI 里根本无法执行。

结果：**700 passed in 55.76s**，无 skip、无 xfail、无 warning 级失败。

> 建议把 `pytest-cov` 加进 `[project.optional-dependencies].test`，
> 否则 CI 里 `--cov` 会直接报 unrecognized argument。

## 1. 用例计数

| 维度 | 数量 |
| --- | --- |
| 收集到的测试项（含 parametrize 展开） | **700** |
| `def test_*` 函数 | **483** |
| 测试文件 | **19**（`tests/` 18 个 + `src/tests/` 1 个） |
| 测试代码行数 | 8659 行（`tests/` 8597 + `src/tests/` 62） |
| 被测源码行数 | 15216 行 / 35 个 `.py` / 5847 条可执行语句 |
| `conftest.py` | **0 个**（没有共享 fixture 层） |

按文件（收集数 / `def test_` 数）：

| 测试文件 | 收集 | 函数 |
| --- | ---: | ---: |
| `tests/test_icgn_synth.py` | 127 | 60 |
| `tests/test_strain.py` | 120 | 62 |
| `tests/test_pipeline_3d.py` | 120 | 87 |
| `tests/test_stereo_synth.py` | 71 | 57 |
| `tests/test_pipeline_2d.py` | 62 | 56 |
| `tests/test_stereo_match.py` | 50 | 45 |
| `tests/test_icgn_second.py` | 44 | 37 |
| `tests/test_uq.py` | 39 | 28 |
| `tests/test_hdf5_schema.py` | 23 | 18 |
| `tests/test_validate.py` | 16 | 16 |
| `src/tests/test_mock_capture.py` | 9 | 3 |
| `tests/test_s2_s3_smoke.py` | 4 | 1 |
| `tests/test_s4_smoke.py` | 3 | 1 |
| `tests/test_cli_run.py` | 3 | 3 |
| `tests/test_s1_metrology.py` | 2 | 2 |
| `tests/test_gui.py` | 2 | 2 |
| `tests/test_fea.py` | 2 | 2 |
| `tests/test_env_guards.py` | 2 | 2 |
| `tests/test_viz.py` | 1 | 1 |

分布严重偏斜：S1–S3 的数值内核（ICGN / stereo / strain / pipeline / uq）
占 700 项里的 **633 项**；而 S4 这一轮新增的整条产品链
（`cli/run` + `viz` + `fea` + `gui`，约 1300 条语句）只有
`test_cli_run` 3 + `test_fea` 2 + `test_gui` 2 + `test_viz` 1 = **8 项**
功能用例，外加 `test_s4_smoke` 的 3 项纯 import 冒烟。

## 2. 覆盖率总表

总计：**语句 5847，未覆盖 725，行覆盖 88%**；开启分支后
（Branch 1708 / BrPart 269）**综合 85%**。

| 模块 | Stmts | Miss | 行覆盖 | 分支覆盖 | 覆盖它的用例数 | 主要来源 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `__main__.py` | 4 | 4 | **0%** | 0% | **0** | — |
| `gui/viewer.py` | 24 | 24 | **0%** | 0% | **0** | — |
| `cli/run.py` | 302 | 150 | **50%** | 44% | 1 | `test_cli_run` |
| `viz/plot2d.py` | 440 | 170 | **61%** | 54% | 1 | `test_viz` |
| `viz/imwrite.py` | 97 | 26 | **73%** | 65% | 1 | `test_viz` |
| `cli/__main__.py` | 193 | 48 | 75% | 73% | 2 | `test_cli_run` |
| `viz/colormaps.py` | 76 | 19 | 75% | 70% | 1 | `test_viz` |
| `fea/project.py` | 410 | 82 | 80% | 73% | 2 | `test_fea` |
| `gui/aoi.py` | 42 | 4 | 90% | 85% | 1 | `test_gui` |
| `io/hdf5_schema.py` | 684 | 87 | 87% | 83% | 116 | `test_strain`, `test_hdf5_schema` |
| `strain/vsg.py` | 58 | 3 | 95% | 93% | 129 | `test_strain` |
| `correlate/icgn.py` | 555 | 24 | 96% | 95% | 338 | `test_icgn_synth`, `test_pipeline_*` |
| `stereo/triangulate.py` | 388 | 16 | 96% | 94% | 158 | `test_pipeline_3d`, `test_stereo_synth` |
| `uq/propagate.py` | 211 | 8 | 96% | 94% | 38 | `test_uq` |
| `cli/validate.py` | 31 | 1 | 97% | 95% | 12 | `test_validate` |
| `pipeline/dic2d.py` | 404 | 12 | 97% | 96% | 107 | `test_pipeline_2d` |
| `pipeline/dic3d.py` | 711 | 21 | 97% | 96% | 116 | `test_pipeline_3d` |
| `stereo/calibrate.py` | 479 | 15 | 97% | 95% | 167 | `test_pipeline_3d`, `test_stereo_synth` |
| `strain/field.py` | 167 | 5 | 97% | 96% | 117 | `test_strain`, `test_uq` |
| `strain/pls.py` | 137 | 3 | 98% | 97% | 140 | `test_strain` |
| `stereo/match.py` | 239 | 3 | 99% | 99% | 72 | `test_stereo_match` |
| `capture/mock.py` | 68 | 0 | 100% | 100% | 46 | `test_mock_capture`, `test_pipeline_2d` |
| `strain/tensors.py` | 89 | 0 | 100% | 100% | 84 | `test_strain` |
| 12 个 `__init__.py` | 38 | 0 | 100% | — | 0（仅 import 期执行） | — |

"覆盖它的用例数"来自 `--cov-context=test` 写入 `.coverage` 的 SQLite
`context` 表，是**真正执行到该模块语句**的不同 test node id 数量，比
"哪个文件名里带这个词"可靠得多。

## 3. 零测试的模块

### 3.1 完全零执行（0% 覆盖，没有任何用例触碰）

**`src/hl3/__main__.py`**（4 条语句，0%）
`python -m hl3` 的 shim。实测手工执行是好的（`python3 -m hl3` 打印 usage、
退出码 2），但 `if __name__ == "__main__"` 块在 pytest 里天然不会执行，
而 `prog="python -m hl3"` 这个参数没有任何回归保护——改坏了帮助文本里的
`prog` 不会有人发现。

**`src/hl3/gui/viewer.py`**（24 条语句，0%）
唯一一个既没有专属测试、又没有被间接执行的功能模块。见 §4.3。

### 3.2 有测试文件但覆盖密度极低

这几个模块名义上"有测试"，但用例数与代码量完全不成比例，实际上和无测试
差别不大：

| 模块 | 语句 | 触及它的用例 | 每 100 语句用例数 |
| --- | ---: | ---: | ---: |
| `viz/plot2d.py` | 440 | 1 | 0.23 |
| `cli/run.py` | 302 | 1 | 0.33 |
| `fea/project.py` | 410 | 2 | 0.49 |
| `cli/__main__.py` | 193 | 2 | 1.0 |
| `viz/imwrite.py` | 97 | 1 | 1.0 |
| `viz/colormaps.py` | 76 | 1 | 1.3 |
| （对照）`correlate/icgn.py` | 555 | 338 | 61 |

整个 `viz` 包（613 条语句、三个模块）只被 `tests/test_viz.py` 里的一个
`test_builtin_png_and_ppm` 覆盖，而且它用 `backend="builtin"` 显式绕开了
matplotlib 路径。

### 3.3 零执行的函数（有 body 但一行都没跑过）

按模块归类，只列 ≥3 条语句的：

| 模块 | 函数 | 语句 |
| --- | --- | ---: |
| `cli/run.py` | `_load_netpbm` | 32 |
| `cli/run.py` | `_report` | 19 |
| `cli/run.py` | `load_image` | 18 |
| `cli/run.py` | `_load_with_pillow` | 14 |
| `cli/run.py` | `_load_npz` | 10 |
| `cli/run.py` | `_load_npy` / `_number` | 4 / 3 |
| `viz/plot2d.py` | `run_field` | 29 |
| `viz/plot2d.py` | `_save_matplotlib` | 26 |
| `viz/plot2d.py` | `save_run_field` | 20 |
| `viz/plot2d.py` | `_run_unit` | 7 |
| `viz/plot2d.py` | `matplotlib_available` | 5 |
| `viz/plot2d.py` | `save_field_png`、`_named_quantity`、`_to_gray` | 4 / 3 / 3 |
| `fea/project.py` | `_nearest_fill` | 19 |
| `fea/project.py` | `NodalProjection.valid` / `.coverage`、`TriMesh.node_valence` | 3 each |
| `gui/viewer.py` | `main` + 模块体 | 16 + 8 |
| `io/hdf5_schema.py` | `_selftest` | 28 |
| `io/hdf5_schema.py` | `sequence_path`/`grid_path`/`fields_path`/`strain_path`/`uncertainty_path`/`diagnostics_path` | 1 each |
| `cli/__main__.py` | `_selftest_check` | 13 |
| `viz/imwrite.py` | `png_size` / `write_pgm` | 6 / 4 |
| `viz/colormaps.py` | `colormap_names` / `is_diverging` | 4 / 2 |
| `pipeline/dic3d.py` | `_subset_offsets`、`Frame3D.u/.v/.w` | 3 + 1×3 |
| `correlate/icgn.py` | `BSplineInterpolator.__call__`、`_ShapeFunction.promote` | 1 each |

`io/hdf5_schema.py` 那六个 `*_path()` 助手一条都没跑，说明
`test_hdf5_schema.py` 是靠字面量路径字符串断言的，没走公共路径构造器——
路径常量改名时测试不会红。

## 4. 高风险未测路径

### 4.1 ICGN 失败路径（`correlate/icgn.py`）

模块整体 96%，但**没覆盖的 24 行几乎全是失败/降级分支**，也就是最需要
测试的部分。逐条列出：

| 行 | 路径 | 为什么高风险 |
| --- | --- | --- |
| 1081–1083 | `np.linalg.cholesky(hessian)` 抛 `LinAlgError` → `Status.SINGULAR_HESSIAN` | 现有的 9 处 `SINGULAR_HESSIAN` 断言全部来自 1057（`_is_flat`）或 1073（`_well_conditioned`）这两条**前置**闸门。Cholesky 这条兜底从未触发过，`hessian_reg` 对角加载一旦调参失误让前置闸门放行了半正定矩阵，落到这里是否真能优雅降级——无人验证。 |
| 1119–1121 | `shape.compose_inverse(p, dp)` 抛 `LinAlgError` → `SINGULAR_HESSIAN` + `break` | 只在二阶（12 参数）下可能发生。注意 `compose_inverse_second_order` 里的 `abs(det) <= 1e-12 * mag^2` 那条 `raise`（icgn.py:803）**是**有单元测试的——缺的是 `_icgn` 迭代循环里接住它的那个 `except`。也就是说异常能抛出，但"抛出后求解器是否正确降级并继续处理其余点"从未验证。同一函数里 810 行（`composed` 非有限）那条 `raise` 也零覆盖。 |
| 1145 | 收敛**后**复核发现 warp 已越界 → 把 `CONVERGED` 改回 `OUT_OF_BOUNDS` | 这是"报告的 ZNCC 必须匹配返回的参数"这条契约的执行点。写错了会静默返回一个越界解并标成收敛。 |
| 1151–1152 | 收敛后复核发现 target 子集是平的 → `SINGULAR_HESSIAN` 且 `zncc = -1.0` | 同上，且这里还要负责把 `zncc` 打回 `-1.0`。漏掉的话下游 `pipeline` 的 `_accepted` 会拿一个陈旧的高 ZNCC 去接受一个坏点。 |
| 1172–1173 | 协方差 `np.linalg.inv(hessian_raw)` 抛 `LinAlgError` → `pass`（留 `nan`） | 这是 UQ 链路的入口。静默 `pass` 意味着失败时 `cov` 保持 `nan`；但从未验证过 `uq/propagate` 在拿到全 `nan` 协方差时的行为。 |
| 989 | `points is None` → 走 `make_grid` 默认网格 | **公共 API 的默认参数路径完全没测**。所有 700 项用例都显式传了 `points`。手工验证可用（64×64 图、`subset_radius=9`、`step=8` → 36 个点），但 `margin = subset_radius + search_radius + 2` 这个默认边距没有回归保护。 |
| 423, 426 | `make_grid` 的 `shape` 非二元组、`shape` 含非正尺寸两条报错 | 承接上一条。（`margin < 0` 与 `2*margin >= min(h,w)` 两条**是**测过的。） |
| 538 | 整数搜索初值：ZNCC 图全为 `-1` 时返回 `(0, 0, -1.0)` | 无纹理/全饱和区域的初值降级路径。返回 `-1` 会让上层把该点标成 `NO_INITIAL_GUESS`，这条链路没端到端验证过。 |
| 575 | `_check_order` 对 `order ∉ {1, 2}` 报错 | 公共 `shape_param_count()` / `icgn(shape_order=...)` 的入参校验。 |
| 1242 | `_well_conditioned` 在最大特征值非有限或 ≤ 0 时提前返回 `False` | Hessian 出现 `nan`/`inf` 时的兜底。目前只有"条件数超限"那条出口被测过。 |
| 397–398 | `reference_gradients` 中 `3 <= n < 5` 的中心差分分支 | 只有极小图像（3 或 4 像素边长）才会走。 |
| 278, 306 | B 样条预滤波与镜像折叠的 `n == 1` 退化分支 | 单像素维度。 |
| 887 | `_ShapeFunction.promote`（一阶结果提升为二阶初值） | 二阶求解用一阶结果做初值的路径。 |

另外 `Status` 枚举 9 个取值里，**`Status.UNCOMPUTED`（0）在整个测试套件中
从未被断言过**——它是 `status_out` 的初始填充值，任何"某点被跳过且没有被
任何分支赋值"的 bug 都会以 `UNCOMPUTED` 泄漏到结果里，而没有测试会发现。

### 4.2 立体退化（`stereo/*`）

三个模块行覆盖 96–99%，看起来很好，但**未覆盖的行几乎全部是退化几何的
`raise` 分支**——正是立体视觉最容易出事的地方：

| 位置 | 退化情形 | 状态 |
| --- | --- | --- |
| `triangulate.py:313` | 两相机中心重合 → 基础矩阵范数消失，`"degenerate stereo pair: fundamental matrix vanished"` | 未测 |
| `triangulate.py:231` | `camera_center()` 的 `abs(Ch[3]) < _REL_EPS` → `"camera centre at infinity"`（仿射/正交投影矩阵） | 未测 |
| `triangulate.py:501–502` | `_ray_directions` 中 `P[:, :3]` 奇异 → `"viewing rays are undefined"` | 未测 |
| `triangulate.py:271` | Hartley 归一化矩阵在**空视图**（`x.shape[0] == 0`）时返回 `np.eye(3)` | 未测；某一视图全部点被 mask 掉时会走到这里 |
| `triangulate.py:599` | 所有视图权重为 0 → `"at least one view weight must be positive"` | 未测 |
| `triangulate.py:630, 665–666` | `tol < 0` 报错；非线性精化的收敛/早退分支 | 未测 |
| 分支 `[656, 686]` | `triangulate_nonlinear` 的迭代循环**从未跑满 `iters`**——只走过提前收敛的出口 | 未测；近平行光线不收敛时的行为无保护 |
| `calibrate.py:190` | `stereo_angle_deg` 在某个相机中心落在世界原点时 → `"stereo angle is undefined"` | 未测 |
| `calibrate.py:493` | DLT resection 得到退化投影矩阵（`scale < _REL_EPS`，例如所有标定点共面/共线）→ `"the target geometry is not sufficient to fix the camera"` | **未测；这是标定失败最常见的真实成因** |
| `calibrate.py:579` | Umeyama 对齐中 `det(U)·det(Vt) < 0` → 反射修正 `D[2,2] = -1` | **未测；漏掉这条会得到镜像的刚体变换**，数值上"看起来收敛"但结果是左右手系翻转 |
| `calibrate.py:650` | `n_finite == 0` **且** `align=True` 时补 `align_*` 的 `nan` 键 | 未测；`n_finite == 0` 本身测过，但对齐开启时的键集合没测，下游按键取值会 `KeyError` |
| `calibrate.py:122/124/130/137/139` | `Camera.__post_init__` 里 K、R 的形状校验及后续有限性检查（`t` 的那条测过） | 未测 |
| `calibrate.py:172/237/277/310/367` | `StereoRig` 非 `Camera` 类型、`look_at_extrinsics` 非有限输入、`standoff_mm <= 0`、`half_extent_mm <= 0`、`depth/lateral_span_mm < 0` | 未测；一批入参负例 |
| `match.py:217–218` | `plane_disparity` 左投影矩阵前 3×3 奇异 → `"viewing rays are undefined"` | 未测 |

其中 `calibrate.py:579` 的反射修正尤其危险：它不抛异常，只是静默改变结果，
所以没有测试就等于没有任何信号。

### 4.3 GUI 在无 tk 环境下的行为（`gui/viewer.py` + `gui/aoi.py`）

`gui/viewer.py` **0% 覆盖**，而本 CI 环境恰好**没有 tkinter**，这意味着 S4
承诺的"GUI 缺失时优雅降级"这条契约完全没有验证。手工执行暴露了三个问题：

1. **`main()` 在无 tk 时的返回码没测。** 实测
   `main(["--help"])` 返回 `2` 并打印
   `error: tkinter is required for the window (No module named 'tkinter'); on Debian/Ubuntu install python3-tk`。
   行为是对的，但没有任何测试锁定它——退化路径的退出码和安装提示文案是
   面向用户的契约，属于最该回归的东西。

2. **`--help` 在无 GUI 环境下不可达。** `viewer.py:42` 的
   `if args and args[0] in {"--help", "-h"}` 排在 matplotlib（:22）和
   tkinter（:31）两个 import 守卫**之后**，所以缺 tk 时 `--help` 也返回 2。
   `EXIT_OK` 那条分支在本 CI 里是死代码。这要么是 bug（帮助文本应该在没有
   GUI 依赖时也能打印），要么是需要写进文档的有意设计——目前两者都没有。

3. **`python -m hl3.gui.viewer` 什么都不做。** 模块里没有
   `if __name__ == "__main__":` 块，实测该命令静默退出 0，不打印任何东西。
   但 `viewer.py:43` 的帮助文本自己写的就是
   `usage: python -m hl3.gui.viewer [field.npy]`。文档与实现直接矛盾，
   而且是零覆盖所以没人发现。

`gui/aoi.py` 90%，缺的 4 行（27/29/31/38）全是 `PolygonAOI` 的输入校验：
形状不是 `(N, 2)`、顶点少于 3 个、含非有限值，以及 `contains()` 的 `xy`
形状校验。`test_gui.py` 只有一条 happy-path 往返测试。

### 4.4 其他值得记一笔的

- **`io/hdf5_schema.validate_file`：132 条语句缺 39 条（67%）**，是全仓最大的
  单函数缺口。缺的是 schema 版本不合法、未知 `@hash_algo`、未知
  `@role`/`@shutter`、畸变模型参数个数不符、`strict` 模式下缺协方差等
  **全部负例分支**。这个函数是 `hl3 validate` 的整个价值所在，只测了正例
  等于没测。
- **`fea/project.py` 410 条语句只有 2 条用例**，且 `method="nearest"` 与
  `fill_nearest=True` 两条路径（核心是 19 条语句的 `_nearest_fill`）**零执行**。
  `TriMesh.__post_init__` 36 条语句缺 14 条，全是网格合法性校验
  （退化三角形、索引越界、重复节点等）。
- **`cli/run.py` 的整个图像输入层零执行**：`load_image` 及其四个后端
  （`.npy` / `.npz` / Netpbm / Pillow）加起来 78 条语句，一行没跑。
  `test_cli_run.py::test_run_synthetic` 只走了 `--synthetic` 分支。
  也就是说 `hl3 run` **从未被测过读真实图像文件**。
- **`cli/run.py::_report`（19 条语句）零执行**：`--quiet` 之外的人类可读输出
  完全没测；唯一的用例传了 `--quiet`。
- **`viz/plot2d.py::_save_matplotlib`（26 条）与 `resolve_backend`（28%）零/低覆盖**：
  matplotlib 在本环境是**装了的**，但唯一的 viz 用例用
  `backend="builtin"` 显式绕开了它。后端自动选择逻辑（环境变量
  `HL3_VIZ_BACKEND`、可用性探测、回退顺序）没有任何保护。
- **`cli/__main__.py::_selftest_check`（13 条）零执行**：`hl3 doctor` 唯一的用例
  传了 `--no-selftest`，自检本体从未运行。

## 5. 推荐补充的 10 条测试

按"风险 ÷ 实现代价"排序。**本报告没有实现其中任何一条**；`trivial` 标记
表示预计 ≤10 行、不需要新 fixture。

| # | 建议用例 | 目标未覆盖行 | 要点 | 代价 |
| --- | --- | --- | --- | --- |
| 1 | `test_viewer_exits_2_without_gui_deps` | `gui/viewer.py` 全部 24 行 | `monkeypatch` 掉 `sys.modules["tkinter"] = None`（或直接依赖本环境无 tk），断言 `main([]) == 2` 且 stderr 含 `python3-tk`；再 `monkeypatch` 掉 matplotlib 断言 `hl3[viz]` 提示。顺带把 §4.3 的 `--help` 不可达与缺 `__main__` 守卫两个问题坐实成 xfail 或改代码。 | **trivial** |
| 2 | `test_polygon_aoi_rejects_bad_vertices` | `gui/aoi.py` 27, 29, 31, 38 | 四个 `pytest.raises(ValueError)`：`(N,3)` 形状、2 个顶点、含 `nan`、`contains()` 传 `(P,3)`。 | **trivial** |
| 3 | `test_icgn_default_grid_when_points_is_none` | `icgn.py` 989（+ 423, 426, 575） | 不传 `points` 调 `icgn()`，断言点数等于 `make_grid(shape, params)` 的长度且坐标逐一相等；再补 `make_grid` 的两条入参负例（`shape` 非二元组、含非正尺寸）和 `shape_param_count(3)` → `ValueError`。 | **trivial** |
| 4 | `test_stereo_degeneracy_raises` | `triangulate.py` 231, 313, 501–502；`calibrate.py` 190；`match.py` 217–218 | 一组参数化的 `pytest.raises(ValueError, match=...)`：两相机中心重合 → `fundamental matrix vanished`；`P` 最后一列使中心在无穷远 → `camera centre at infinity`；`P[:, :3]` 构造成奇异 → `viewing rays are undefined`；某相机中心置于世界原点 → `stereo angle is undefined`。全部是纯矩阵字面量，不需要合成图像。 | **trivial** |
| 5 | `test_umeyama_handles_reflection` | `calibrate.py` 579 | 构造一组点云和它的**镜像**，断言 Umeyama 对齐返回的 `R` 满足 `det(R) == +1`（即走了 `D[2,2] = -1` 修正而不是返回反射矩阵）。这是唯一一条静默出错的退化路径，优先级应视为最高之一。 | 低 |
| 6 | `test_icgn_singular_hessian_fallbacks` | `icgn.py` 1081–1083, 1119–1121, 1172–1173（+ 1242） | 三条兜底 `except LinAlgError` 都只能靠 `monkeypatch` 让 `np.linalg.cholesky` / `compose_inverse_second_order` / `np.linalg.inv` 抛 `LinAlgError` 来打到（自然构造会先被前置闸门拦下）。断言点状态是 `SINGULAR_HESSIAN`、协方差保持 `nan`、**其余点仍正常求解**（这才是"降级"而不是"崩溃"的定义）。 | 中 |
| 7 | `test_icgn_post_convergence_recheck` | `icgn.py` 1145, 1151–1152 | 收敛后复核把 `CONVERGED` 降级为 `OUT_OF_BOUNDS` / `SINGULAR_HESSIAN`。做法：给一个位于图像边缘、真实位移把 warp 推出边界的点；以及一个 target 侧为平场的点。同时断言降级时 `zncc == -1.0`。顺带把 `Status.UNCOMPUTED` 也加一条断言（全 mask 输入）。 | 中 |
| 8 | `test_cli_run_reads_image_files` | `cli/run.py` 117–249（`load_image` + 四个后端）、549–557（`_write_out`）、787–840（`_report`） | 用 `tmp_path` 写两帧 `.npy`、两帧 `.npz`、两帧 `.pgm`（`hl3.viz` 已经能写 PPM，PGM 需要 `imwrite.write_pgm`——那个函数也是零覆盖，一举两得），跑 `run_main([...])` 不带 `--quiet`，断言退出 0 且 stdout 出现网格尺寸/质量行。再加负例：三维数组 → `ImageLoadError`、`--out foo.txt` → `UsageError`、`--out foo.npy --field bogus` → `UsageError`。 | 中 |
| 9 | `test_validate_file_reports_each_violation` | `hdf5_schema.py` 1099–1244（`validate_file` 缺的 39 条） | 参数化地写若干**故意坏掉**的 `.hl3` 文件（`h5py` 在本环境可用）：`@schema_version` 非语义化 / 主版本超前、未知 `@hash_algo`、未知 `@role` 与 `@shutter`、`@model` 与 dist 长度不符、缺 `/project/units`、`strict=True` 且无协方差。每个断言 `problems` 里出现对应消息。这是全仓最大的单函数缺口，也是 `hl3 validate` 的核心价值。 | 中高 |
| 10 | `test_fea_nearest_and_fill_nearest` | `fea/project.py` 616–634（`_nearest_fill`）、815–826、886–895 | `project_to_nodes(..., method="nearest")` 在样本稀疏于节点时的行为；`fill_nearest=True` 时被 barycentric 漏掉的节点是否被最近邻补上；`max_distance` 超限时是否保持 `nan`。同时补 `NodalProjection.valid` / `.coverage` / `TriMesh.node_valence` 这三个零执行的属性。 | 中 |

补充建议（不计入 10 条）：

- 把 `pytest-cov` 加进 `[project.optional-dependencies].test`，并在 CI 里加
  `--cov=hl3 --cov-fail-under=88`（不开 `--cov-branch` 时当前正好 88%）。
  阈值本身挡不住已有缺口，但能防止 S4 那种"新增上千行只配 8 条用例"再次
  发生。
- 更有价值的是按包设下限而不是单一全局阈值：全局 88% 完全掩盖了
  `cli/run.py` 50% 和 `viz/plot2d.py` 61% 这两个用户直接接触的表面。
- 目前没有 `conftest.py`。第 8、9 条建议共享一个"写一个最小合法 `.hl3`"和
  "写一对合成图像文件"的 fixture，否则会在多个测试文件里重复。
