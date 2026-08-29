ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# R3-O2 · 立体模块加固（`src/hl3/stereo/` + `tests/test_stereo_synth.py`）

- **子代理**：R3-O2（opus-fast），Round 3，4/3/3 编制
- **独占路径**：`src/hl3/stereo/**`、`tests/test_stereo_*.py`、`round3/R3-O2-stereo-harden.md`
- **分支**：`cursor/r3-o2-stereo-harden-1747`（基于 `origin/cursor/dic-sota-plan-259d` @ `8cc4db6`）
- **上游**：`round2/R2-O2-stereo-impl.md`（本人 Round 2 产出）、`round1/R1-O2-hl3-3d-spec.md`、`round2/R2-F4-r3-gates.md`
- **法律基线**：遵循 `.agent_workspace/LEGAL.md`。本轮**未新增任何算法**，只做输入校验、失效语义与测试。**显微镜非参数畸变（规格 §4.1 L6）零实现代码**，见 §6。

---

## 0. 一句话结论

Round 2 的立体原型在**干净、完整、良态**的输入上是正确的（本轮逐位复现了 R2-O2 附录 A 的全部数字），但它**默认输入永远干净**——而这个假设在真实 DIC 数据上第一帧就不成立：**任何一个未匹配的 POI（`nan` 像素）会让 DLT / Sampson / 非线性三条三角化路径对整场抛 `LinAlgError: SVD did not converge`**。本轮修掉这一类"缺失数据"缺陷 5 项、"退化几何被静默伪装成正常结果"缺陷 6 项、"错误调用静默产出垃圾"缺陷 14 项，测试从 32 个扩到 71 个（新增 39 个，其中 **22 个在加固前的代码上失败**）。全部计量数字不变。

---

## 1. 交付物

| 文件 | 行数（前 → 后） | 内容 |
|---|---|---|
| `src/hl3/stereo/triangulate.py` | 474 → 867 | 输入校验层、缺失数据传播、退化几何上报、`position_sigma` / `triangulation_quality_mask` |
| `src/hl3/stereo/calibrate.py` | 1098 → 1280 | `Camera`/`StereoRig` 构造校验、几何生成器与误差度量的前置条件、质量门限收口 |
| `src/hl3/stereo/__init__.py` | 90 → 94 | 汇出两个新 API |
| `tests/test_stereo_synth.py` | 544 → 1178 | 32 → **71 个测试**，2.7 s 全绿 |

提交（3 个，逐条独立）：

```
d5368b8  harden(stereo): validate inputs, survive dropped POIs, report degenerate geometry
e5ba000  harden(stereo): never reinterpret a wrong-width array as points or pixels
a722f91  test(stereo): cover dropped points, degenerate geometry and input contracts
```

复现：

```bash
python3 -m pytest tests/test_stereo_synth.py -q          # 71 passed, 2.7 s
python3 -m pytest -q                                     # 全仓 126 passed, 8.1 s
PYTHONPATH=src python3 -W error::RuntimeWarning -c "from hl3.stereo.calibrate import main; main()"   # 27 s，零警告
ruff check --select E,F,I,UP,B,SIM,RUF --ignore SIM300 --target-version py310 src/hl3/stereo/ tests/test_stereo_synth.py
```

---

## 2. 失效语义：本轮确立的三条规则

加固前，模块对"坏输入"只有一种反应：能算就算，算不出来就崩。本轮把它拆成三类，**这个区分本身是主要交付物**，代码与文档都按它组织：

| 类别 | 规则 | 理由 |
|---|---|---|
| **调用方写错了** | 抛 `ValueError`/`TypeError`，消息里带上出错的值 | 形状错、视图数不匹配、相机参数非有限、噪声 σ ≤ 0、退化相机配置——这些**测量产生不出来，只能是上游 bug**，大声失败最便宜 |
| **测量缺失** | 传播为 `nan`，且**只影响该点** | 非有限像素坐标是相关器报告"这个点没匹配上"的方式，任何真实位移场都有。它必须活到输出，而不是毒化邻居或中止整批 |
| **几何退化** | 上报（协方差 `inf`），不隐藏 | 近平行射线定位不了的点，要给无穷大协方差，而不是一个看着像模像样的有限数——否则质量门限会信它 |

