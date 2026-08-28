ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast
<!-- SPDX-License-Identifier: Apache-2.0 -->

# IR1-O3：HL3-2D 序列流水线（`hl3.pipeline.dic2d`）

> 子代理：IR1-O3（opus-fast）｜轮次：Impl-R1 / S1
> 独占路径（与 `s1s4/IR1_DISPATCH.md` 一致）：`src/hl3/pipeline/**`、`tests/test_pipeline_2d.py`、本报告
> 额外改动（任务书明确授权的唯一一处）：`src/hl3/__init__.py` 的 `__all__` 加 `"pipeline"`，一行
> **未触碰**：`src/hl3/correlate/**`、`src/hl3/strain/**`、`src/hl3/stereo/**`、`src/hl3/io/**`、`src/hl3/capture/**`、`benchmarks/**`、`docs/**`、`README.md`、`pyproject.toml`、`.github/**`
> 环境：CPU-only（4 vCPU，无 GPU），Python 3.12.3 + NumPy 2.4.4，纯 NumPy，未引入任何新依赖
> 法律边界：只调用本仓自己的 R2-O1/R3-O1 内核，无任何外部 DIC 代码、无 VIC 逆向

---

## 0. TL;DR — 实测数字

| 项 | 数值 |
|---|---|
| **新增代码** | `src/hl3/pipeline/dic2d.py` **989 行** + `src/hl3/pipeline/__init__.py` 46 行 |
| **新增测试** | `tests/test_pipeline_2d.py` **900 行 / 62 个用例**，`62 passed in 4.23s` |
| 全仓（CI 口径 `pytest -q`） | **`460 passed in 17.52s`**，0 failed |
| **固定参考下与内核逐位一致** | `np.array_equal(run.frames[1].p_total, icgn_first_order(...).p)` → **True**（`zncc`、`status` 同为 True） |
| 亚像素精度（傅里叶位移散斑，128²，subset 21×21，36 POI） | 逐帧 mean\|误差\| **7.585e−04 / 1.001e−03 / 8.834e−04 px**，max **5.7e−03 px** |
| 吞吐 | **770 POI-solves/s**（4 帧 × 36 POI，含参考帧自相关，单线程纯 NumPy） |
| 参考更新的误差代价（同一 5 帧序列，末帧 mean\|误差\|） | FIXED **2.708e−07** ／ EVERY_N(2)（2 次更新）**1.092e−05** ／ EVERY_N(1)（4 次更新）**9.197e−05** px |
| PREV_FRAME 种子的收益 | 全序列总迭代数 **584**（零种子 608），−4.0% |
| 应变 | IR1-O2 定稿后**自动接通**：`backend = hl3.strain.compute_strain`，刚体平移下 `exx/exy/eyy` 最大 **7.5e−08**。写这份实现时该模块还 import 即抛错，运行照常完成——两种状态都有用例 |

一句话：**流水线只做"序列层"的事——建一次网格、逐帧调一次内核、传种子、换参考、合成累积 warp——相关数学一行都没有重写；固定参考下它逐位吐出内核自己的数字。** 应变从设计上就是可选的：`hl3.strain` 缺席、半写、签名不匹配三种情况都只降级不失败（只有 `StrainMode.REQUIRED` 才变成运行失败）；而它一旦定稿，链路**不改流水线代码就自己接通了**。

---

## 1. 交付物

| 文件 | 改动 |
|---|---|
| `src/hl3/pipeline/dic2d.py` | 新增，989 行 |
| `src/hl3/pipeline/__init__.py` | 新增，46 行（只做再导出） |
| `tests/test_pipeline_2d.py` | 新增，900 行 / 62 用例 |
| `src/hl3/__init__.py` | `__all__ = ["correlate"]` → `["correlate", "pipeline"]`，**仅此一行** |
| `.agent_workspace/s1s4/IR1-O3-pipeline.md` | 本报告 |

提交（分支 `cursor/ir1-o3-pipeline-e17b`，同时快进推到集成分支 `cursor/dic-sota-plan-259d`）：

