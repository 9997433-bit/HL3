ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# IR1-O2 · 应变引擎（PLS / 张量族 / VSG）实现与实测

- **子代理**：IR1-O2（opus-fast），Impl-R1（S1 收口轮），4/3/3 编制
- **独占路径**：`src/hl3/strain/**`、`tests/test_strain.py`、本文件。**未触碰** `src/hl3/correlate/icgn.py`（IR1-O1 独占）、`src/hl3/pipeline/**`（IR1-O3）、`src/hl3/io/**`（IR1-F4 面）；`src/hl3/__init__.py` 保持原样未改。
- **上游效力顺位**（RUL-08）：`LEGAL.md` → Gate（IR1-F1 G-S1-STR-1）→ 内核规格 R1-O1 §1.6/§1.7/§2.11 → 调用面 IR1-F3 §4/§6 → schema IR1-F4 + `hl3.io.hdf5_schema`。
- **分支**：`cursor/ir1-o2-strain-068c`
- **依赖**：仅 numpy（双精度）+ `hl3.io.hdf5_schema` 的零依赖常量层（`vsg_size_px`、`STRAIN_TENSORS`、`STRAIN_METHODS`）。不需要 h5py。

---

## 0. 一句话结论

应变层已跑通并可测：**均匀变形四种张量的最大误差 1.1×10⁻¹⁵**（舍入级）；**刚体转动（1°–45°）的 Green-Lagrange / Hencky / Euler-Almansi 应变最大值 ≤ 6.3×10⁻¹⁴**，比规格 §5.3 的 `5e-5` 判据宽出十一个数量级，同时工程应变**精确等于 `cos θ − 1`**（2° 时 −609 µε，如实记录而非掩盖）；`σ_u = 0.01 px`、`step = 5 px` 下的应变噪声底板为 **828 / 286 / 87 / 32 µε（W = 3 / 5 / 9 / 15）**，与解析预测 `σ_u /(step·√Σdx²)` 吻合到 1.5% 以内；30 000 个 POI 的全场应变 **25 ms**，且**几乎与窗口大小无关**（W=5→15 只从 25 ms 涨到 30 ms），六档 VSG 扫描 216 ms —— 规格 §1.6 "改 strain_window 不重跑相关、秒级出结果" 与 §1.3 步骤 5 的 VSG 研究自动化在数值层已经成立。`tests/test_strain.py` 120 项全绿；顺带修好了此前失败的 IR1-G2 门测 `test_s1_metrology.py::test_uniform_strain_smoke`。

---

## 1. 交付物

| 文件 | 行数 | 内容 |
|---|---|---|
| `src/hl3/strain/pls.py` | 378 | 切窗加权 PLS 位移梯度（一阶/二阶、uniform/gaussian、邻点与秩判据） |
| `src/hl3/strain/tensors.py` | 327 | `F`、工程/Green-Lagrange/Euler-Almansi/Hencky、主应变、von Mises、Tresca、面积变化率、极分解转角 |
| `src/hl3/strain/vsg.py` | 175 | GPG 式 (7.2) 口径（委托 `hdf5_schema.vsg_size_px`）、后滤波窗、mm 换算、反解 |
| `src/hl3/strain/field.py` | 482 | `StrainParams` / `StrainField`（IR1-F3 冻结布局）、`compute_strain`、POI 列表→网格适配器 |
| `src/hl3/strain/__init__.py` | 112 | 公开 API 汇出 |
| `tests/test_strain.py` | 933 | 120 项闭式合成测试 |

复现方式（无需安装）：

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_strain.py          # 120 passed, 0.5 s
PYTHONPATH=src python3 -m pytest -q tests src/tests               # 459 passed, 19 s（全仓）
python3 -m ruff check src/hl3/strain                              # 0 error
```

最小用例：

```python
from hl3.strain import StrainParams, compute_strain

strain = compute_strain(u_grid, v_grid, StrainParams(window_pts=5),
                        step_px=5, subset_px=21, valid=(status == Status.CONVERGED))