`triangulate.py` 模块 docstring 里写死了这三条，后续任何新函数都必须归到其中一类。

---

## 3. 缺陷清单（全部实测复现，非推测）

### 3.1 缺失数据类（最严重）

| # | 缺陷 | 加固前实测行为 | 加固后 |
|---|---|---|---|
| D-1 | **一个 `nan` 像素杀死整场** | `triangulate_dlt` / `triangulate_optimal` / `triangulate_nonlinear` 抛 `LinAlgError: SVD did not converge`，25 个点里坏 1 个，**25 个全丢** | 该点 `nan`，其余点与无缺失时**逐位相同** |
| D-2 | Hartley 归一化被 `nan` 污染 | `_normalizer_2d` 对全视图取均值，一个 `nan` 让 `T` 全 `nan`，即使不走 SVD 也全场报废 | 归一化只在已观测点上计算 |
| D-3 | `reconstruction_error` 整体塌成 `nan` | 一个坏点 → 整张误差报表全 `nan` | 在有限点上统计，并新增 `n_points` / `n_finite` 两个字段 |
| D-4 | `reprojection_rmse` 同上 | 一个坏点 → `nan` | 忽略缺失点；全缺失才返回 `nan` |
| D-5 | 空输入 `N=0` | `RuntimeWarning: Mean of empty slice` + 后续未定义 | 返回 `(0, 3)` / `(0, 3, 3)` / `(0,)`，无警告 |

D-1/D-2 的根因是同一个：**所有点被塞进一次批量 SVD / 批量 3×3 solve，而 NumPy 的批量算子对整批负责**。修法是所有共享线性代数的估计器先按 `_observed_mask` 收缩，算完再散回。

D-3 的 `n_points` / `n_finite` 是刻意成对给的：只报"存活点的 RMS"会让**丢掉难点**成为免费的降误差手段，覆盖率必须跟误差一起走。

### 3.2 退化几何被伪装成正常结果

| # | 缺陷 | 加固前实测行为 | 加固后 |
|---|---|---|---|
| D-6 | `triangulation_covariance` 对整批抛 `LinAlgError: Singular matrix` | 一个秩亏点炸掉整批——而这**恰恰是唯一能挡住远场退化的量**（R2-O2 §3.10） | 逐点：秩亏 → `inf`，输入非有限 → `nan`，其余正常 |
| D-7 | 极线度量对退化线**返回 0（满分）** | `np.maximum(den, TINY)` 把 `0/0` 变成 `0.0`，即"这个匹配完美" | `nan`（未定义），绝不返回 0 |
| D-8 | 重合光心的 `F` 是**归一化后的舍入误差** | `fundamental_from_projections(P, P)` 返回单位范数矩阵，看不出异常（`‖e₂‖/scale = 5.2e-17`，正常机位为 3.7e-3，相差 14 个数量级） | 抛错 |
| D-9 | `decompose_projection` 对奇异 `M` 静默返回 `nan` | 只有一条 `RuntimeWarning` | 抛错 |
| D-10 | `cheirality_mask([])` **全部放行** | 安全门限在没有相机可比对时 fail-open | 抛错（fail-closed） |
| D-11 | `project` 在主平面上除以次正规数 | 有限的垃圾坐标 | 深度恰为 0 → `nan`；近零深度仍给（数学正确的）巨大有限值，由协方差门限负责拒绝 |

D-6 值得单独说：R2-O2 §3.10 的结论是"协方差是唯一能挡住非线性 GN 无穷远极小值的量"，而这个量的实现是**整批一起崩**的。也就是说 Round 2 那条最有产品价值的发现，建立在一个自己就不健壮的门限上。现在它逐点降级。

D-7 同理：Sampson 距离是规格 §4.3 指定的 POI 级质量场，它的**全部职责就是标出坏匹配**，而它在退化处返回满分。

### 3.3 错误调用静默产出垃圾

以下 14 项加固前**不抛错**或抛出无法解读的 NumPy 内部错误，现已全部带值报错（`test_every_guarded_entry_point_raises_with_a_useful_message` 一次扫过 43 个入口）：