1. `57aae98 feat(pipeline): 2D DIC sequence pipeline over the IC-GN reference kernel`
2. `a5ae3a4 test(pipeline): 60 cases for the 2D pipeline, from MockCapture to strain`
3. `1a08aae fix(pipeline): survive a strain module that raises on import`
4. `2056320 docs(s1): IR1-O3 report on the 2D pipeline and its optional strain hand-off`
5. `581fdb8 feat(pipeline): pass subset_px so the merged hl3.strain wires up`

公开 API（`from hl3.pipeline import ...`）：

```
run_sequence, correlate_pair                      # 入口
Dic2DConfig, ReferenceMode, SeedMode, StrainMode  # 配置
Dic2DRun, FrameOutcome, StrainOutcome             # 结果
compose_total, lattice_shape, vsg_size_px         # 可单测的纯函数
resolve_strain_backend, StrainUnavailableError    # 应变对接
```

最小用例（零安装，`PYTHONPATH=src`）：

```python
from hl3.capture import MockCapture
from hl3.correlate import ICGNParams
from hl3.pipeline import Dic2DConfig, run_sequence

run = run_sequence(MockCapture(frame_count=4, shape=(96, 96), seed=3),
                   Dic2DConfig(icgn=ICGNParams(subset_radius=8, step=8), margin=20))
run.field("u").shape        # (4, 7, 7) —— (frame, y, x)，未收敛点为 NaN
run.provenance["l_vsg_px"]  # 49 = (5-1)*8 + 17
```

---

## 2. 设计决定（每条都给理由，不给"惯例"）

### 2.1 不重写内核，并把"不重写"变成可断言的事实

流水线对每个 POI 只做一件事：调一次 `icgn_first_order`。为了让"没动内核数学"不停留在口头，`compose_total(累积, 分段)` 在累积项全零时**直接返回分段结果的副本**而不是乘一遍单位矩阵——否则 `(1+0.01)*1 − 1 = 0.010000000000000009`，固定参考模式下每个点都会带上 1e−17 量级的、纯属流水线自造的扰动。有了这条短路，`test_compose_total_is_identity_on_a_zero_accumulator` 可以用 `np.array_equal` 而不是 `allclose` 来断言，实测中整帧 `p / zncc / status` 与直接调内核**逐位相同**。

这条同时是 R2-O1/R3-O1 那些实测精度表的保护：流水线上层若引入哪怕 1 ulp 的偏移，那些表就得重跑。

### 2.2 参考帧也真的去相关，不假造 identity

第 0 帧对自己相关，数学上必然收敛到 `p = 0`、`ZNCC = 1`，看起来完全可以省掉。**不省**：省掉就等于假设每个 POI 都合法。真跑一遍，子区越界的点在第 0 帧就报 `OUT_OF_BOUNDS`，纹理不足的点在第 0 帧就报 `SINGULAR_HESSIAN`，而不是等到"第一帧真的动了"才暴露。代价是一帧的算力（实测收敛于 1 次迭代），换来的是诊断出现在正确的位置。测试 `test_reference_frame_is_correlated_rather_than_assumed` 用 `iterations >= 1` 锁住这个行为，防止后人"优化"掉。

### 2.3 参考更新：POI 跟着材料点走，因此不需要插值位移场

R1-O1 §2.9 描述增量参考时要求「在变形构形上插值上一段的位移场（薄板样条或线性三角插值）」。那是**按网格重建位移场**时的做法。本流水线的 POI 是有身份的材料点，换参考时直接把该点的参考坐标搬到 `x_ref + u_total`，于是根本不存在"新参考网格点上的旧位移未知"这个问题，插值一步可以整个省掉——也就省掉了它带来的一层偏差。

合成用链式法则（§2.9 原文）：

```
u_total = u_a + u_s ,  F_total = F_s · F_a
```