exx_map = strain.as_grid("exx")        # (ny, nx) 云图；数组本体是 (P,) 扁平点序
assert strain.vsg_px == 41.0           # (5-1)*5 + 21
```

---

## 2. 实现要点

### 2.1 PLS 的全场向量化（本实现的主要工程内容）

规格 §2.11 步骤 1 是逐点最小二乘，朴素写法是"对每个 POI 取窗、组法方程、解 3×3"，Python 层循环三万次不可接受。这里改写为：**每个法方程元素都是一次可分离二维相关**。

- Gram 元素 `G[i,j] = Σ_窗 w·dx^(a_i+a_j)·dy^(b_i+b_j)·m`，是**有效性掩膜** `m` 与核 `w(dx)dx^a ⊗ w(dy)dy^b` 的相关；
- 右端 `rhs[i] = Σ_窗 w·dx^a dy^b·(m·u)`，是**掩膜后位移**与同一族核的相关。

于是全场只需十来次一维相关（`sliding_window_view` + `tensordot`，零填充）加一次批量 3×3（二阶 6×6）求解。三个后果值得记账：

1. **掩膜直接进法方程**，窗内有洞的点是被**精确求解**的，不是近似、不是补零 —— 单点丢失的邻点实测仍精确到 1e-13（测试 `test_a_dropped_point_stays_local_and_does_not_bias_its_neighbours`）；
2. **成本与窗口大小几乎无关**（见 §3.5），这正是 VSG 扫描便宜的原因；
3. 拟合在**索引单位**下做（Δ 以 POI 计），最后除以 `step_px` 得梯度 —— 条件数与 step 无关，二阶项从 O((r·step)⁴) 降到 O(r⁴)。

失败口径与 `hl3.stereo.triangulate` 对齐：调用错误抛 `ValueError`；测量缺失传播为 NaN；秩亏窗（例如只有一行 POI，`u_y` 不可定）由特征值判据判 NaN，**不给一个看起来合理的数**。批量 `eigvalsh` 先筛后解，避免单个奇异矩阵让整场 `solve` 抛异常。

### 2.2 一阶与二阶形函数的真实差别（一条反直觉结论）

在**完整对称窗**上，二阶拟合与一阶拟合给出的梯度**逐位相同** —— 因为多出的基函数 `dx²、dxdy、dy²` 在每个轴上是偶的，而梯度项 `dx、dy` 是奇的，法方程按奇偶分块，互不耦合。二阶的价值只在**窗口不对称**处兑现：网格边界、洞的旁边、掩膜边缘。测试 `test_quadratic_order_pays_off_only_where_the_window_is_truncated` 把这条钉死：抛物型位移场下，内部两者都精确到 1e-15，而在单侧窗的边界列上一阶偏差 > 1e-6、二阶仍精确到 1e-15。

这条对上游有用：规格 §2.11 把 `QUADRATIC` 说成"高梯度用"，更准确的说法是**"高梯度 + 窗口不对称时用"**；纯内部高梯度场靠加窗是换不来精度的，只能换噪声。

### 2.3 张量族与 NaN 纪律

`F = I + ∇u` 之后全部是闭式代数。2×2 对称特征分解**手写闭式**而非调 `np.linalg.eigh`：`eigh` 遇到批内任何一个 NaN 会对**整批**抛异常，而失败 POI 是常态不是异常。`hypot` 而非 `sqrt(a²+b²)`、`atan2` 而非 `atan`（纯剪时分母为零），两处都是为 DIC 实际量级（1e-4）的小应变准备的。

---

## 3. 实测结果

全部数字在 4 vCPU、无 GPU 的 CPU-only 环境上取得，网格 200×150 = 30 000 POI，`step = 5 px`、`subset = 21 px`（`L_VSG = 41 px`）。

### 3.1 均匀变形（`F = [[1.010, 0.004], [−0.002, 0.997]]`）

| 张量 | 最大 \|误差\| |
|---|---|
| engineering | 1.11×10⁻¹⁵ |
| green_lagrange | 1.11×10⁻¹⁵ |
| euler_almansi | 1.11×10⁻¹⁵ |
| hencky | 1.11×10⁻¹⁵ |

平面拟合平面，误差只剩舍入。三种窗口（3/5/9）、两种阶数、两种加权的全组合都一样（测试参数化 12 组）。

### 3.2 刚体转动 —— 规格 §5.3 的硬性不变性

| θ | GL 最大\|E\| | Hencky | Euler-Almansi | 工程 ε_xx（实测） | `cos θ − 1`（理论） | 极分解转角误差 |
|---|---|---|---|---|---|---|
| 1° | 1.1×10⁻¹⁵ | 1.1×10⁻¹⁵ | 1.0×10⁻¹⁵ | −0.000152 | −0.000152 | 4×10⁻¹⁴ ° |
| 5° | 5.7×10⁻¹⁵ | 5.7×10⁻¹⁵ | 5.6×10⁻¹⁵ | −0.003805 | −0.003805 | 3×10⁻¹³ ° |
| 10° | 1.4×10⁻¹⁴ | 1.4×10⁻¹⁴ | 1.1×10⁻¹⁴ | −0.015192 | −0.015192 | 5×10⁻¹³ ° |
| 30° | 1.2×10⁻¹⁴ | 1.3×10⁻¹⁴ | 1.4×10⁻¹⁴ | −0.133975 | −0.133975 | 3×10⁻¹³ ° |
| 45° | 6.3×10⁻¹⁴ | 6.3×10⁻¹⁴ | 6.7×10⁻¹⁴ | −0.292893 | −0.292893 | 2×10⁻¹² ° |

规格 §5.3 的判据是 `max|E| < 5e-5`（端到端预算，其中相关器占绝大部分）；单看应变层，**余量十一个数量级**。工程应变的伪压缩被**逐位断言**而不是容忍：2° 转动伪造 −609 µε，与金属试样弹性段的真实应变同量级 —— 这正是默认张量必须是 Green-Lagrange 的理由，测试把它写成可执行的文档。

### 3.3 应变噪声底板与 VSG（`σ_u = 0.01 px`，纯噪声位移场）

| 窗口 W | `L_VSG` | σ_ε（uniform） | σ_ε（gaussian） | 解析预测（uniform） |
|---|---|---|---|---|
| 3 | 31 px | 828 µε | 908 µε | 816 µε |
| 5 | 41 px | 286 µε | 352 µε | 283 µε |
| 7 | 51 px | 143 µε | 180 µε | 143 µε |
| 9 | 61 px | 87 µε | 109 µε | 86 µε |
| 15 | 91 px | 32 µε | 41 µε | 31 µε |

解析预测取 `σ_ε = σ_u / (step·√Σ_窗 dx²)`，实测与之吻合到 1.5% 以内 —— 说明实现没有引入额外方差，也说明这套数字可以直接进 §1.3 步骤 4 的噪声底板报告。对照：同样的位移噪声**直接差分**（相邻 POI 相减）是 `0.01·√2/5 = 2828 µε`，5 点窗已经把它压掉一个数量级，这就是"必须拟合、不能差分"的量化理由。

**一条对报告口径的重要提醒**：同一 `L_VSG` 下 gaussian 加权的噪声比 uniform **高 23%–27%**。因为高斯权软化了窗口边缘，等效标距小于名义标距 —— 即**名义 `L_VSG` 相同的两套结果，若加权不同则不可直接比较**。GPG 的报告字段只要求 `L_VSG`，所以本实现把 `weighting` 一并记进 `StrainField`。

### 3.4 空间分辨率传递函数（PLS 微分级，`step = 1 px`、`subset = 1 px`，只看窗口的贡献）

| λ / L_VSG | 1 | 2 | 3 | 4 | 6 |
|---|---|---|---|---|---|
| W=5 | 0.338 | 0.793 | 0.904 | 0.945 | 0.975 |
| W=9 | 0.314 | 0.780 | 0.897 | 0.941 | 0.974 |
| W=15 | 0.308 | 0.776 | 0.896 | 0.940 | 0.973 |

三条曲线在 `λ/L_VSG` 坐标下几乎重合（差 < 0.03），**经验上证实 `L_VSG` 就是正确的归一化量** —— 这也是 GPG 把它抬成必填字段的物理依据。工程结论：**要让应变幅值保真到 90%，需要 `λ ≳ 3·L_VSG`**；`λ = 2·L_VSG` 处只剩 0.78。规格 §5.5 的 T5 判据写的是"λ > 2·L_VSG 时 Â/A > 0.9"，但 T5 度量的是**位移**幅值（相关器 subset 平均），本表度量的是**应变微分级**的幅值 —— 两者不是同一个量，不构成冲突，但 T5 落地时若把判据套到应变场上会不通过。已记入 §5 待裁决项。

### 3.5 性能（30 000 POI，单次全场）

| 配置 | 耗时 | 吞吐 |
|---|---|---|
| W=5 一阶 | 25.3 ms | 1.19 MPOI/s |
| W=9 一阶 | 28.1 ms | 1.07 MPOI/s |
| W=15 一阶 | 30.4 ms | 0.99 MPOI/s |
| W=5 二阶 | 70.4 ms | 0.43 MPOI/s |
| 六档窗口 VSG 扫描（3/5/7/9/11/15） | 216 ms | — |

窗口从 5 涨到 15（面积 9 倍）耗时只涨 20%，因为可分离相关的成本是 O(N·L) 而不是 O(N·L²)，且常数极小。**VSG 研究整体 0.2 秒**，规格 §1.6 "从跑一晚上变成点几下" 在这一层已经兑现（真正的 VSG 研究还要 IR1-O3 的 pipeline 把相关结果缓存住，见 §6）。

---

## 4. 契约对齐

### 4.1 IR1-F3 冻结面（§4 `StrainParams`、§6 `StrainField`）

逐条落地，并有测试锁定（`test_strain_params_keep_the_frozen_signature`、`test_strain_field_keeps_the_frozen_layout`、`test_derived_fields_follow_the_frozen_formulas`）：

- `StrainParams` 前四个字段名与顺序 = `window_pts / tensor / weighting / min_valid_fraction`，默认值 `5 / "green_lagrange" / "uniform" / 0.5`；追加字段 `fit_order / sigma / require_center` 一律按 §11.2 规则以**默认值复现冻结行为**的关键字槽位追加。
- **`step_px` 与 `subset_px` 不进 `StrainParams`** —— 它们属于相关器（`Pipeline2DParams.icgn`），改为 `compute_strain` 的必填关键字参数，避免一次分析里存在两份互相矛盾的 step/subset。
- `StrainField` 前八个字段名与顺序 = `exx / eyy / exy / tensor / method / window_pts / vsg_px / grid_shape`，数组是**扁平 (P,) 承 NaN**、行主序 `index = iy*nx + ix`（与 `make_grid` 及 `ICGNResult` 同点序，测试直接比对 `as_grid("exx")[7,11] == exx[7*nx+11]`）。追加 `weighting / vsg_mm / gradients` 三项。
- 派生量 `e1 / e2 / theta_p / gamma_max / von_mises` 按 §6 给定公式逐位实现；`valid == isfinite(exx)`，且三分量 NaN 图样完全一致（`test_the_three_components_share_one_nan_pattern`）。
- **邻点判据**照冻结口径：`valid` 参数即"`status == CONVERGED`"掩膜，`LOW_ZNCC` 点保留位移但不参与拟合。因此本层**不再自设 ZNCC 阈值**（早期草稿里有过，已删除）—— 双重门限只会让报告里的阈值对不上。
- 便利方法 `as_grid(name)`（含 `(P,2,2)` 张量）、`as_schema_dict()`、`schema_attrs()`、`with_window()`（VSG 扫描一步）。

### 4.2 Gate G-S1-STR-1（IR1-F1 B 组）

| 门条 | 状态 | 证据 |
|---|---|---|
| 切窗 PLS 位移梯度 | ✅ | `pls_gradients`，`test_uniform_strain_gradients_are_exact` |
| VSG 窗口可配 | ✅ | `StrainParams.window_pts` / `with_window`，六档扫描 216 ms |
| 至少 engineering 与 green_lagrange | ✅ | 实际给 5 个名字（含 `logarithmic` 别名），`test_every_supported_tensor_name_is_schema_legal` |
| 命名与 `STRAIN_TENSORS`/`STRAIN_METHODS` 严格一致 | ✅ | 校验直接对 schema 常量做；`_METHOD_BY_ORDER` 在**导入时**核对 `STRAIN_METHODS`，改坏了立即炸 |
| `vsg_size_px` 同一公式 | ✅ | **委托** `hl3.io.hdf5_schema.vsg_size_px`，本包不另写一份；`test_the_vsg_formula_has_exactly_one_implementation` 直接断言委托关系 |
| 随结果输出 | ✅ | `StrainField.vsg_px` 为冻结字段，`schema_attrs()` 必带 |

### 4.3 IR1-F4 §10 落盘检查单

| # | 条目 | 本实现 |
|---|---|---|
| 1 | `exx/eyy/exy` 与 `fields/u` 同点序 | ✅ 点序一致；**帧轴与 f32 降型归写入器**（本层是单帧 `(P,) f64`） |
| 2 | 四件必填属性，`@vsg_px` 用 `vsg_size_px()` | ✅ `schema_attrs()`；公式委托 schema 模块 |
| 3 | 有标定才写 `@vsg_mm` | ✅ 未给 `image_scale_px_per_mm` 时该键**根本不出现**（`test_vsg_mm_is_absent_for_an_uncalibrated_analysis`） |
| 4 | 无效点写 NaN 不写 0 | ✅ 邻点不足、秩亏、掩膜、中心点无效一律 NaN |
| 5 | `theta_p` 按 `/project/units@angle` | ⚠️ 本层恒返回**弧度**并在 docstring 写明；单位换算留给写入器（本层不知道 project 属性） |
| 6 | `ezz_assumed` 必带 `@assumption` | n/a 未实现该数据集（见 §6） |
| 7 | 多套平滑窗各占一个 `<strain_id>` | ✅ `with_window()` 支持，命名归写入器 |
| 8 | 经 `_write_dataset` 写 | n/a 属写入器 |
| 9 | `validate_file(strict=True)` 零违规 | n/a 属写入器；本层给出的属性集合是其必要输入 |
| 10 | 消费/回写 `grid/neighbors`（CSR） | ⚠️ 未做。改为输出**逐点有效邻点数** `n_neighbors`，口径可审计但不是 CSR。建议 S2 由 pipeline 层承担 |

### 4.4 顺带修好的门测

`tests/test_s1_metrology.py::test_uniform_strain_smoke`（IR1-G2）在 `hl3.strain` 不存在时 skip、存在但入口名对不上时 **fail**。本实现把入口命名为 `compute_strain`（该测试探测的三个名字之一），现已实跑通过：`exx=0.010000000, eyy=-0.004000000, exy=0.000000000`，与该测试的解析真值逐位一致。全仓 459 项测试全绿。

---

## 5. 与规格的偏差、裁决与待裁决项（如实登记）

| # | 事项 | 处置 |
|---|---|---|
| D-1 | **von Mises 前系数**。R1-O1 §2.11 写 `ε_eq = (2/3)·sqrt(ε₁²+ε₂²+ε₁ε₂)` 并注明"常用形式，实现上给出显式公式与假设"。但该常数**过不了单轴自洽检验**：不可压单轴 `(ε, −ε/2)` 代入应回到 `ε`，`2/3` 给出 `0.577ε`，差一个 `√3`。 | 采用推导值 `ε_eq = (2/√3)·sqrt(ε₁²+ε₁ε₂+ε₂²)`（由 `sqrt(2/3·e_ij e_ij)` + `ε₃ = −(ε₁+ε₂)` 推出），docstring 写死公式与"平面应力 + 不可压"两条前提，测试 `test_von_mises_equals_the_axial_strain_in_incompressible_uniaxial_tension` 钉死。按 IR1-F3 §6，选定即冻结。**建议规格侧修正 §2.11 的印刷常数。** |
| D-2 | **默认加权**。R1-O1 §1.6 产品默认 `GAUSSIAN(σ=L/4)`；IR1-F3 §4 登记 S1 默认为 `uniform`。 | 两种**都实现**，默认取 `uniform`（服从调用面冻结）。翻默认属数值行为变更，须过 A4/G2 门。§3.3 已给出翻转的代价数据（同 VSG 下噪声 +23%~27%），可直接作为该门的输入。 |
| D-3 | **后滤波窗如何进式 (7.2)**。§2.11 步骤 4 只说"用 `L_filter` 代入"，§1.7 说"取实际生效的那个"。级联 `W1` 拟合 + `W2` 滤波的真实支撑是 `W1+W2−1`。 | `effective_window_pts(..., combine="max"|"cascade")`：默认 `"max"`（合规、与他家可比），`"cascade"` 为更保守的诚实值，用了必须在报告里写明。**规格侧建议明确二选一。** |
| D-4 | **`hencky` 与 `logarithmic` 双枚举**（IR1-F4 记账 G-4）。 | 两个名字都接受、走同一实现，`@tensor` **回显调用方所写的名字**（不做静默改写，落盘保真）。 |
| D-5 | **T5 判据用于应变场**。规格 §5.5 断言 `λ > 2·L_VSG ⇒ Â/A > 0.9`，度量对象是位移；应变微分级在 `λ = 2·L_VSG` 处只有 0.78，`λ ≳ 3·L_VSG` 才到 0.90（§3.4）。 | 不改规格文字（不在本人独占路径）。建议 IR1-F2/G2 在 T5 落地时**区分位移与应变两条曲线**，否则应变侧判据会误判。 |
| D-6 | 二阶拟合在**完整对称窗**上与一阶给出逐位相同的梯度（§2.2）。 | 不是缺陷，是代数事实。已在 docstring 与测试中写明，避免后续误以为"开了二阶没生效"。 |

---

## 6. 未实现（S1 明确不做，列为后续）

- **应变的另外三条路线**：`FROM_SHAPE_FUNCTION`（直接取 ICGN 的 `p`，`L_VSG = L_subset`）、`FE_SHAPE_FUNCTION`、`GLOBAL_SPLINE`。VSG 模块已经能表达第一条的 `window_pts = 1`。规格 §2.11 说"四种全部实现是超越闭源软件的可比性优势"，这条优势要到 S2/S3 才兑现。
- **后滤波本身**（高斯/中值/多项式）。只做了 VSG 记账口径，滤波器留给后处理层；默认关闭这条纪律因此暂无实现负担。
- **`ezz_assumed`**：需要明确的塑性/弹性假设与 `@assumption` 字符串，跨 schema 与力学两侧，S2 再定。
- **不确定度传播**：`uncertainty/strain_std`。PLS 是线性算子，`Σ_ε = A Σ_u Aᵀ` 有闭式，§3.3 的解析预测已经验证了对角项；S3 的 UQ 轮次接上即可。
- **`grid/neighbors` CSR 回写**（F4 检查单第 10 条）。
- **曲面应变**（S2/S3 的 3D 路线）：本模块是平面 `(u, v)` 版本；`curvature_k1/k2`、`surface_normal` 不在此轮。

---

## 7. 法律与红线

- 全部为独立实现，数学来源为公开发表文献与仓内规范：Pan et al., *Opt. Eng.* 46:033601 (2007) 的 PLS；iDICs GPG 式 (7.2) 的 VSG；连续介质力学教科书的张量族与极分解。**未下载、未使用、未再分发任何 VIC 二进制、专有手册、示例数据或 Challenge 图像集**；本轮未做任何 VIC 逆向。
- **显微镜零实现**（RUL-04）：本模块与畸变模型正交，不感知任何镜头模型，未新增 `stereo_microscope` 相关的任何参数、代码或文字。
- 新增文件均带 `SPDX-License-Identifier: Apache-2.0` 头（与 `hl3.io` / `hl3.pipeline` 的现行做法一致，供 IR1-G1 复核）。
- `git add` 仅限独占路径：`src/hl3/strain/`、`tests/test_strain.py`、本报告；未使用 `git add .`（同一工作树里 IR1-O3 的 `src/hl3/pipeline/**` 改动确实存在，已刻意不纳入本次提交）。