| 缺陷 | 加固前 |
|---|---|
| `look_at_extrinsics(center == target)` | 静默返回全 `nan` 的 `R, t`（`nx < 1e-12` 判据碰上 `nan` 恒为 False） |
| `Camera(K, R, t)` 的 `R` 是反射 / 非正交 | 接受。反射的 `R` 会静默翻转 cheirality 与深度轴符号，表现为很久之后的"里外翻转重建" |
| `visible_mask` 遇到未设传感器尺寸的相机 | 返回**全 False**，与"几何全错、什么都看不见"无法区分 |
| `intrinsics(pixel_pitch_mm < 0)` | 返回负焦距 |
| `add_pixel_noise(sigma_px < 0)` | 静默当作 0，噪声扫描退化成一排重复的无噪声结果 |
| `synth_complex_surface(n_side=1)` | 返回退化的单点面 |
| `triangulate_nonlinear(weights=[...])` 长度不符 | `IndexError: list index out of range` |
| `umeyama` 点数不符 / < 3 点 / 含 `nan` | `matmul` 核心维度错误等 NumPy 内部消息 |
| `triangulation_covariance(sigma_px=0)` | `ZeroDivisionError` |
| `_ray_directions` 遇到奇异 `M` | 裸 `LinAlgError` |
| `X0` / `X` 与观测点数不符 | 广播错误 |
| 宽度不对的二维数组被**重新解释** | `(N, 2)` 像素数组传给需要 `(N, 3)` 的入口时，只要 `2N` 是 3 的倍数就静默 reshape。**参数写反会得到一个像模像样的答案** |
| `epipolar_distance` / `sampson_distance` 两侧点数不符 | 广播错误 |
| `StereoRig.stereo_angle_deg` 相机光心在原点 | `nan`（角度的顶点就在那里） |

---

## 4. 行为不变性（回归证据）

加固**不改变任何计量结果**。完整合成研究（`calibrate.main()`，种子 20260828，27 s）逐项对照 R2-O2 附录 A：

| 量 | R2-O2 附录 A | 本轮 | |
|---|---|---|---|
| 无噪声非线性 3D RMS | 3.311×10⁻¹¹ µm | 3.310592134289438×10⁻¹¹ µm | ✓ |
| σ=0.02 px 非线性 RMS | 4.897 µm | 4.897097935230754 µm | ✓ |
| σ=0.02 协方差/MC 比值 | 0.9941 | 0.9940536243540429 | ✓ |
| 误差预算 combined RMS | 4.911 µm | 4.910798394600965 µm | ✓ |
| 退化实验非线性拒绝点数 | 3/100860 | 3/100860 | ✓ |
| 门限后 RMS | 491.6 µm | 491.588692186979 µm | ✓ |
| 噪声标定基线误差 | 2.445 µm | 2.445002051103984 µm | ✓ |

且该运行在 `-W error::RuntimeWarning` 下通过——加固前它会触发若干 `invalid value encountered in divide`。

---

## 5. 测试

`tests/test_stereo_synth.py`：**32 → 71 个，2.70 s 全绿**（Python 3.12.3、numpy 2.4.4、4 vCPU 无 GPU）。全仓 126 个全绿。lint（`E,F,I,UP,B,SIM,RUF`，除 `SIM300`）全绿。

### 5.1 反向验证：新测试确实抓得住旧缺陷

把 `src/hl3/stereo/` 换回 `8cc4db6` 的旧版本（并补一个兼容 shim 提供两个新 API，让测试能收集），**71 个里 22 个失败**：

```
test_a_dropped_point_does_not_destroy_the_rest_of_the_field[dlt / dlt_unnormalised / sampson / nonlinear]
test_a_fully_dropped_field_returns_all_nan[dlt / dlt_unnormalised / sampson / nonlinear]
test_empty_input_returns_an_empty_result[nonlinear]
test_reconstruction_error_reports_coverage_alongside_the_error
test_reprojection_rmse_ignores_dropped_points
test_covariance_is_infinite_where_the_geometry_cannot_locate_the_point
test_position_sigma_is_the_root_of_the_covariance_trace
test_coincident_cameras_have_no_epipolar_geometry
test_epipolar_metrics_report_nan_rather_than_a_perfect_score
test_projection_is_nan_on_the_principal_plane
test_cheirality_gate_fails_closed_with_no_cameras
test_sampson_correction_is_idempotent_once_converged
test_view_weights_pull_the_solution_towards_the_trusted_camera
test_every_guarded_entry_point_raises_with_a_useful_message
test_the_public_api_never_emits_a_runtime_warning
test_triangulate_multiview_rejects_bad_input
```