推导一行：`X + dX --(累积)--> (X + u_a) + F_a·dX --(分段)--> (X + u_a) + u_s + F_s·F_a·dX`。
`test_compose_total_matches_matrix_product` 用 `hl3.correlate.warp_matrix` 的 2×2 块乘积做独立对照。

**误差代价是实测的，不是估计的**（同一 5 帧、每帧 +0.5/+0.25 px 的序列，末帧 mean|误差|）：

| 模式 | 参考更新次数 | 末帧 mean\|误差\| |
|---|---:|---:|
| FIXED | 0 | 2.708e−07 px |
| EVERY_N(2) | 2 | 1.092e−05 px |
| EVERY_N(1) | 4 | 9.197e−05 px |

即：**每换一次参考，误差量级涨约一个数量级**。这正是 §2.9 要求「必须在报告中标注参考更新发生的帧号」的原因，所以 `provenance["reference_updates"]` 是必填项而不是可选诊断。

### 2.4 换参考时丢轨的点：宁可说不知道

换参考的那一帧上没收敛的点，在新参考里的位置是未知的。三种可能处置：沿用旧坐标（继续算，结果是垃圾）、回退到原始网格坐标（同样是垃圾）、承认不知道。选第三种：这些点退出 `tracked`，此后**根本不送进求解器**（既不浪费算力也不产生看起来像数字的垃圾），状态报 `NO_INITIAL_GUESS`——这个码在 R1-O1 §2.6 失败表里的语义正是"没有可用初值"。

对应测试 `test_a_lost_track_is_never_re_anchored_by_guesswork`：一个放在图像角上的越界点，前两帧 `OUT_OF_BOUNDS`，参考在第 1 帧更新之后转为 `NO_INITIAL_GUESS`，而同一网格上其余点全程 `CONVERGED`——即丢轨是**逐点**的，不传染。

### 2.5 全军覆没的帧不得晋升为参考

`INCREMENTAL` 的触发条件是"全场 ZNCC 中位数低于阈值"，而中位数在没有收敛点时是 NaN。若把 NaN 直接当作"低于阈值"，一帧完全去相关（遮挡、闪光、掉帧写坏）就会被扶正成参考，然后**整场丢轨**。因此晋升多一个前提：该帧至少有一个点收敛。测试 `test_a_frame_where_nothing_converged_is_not_promoted_to_reference` 用一张纯灰帧插进序列中间验证：该帧 `valid_fraction == 0`、`zncc_median` 为 NaN、不晋升，其后的帧仍然对第 0 帧相关。

### 2.6 只有真正的完整格点才折成 `(n_frames, ny, nx)`

`res.field("u")` 返回 `(n_frames, ny, nx)` 是 §1.13 的公开约定，但把任意点列 reshape 成网格会**静默错位**。`lattice_shape()` 因此做严格检查：`unique(x) × unique(y)` 的个数要等于点数，且逐点重建的 meshgrid 要与输入**完全相等**（顺序也要对）。不满足就返回 `None`，`field()` 退回 `(n_frames, n_points)`。测试覆盖了缺一个点、乱序、散点、空点集四种否定情形。

### 2.7 掩码约定与内核一致

`field(name)` 默认把未收敛点置 NaN（与 `ICGNResult.masked()` 同一约定），但 `status` 与 `iterations` **永不掩码**——它们本身就是"为什么没算出来"的信息，写成 NaN 等于把诊断销毁。`field(name, masked=False)` 给原值，并在 docstring 里明说未收敛点的原值无意义。

### 2.8 种子

`SeedMode` 三档对应 §2.7 的优先级 1/3/（无）：`PREV_FRAME`（默认）取上一帧同点的 `p`，**上一帧没收敛的点回退到零**（不传播坏值）；`SOLVER` 交给内核，即 `search_radius > 0` 时走 FFT-CC；`ZERO` 显式全零，用于对照。换参考后种子清空（旧 `p` 属于旧参考，不能跨段用）。