这条是刻意做的：**"测试数量翻倍"本身不是证据**，只有在旧代码上会红的测试才是回归测试。剩下 17 个新测试是对此前完全无覆盖代码的首次覆盖（见 5.2），不是重复断言现状。

### 5.2 新增覆盖（此前为零）

- **`run_synthetic_experiment` 端到端驱动**：Round 2 交付了 1000 行实验驱动，**一个测试都没有**。现在有 3 个（结果树完整性、定种子逐位可复现、换种子只动噪声不动几何），用缩减配置跑 0.4 s。
- **`triangulate_nonlinear(weights=...)`**：规格 §9 多系统重叠区的接口，此前未测。现在验证高权重视图确实把解拉过去（该视图残差降到 1/5 以下）+ 权重校验。
- **代数不变性**（与本合成机位无关，因此能抓住固定几何回归测试抓不住的坐标系约定错误）：
  - 刚体世界变换下的**等变性**——同时移动世界与相机，像素不变，重建结果必须跟着变；一次性穿过光心、射线方向、DLT 归一化、GN 全链。
  - `P → αP` 的**射影缩放不变性**（含 α<0）。
  - Sampson 修正的**幂等性**、`iters=0` 为恒等、提前退出不改变结果。
- **警告卫生**：一整批含 `nan`、全 `nan`、空、远场退化的调用在 `simplefilter("error")` 下必须零警告。数值库里的 `RuntimeWarning` 是潜伏的静默错误——响一次、被过滤掉、调用方拿着被污染的数组继续跑。
- **API 面**：`__all__` 与命名空间不得漂移、必须有序。

### 5.3 分组一览（71 个）

| 组 | 数量 |
|---|---|
| 相机模型 / 三角化 / 极线 / 噪声与不确定度 / 位姿代数 / 标定 / 可复现（Round 2 原有） | 32 |
| 缺失数据（丢点传播、全丢、空输入、覆盖率、协方差与门限） | 20 |
| 退化几何（秩亏协方差、远场门限、重合光心、平行射线、主平面、退化极线、fail-closed） | 8 |
| 代数不变性与权重 | 7 |
| 输入契约（1 个测试扫 43 个入口）+ 警告卫生 | 2 |
| 范围边界（L-7）+ API 面 | 2 |
| 端到端驱动 | 3 |

---

## 6. 范围边界：显微镜畸变**零实现**（规格 §10.4 / 门 L-7）

本轮**未新增任何畸变代码**，与 Round 2 一致：无 Brown–Conrady（L1）、无有理（L2）、无薄棱镜/倾斜传感器（L3）、无鱼眼（L4）、无远心（L5）、**无显微镜非参数畸变场（L6）**。仍是纯 L0 针孔。

新增 `test_stereo_package_ships_no_distortion_implementation`，把 L-7 从"评审时人工 grep"变成 **CI 里可执行的门**：

1. 扫描 `src/hl3/stereo/*.py` 中匹配 `distort|brown|conrady|radial|tangential|prism|fisheye|telecentric|microscop` 的**函数/类定义**（不是提及）——命中即失败；
2. 同时**要求**每个模块 docstring 里保留 `patent-clearance` 字样——**删掉免责声明不能成为让测试通过的手段**；
3. 断言 `hl3.stereo.__all__` 不含相关名字。

实测：定义命中 0 条。

### 6.1 交给 R3-G1 的白名单登记项

R2-F4 §2.1 的 L-7 扫描命令是 `rg -i -n '(microscop|...)' src/ tests/`，其 FAIL 判据是"存在显微镜畸变**实现**代码"，但按 L-2 的规则，未登记的命中一律 FAIL。以下命中**全部是范围排除声明或执行该排除的测试**，请 R3-G1 登记进 `legal/scan-allowlist.txt`（该文件不在我的独占路径内，我未创建）：