实测收益是有限的：`584 → 608` 总迭代数，−4.0%。**这个数字比预期小，如实写在这里**：本序列每帧只动 0.5 px 量级，零种子本来就在收敛域里；PREV_FRAME 的真正价值在大位移序列，而那种序列在 S1 的验收范围之外，未测。

---

## 3. 应变对接契约（写给 IR1-O2 与 Impl-R2）

本任务与 IR1-O2 并行，写完时 `hl3.strain` 还是个半成品（先是无 `__init__.py` 的命名空间包，随后 `__init__.py` 从自己的子模块 import 了尚不存在的名字，import 即抛 `ImportError`）。**这不是障碍，是需求**：相关计算是全流程里最贵的一段，不能因为下游模块没就绪而丢掉。

交付时 IR1-O2 已定稿，下面的规则原样生效、**未为它写任何适配代码**：`hl3.strain.compute_strain` 被自动选中，网格 payload 直接对上，`StrainField` 数据类被解包成 `exx/exy/eyy` 三个 `(n_frames, ny, nx)` 场。

查找与调用规则（`resolve_strain_backend` + `_strain_one`）：

1. **入口名**按顺序试：`pipeline_strain`、`strain_fields`、`strain_field`、`compute_strain`、`strain_from_displacement`、`local_plane_fit`、`pointwise_least_squares`、`pls_gradients`。名单同时覆盖了 IR1-G2 在 `test_s1_metrology.py` 里期望的名字和 IR1-O2 现有的 `pls.py` 实现，谁先定稿都能接上。
2. **payload**（按关键字传，后端签名里没有的键**自动丢弃**，所以窄签名不算错）：
   `x, y, u, v, u_x, u_y, v_x, v_y, valid, zncc, window, step, step_px, subset_size, subset_px, grid_shape`。
   （`step_px` / `subset_px` 是 `step` / `subset_size` 的别名，因为 IR1-O2 定稿的 `compute_strain` 把这两个做成了**必填关键字**——它拒绝猜空间分辨率，这个选择是对的，流水线配合它多带两个键即可。）
3. **先网格后点列**：POI 是完整格点时，先用 `(ny, nx)` 形状调一次（PLS 的 `L_window × L_window` 邻域拟合天然写在格点上，IR1-O2 的 `pls_gradients(u, v, ...)` 也是这个形状）；抛 `TypeError/ValueError` 时再用一维点列调一次。散点 AOI 只有点列一种。
4. **返回值**接受 `Mapping`、`NamedTuple`、或带 `__dict__` 的对象（如 IR1-O2 的 `GradientField` 数据类）；只取其中的 ndarray 字段，标量属性（`window`、`fit_order`…）忽略。
5. **失败一律降级**：`StrainOutcome(available=False, reason=...)`，`reason` 写明是"模块不可导入"、"没有已知入口"、还是"入口调用失败: <异常类型>: <消息>"。`provenance["strain"]` 同步记录。
6. **`StrainMode.REQUIRED`** 是唯一会把上述任一情况变成 `StrainUnavailableError` 的开关，留给 CI 门禁用。
7. **`Dic2DConfig.strain_backend`** 可直接注入 callable，优先级高于模块查找——IR1-O2 定稿后如果签名和上面的 payload 不完全对得上，一行适配函数即可接上，不需要改流水线。

**本流水线不实现任何应变数学。** 唯一"接近应变"的输出是 `field("u_x"/"u_y"/"v_x"/"v_y")`，那是一阶形函数 `p` 的第 2/3/5/6 个分量原样取出（§2.11 里 `FROM_SHAPE_FUNCTION` 方案的输入），张量构造、邻点筛选、后滤波全部属于 `hl3.strain`。

`L_VSG` 例外：`vsg_size_px()` 实现了 iDICs GPG 式 (7.2) `L_VSG = (L_window−1)·L_step + L_subset`，因为它只依赖 `(subset, step, window)` 三个流水线自己持有的参数，且 §1.7 要求它**始终**显示。与 `hl3.strain.vsg_size_px` 重复一行代数是有意的取舍：让 provenance 在应变模块缺席时仍然完整。两者已交叉核对过一致（`(21, 5, 5) → 41`；IR1-O2 的版本多了后滤波窗口合并参数，本流水线不做后滤波，取不到那一支）。若 Impl-R2 要消除这一行重复，正确做法是流水线转调 `hl3.strain.vsg_size_px`，并接受"应变模块缺席时 `l_vsg_px` 为空"。

---

## 4. 测试矩阵（61 条）

| 组 | 条数 | 内容 |
|---|---:|---|
| 纯代数 | 8 | GPG 式 (7.2) 100 组组合、`compose_total` 对矩阵乘积、零累积逐位恒等、形状校验、`lattice_shape` 四种否定 |
| MockCapture 端到端 | 6 | 整像素真值 `(u,v)=(2i,i)` 全点收敛；参考帧真跑；相机元数据/时间戳；掉帧后源编号不重排；进度回调；两次运行逐位相同 |
| 亚像素精度 | 3 | 傅里叶位移带限散斑序列；`correlate_pair` 与两帧序列一致；PREV_FRAME 与 ZERO 两种种子结果一致且迭代数不增 |
| 场与掩码 | 4 | `(n_frames, ny, nx)` 形状与 dtype；越界点 NaN + `OUT_OF_BOUNDS`；未知场名报错；形函数梯度输出 |
| 参考更新 | 6 | EVERY_N 的更新序列与总位移真值；INCREMENTAL 由 ZNCC 触发（加噪）；丢轨点不再锚定；零收敛帧不晋升；非 FIXED 强制 `reference_index == 0`；FIXED 下参考帧可在序列中间（负位移真值） |
| 输入契约 | 14 | 图像栈/列表/捕获源；尺寸不一致、非二维、空序列、参考越界、点集畸形、配置越界（6 组参数化）、类型错误、容器类型错误 |
| provenance | 1 | 求解器名、subset/step/search_radius、`l_vsg_px`、网格形状、有效率、strain 子字典 |
| 应变对接 | 20 | 已合并模块的端到端链路（刚体平移下应变为零，模块未定稿时 skip）／模块缺席／import 抛错／无已知入口／入口顺序／注入覆盖／签名裁剪／`**kwargs` 全量／网格优先／点列回退／后端抛错降级／REQUIRED 抛错 ×2／返回值不可识别／对象返回解包／未知场名 ×2／OFF 不查找／降级后取场报错／对真实 `hl3.strain` 的两分支自适应断言 |

最后一条值得单独说：`test_the_real_strain_module_is_used_when_it_is_importable` 不假设 `hl3.strain` 存在与否，而是断言**流水线的自述必须诚实**——不可用时 `frames == ()`，可用时 `backend == 已解析的名字` 且帧数对得上，"存在但调不通"时 `reason` 里必须出现该入口名。这样 IR1-O2 无论何时定稿，这条测试都不需要改，也不会变成一条永远为真的空断言。

---

## 5. 明确未做

| 项 | 状态 | 归属 |
|---|---|---|
| 应变张量、PLS、VSG 研究 | 未做（只做可选对接） | IR1-O2 / `hl3.strain` |
| 二阶形函数入口 | 未做；流水线固定调 `icgn_first_order` | IR1-O1 定稿后接入是改一行调度 |
| AOI（多边形/布尔/逐帧掩膜） | 未做；只支持 `make_grid` 或用户直接给点列 | S2+ |
| RG / HYBRID 计算路径、SIFT 初值 | 未做；只有 PATH_INDEPENDENT | §2.8，S2+ |
| 多线程 / GPU / 可中断续跑 / 实时预览 | 未做，单线程纯 NumPy | §1.5、§1.15，S5/S6（用户已明确不做） |
| HDF5 增量写、CLI、报告 | 未做；`provenance` 是 dict，没有落盘 | `hl3.io` / Impl-R3 |
| 非 FIXED 模式下 `reference_index > 0` | **主动拒绝**（构造期 `ValueError`） | 向前累积走不到参考帧之前的帧；反向合成是另一个问题，规格未定义，不猜 |
| 大位移序列上的种子收益 | 未测 | 现有实测只覆盖 ≤2.5 px 位移 |
| 吞吐优化 | 未做 | 770 POI-solves/s 是"能跑"的数字，不是性能承诺 |