| 路径:行 | 内容性质 | 理由 |
|---|---|---|
| `src/hl3/stereo/triangulate.py:28` | 模块 docstring | 声明 L6 层"stays out of every branch until the written patent-clearance opinion exists"，紧邻一句 "This paragraph is a scope exclusion, not a description of anything present in this file." |
| `src/hl3/stereo/calibrate.py:36` | 模块 docstring | 同上，"What this module is *not*" 小节 |
| `src/hl3/stereo/__init__.py:7` | 包 docstring | 同上 |
| `tests/test_stereo_synth.py:1065,1079,1094` | 测试 | 执行 L-7 的扫描器自身（正则与禁用名单） |

另有一条**不在我独占路径内**、需 R3-G1 或 R2-O3 处理：`src/hl3/io/hdf5_schema.py:298,310` 出现 `"stereo_microscope"`（schema 枚举值，非实现代码）。

`legal/scan-allowlist.txt` 目前在仓库中不存在——按 R2-F4 §2.2 的 fail-closed 规则，白名单缺失时所有命中都算 FAIL，所以这个文件本身是 Round 3 的一个硬缺口。

---

## 7. 未做 / 仍是欠账

本轮只做加固，**R2-O2 §5 的全部范围边界原封不动**，逐条重申以免被误读为已完成：

1. **无任何镜头畸变**（L1–L5），因此规格 §6.2/§6.3"在原始畸变图像上匹配 + 极曲线采样"这条核心架构决策**仍未验证**。
2. **不是 Zhang 平面标定**。`resection_dlt` 消费的仍是世界坐标已知的非共面 3D 靶点。Zhang 法（逐板单应 → 绝对二次曲线的像 → LM 联合优化）**完全没有**，这仍是最大的一块欠账。
3. **无棋盘/ChArUco 角点检测**，合成实验仍直接注入像素级噪声。
4. **无标定协方差 `Σ_cal`**。§3.4 的协方差只含匹配项，仍是"相机参数精确已知"下的**下界**。规格 §6.6 的完整传播链只落地了前两块。
5. **无 §6.4 四路闭环残差**（依赖 R3-O1 的 2D 内核对接）、**无 PIB 估计/补偿**、**无应变**、**无多系统位姿图**、**无 HDF5 落盘**。
6. **未下载 Challenge 数据集**，所有数字来自自建合成台架。
7. **R2-O2 §3.9 那条反直觉说明依然成立且依然重要**：本原型测出"标定项只有匹配项的 1/16"，与 Challenge 1.0"五家码差别主要来自标定"不矛盾但**不能用来反驳它**——因为本原型是纯针孔、真值与模型同族，而 Challenge 里标定主导的主因是**未校正的镜头畸变**（模型失配），不是检出噪声（随机误差）。要在合成台架上复现"标定主导"，必须先把畸变加进渲染与模型并**故意让模型阶数低于真值阶数**。在此之前，任何"我们的标定更好"的说法都没有合成证据支撑。

### 7.1 本轮加固暴露出的、建议进 Round 4 的问题

- **`Σ_X` 目前只有匹配项，但质量门限已经在用它**。`triangulation_quality_mask` 的 `max_position_sigma_mm` 阈值现在建立在一个已知偏小的协方差上，也就是**门限偏松**。接上 `Σ_cal` 之前，这个阈值不能对外当作标定过的判据。
- **`nan` 语义需要与 R3-O1 的 2D 内核对齐**。我这边确定了"未匹配 = 非有限像素"，相关器侧如果用 mask 数组或哨兵值表达同一件事，两边接口会打架。这是 §6.4 四路闭环残差落地前必须先谈的。
- **`triangulate_nonlinear` 的收敛判据仍是逐点步长**，没有把不收敛的点标出来。目前不收敛的点会安静地返回最后一次迭代的位置。加一个收敛标志位是下一步。

---

## 8. 协作事件记录（与 R2-O2 §8 同类，仍未解决）

Round 2 报告里记过一次"共享工作目录被兄弟代理 `git add` 扫走半成品"。**本轮同一问题再次发生，且更严重**：

1. 我在 `/workspace` 用 `git checkout -b` 创建分支后，共享检出目录就切到了我的分支上；
2. 我编辑立体模块期间，兄弟代理（R3-F3）在该目录 `git commit`，于是 **R3-F3 的提交落到了我的分支上**；
3. 同时 `git status` 显示 R3-F2 / R3-F4 / R3-G2 的产出已被暂存在共享索引里——我若直接 `git commit` 就会把它们一并卷进我的分支。

处置：

- 把 `/workspace` 切回 `cursor/dic-sota-plan-259d`（切换前后同一 commit，兄弟代理的暂存与工作区改动完好无损），并从共享索引里撤出我自己的文件；
- 用 `git branch -f` 把我的分支重建到 `origin/cursor/dic-sota-plan-259d`（该分支已包含 R3-F3 正式推送的成果），丢弃误落的那次提交；
- 改用独立 `git worktree`（`/tmp/r3o2-wt`）完成后续全部编辑、测试与提交，**全程未再触碰共享检出目录**。

我的三次提交只含 4 个文件：`src/hl3/stereo/` 三个 + `tests/test_stereo_synth.py`（本报告为第 5 个）。未改 `pyproject.toml`、CI 配置、`README.md`、`docs/`、`src/hl3/correlate/`、`src/hl3/io/` 或任何其他代理的产物。

**给父调度器的建议（Round 2 提过一次，本轮加强）**：派工单里的"`git add` 不要用 `.`"不够——问题不在 `git add` 的参数，而在**多个代理共享一个工作树时，分支状态本身是全局可变量**。应改为硬性要求：**每个实现代理开工第一步就 `git worktree add`，绝不在共享检出目录里切分支或提交**。

---

## 附录 A · 加固前后行为对照（可复现的探针输出）

加固前（`8cc4db6`）：

```
dlt normalize=True, 1 NaN POI     LinAlgError: SVD did not converge
dlt normalize=False, 1 NaN POI    LinAlgError: SVD did not converge
midpoint, 1 NaN POI               OK  nan_rows=1/25
nonlinear, 1 NaN POI              LinAlgError: SVD did not converge
optimal, 1 NaN POI                LinAlgError: SVD did not converge
covariance singular (1 view dup)  LinAlgError: Singular matrix
covariance sigma=0                ZeroDivisionError: float division by zero
empty N=0 dlt                     RuntimeWarning: Mean of empty slice
look_at center==target            RuntimeWarning: invalid value encountered in divide
F coincident centres              OK  (返回单位范数矩阵)
cheirality no views               OK  [True True True]
visible_mask zero-size sensor     OK  [False]
decompose singular M              RuntimeWarning: invalid value encountered in divide
intrinsics negative pitch         OK  (焦距 -10144.93)
add_pixel_noise negative sigma    OK  (静默无噪声)
synth_complex_surface n_side=1    OK  (单点)
umeyama 1 point                   ValueError: setting an array element with a sequence...
nonlinear weights too few         IndexError: list index out of range
```

加固后：

```
dlt / dlt(unnorm) / midpoint / nonlinear / optimal, 1 NaN POI   OK  nan_rows=1/25（其余点逐位不变）
covariance 1-view rank deficient   position_sigma 全为 inf，批次不崩
covariance sigma=0                 ValueError: sigma_px must be finite and strictly positive
empty N=0（全部入口）              OK  (0,3) / (0,3,3) / (0,)，零警告
look_at center==target             ValueError: 'center' and 'target' coincide, so there is no optical axis
F coincident centres               ValueError: degenerate stereo pair: the two camera centres coincide...
cheirality no views                ValueError: Ps must contain at least one view
visible_mask zero-size sensor      ValueError: camera has no sensor extent (width/height are unset)...
decompose singular M               ValueError: cannot decompose a projection matrix whose leading 3x3 block is singular...
intrinsics negative pitch          ValueError: pixel_pitch_mm must be positive, got -0.00345
add_pixel_noise negative sigma     ValueError: sigma_px must be non-negative, got -1.0
synth_complex_surface n_side=1     ValueError: n_side must be >= 2, got 1
umeyama 1 point                    ValueError: umeyama needs at least 3 point pairs, got 1
nonlinear weights too few          ValueError: weights must supply one value per view, got 1 for 2 views
远场退化点 + 门限                   被 max_position_sigma_mm 拒绝；不设该上限时通过（证明协方差项不可替代）
```

---

*R3-O2 完。本文件与三次提交只覆盖 `src/hl3/stereo/**`、`tests/test_stereo_synth.py`、`round3/R3-O2-stereo-harden.md`。*