---

## 6. 与 R1-O1 规格的对应

| 规格条款 | 本实现 |
|---|---|
| §1.0 状态机 | 未实现完整状态机；`Dic2DRun` 是一次运行的不可变结果，`provenance` 承担 `EXPORTED` 之前的快照职责 |
| §1.5 运行配置 | `initial_guess` → `SeedMode`；`reference` → `ReferenceMode`；`path` 固定 PATH_INDEPENDENT；`deterministic` 恒为 true（单线程，`provenance["deterministic"]`） |
| §1.5 失败点诊断 | 直接复用内核的 `Status`，逐帧 `status_counts()`，外加流水线自己的 `NO_INITIAL_GUESS`（丢轨） |
| §1.7 VSG | `vsg_size_px()` 实现式 (7.2)，`provenance["l_vsg_px"]` 始终填写 |
| §1.13 Python API | `res.field("u")` → `(n_frames, ny, nx)`，NaN 为无效，与规格示例同形 |
| §2.7 初值优先级 | 实现优先级 1（PREV_FRAME）与 3（FFT-CC，转调内核）；2/4 未实现 |
| §2.9 参考更新 | 三种模式全实现；累积用链式法则；不做位移场插值（见 §2.3 的理由） |
| §2.11 应变 | 不实现，转调 `hl3.strain` |
| §5.16 确定性 | 单线程纯 NumPy，同输入逐位可复现，有测试 |

---

## 7. 共享检出事故记录

与 R3-O3 记录过的同类问题：本轮十个代理共用同一个工作树。本任务提交期间，兄弟代理把工作树切到了它自己的分支（`cursor/ir1-o2-strain-068c`），我的两个提交因此落在了那条分支上；同时集成分支 `cursor/dic-sota-plan-259d` 的远端已经前进。处置：**不动别人的 HEAD**，用 `git branch -f cursor/ir1-o3-pipeline-e17b <我的提交>` 建自己的分支 ref 并推送，再把同一提交快进推到 `cursor/dic-sota-plan-259d`（`3fa436f..a5ae3a4`，只含本任务两个提交，不夹带任何在写文件）。全程只 `git add` 独占路径，未使用 `git add .`，未 stage 兄弟代理的未跟踪文件（`src/hl3/strain/`、`tests/test_strain.py`、`tests/test_icgn_second.py`）。

另：本实现写作期间，`hl3.strain` 依次经历了「无 `__init__.py` 的命名空间包」→「`__init__.py` 从自己的子模块 import 不存在的名字，import 即抛错」→「定稿」三种状态，全仓测试也一度因此有 1 条失败（`tests/test_s1_metrology.py::test_uniform_strain_smoke`，非本任务文件，未改动）。流水线对前两种状态的反应都是**降级而非失败**，各有用例锁定（`test_missing_strain_module_downgrades_the_run`、`test_a_module_that_explodes_on_import_downgrades`）；定稿后链路自动接通，由 `test_the_merged_strain_module_closes_the_chain` 锁定。交付时全仓 `460 passed`。

---

## 8. 法律与依赖

- 新增文件均带 `SPDX-License-Identifier: Apache-2.0`。
- 依赖只有 NumPy；无新增第三方依赖，无 GPU/CUDA 代码路径，无相机 SDK。
- 无 VIC 逆向：本模块的接口取自 R1-O1 规格与 iDICs GPG 的公开条款（§1.5/§1.7/§1.13/§2.7/§2.9/式 (7.2)），实现为独立编写。
- `MockCapture` 保证测试不枚举、不打开任何真实相机（`tests/test_env_guards.py` 的 CPU-only 边界不受影响）。
