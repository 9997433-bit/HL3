ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR1-F2：S1 pytest 测试矩阵（实现者必加用例）

> 子代理：IR1-F2（fable）｜轮次：Impl-R1（S1 · 2D 计量收口）
> 独占路径：`.agent_workspace/s1s4/IR1-F2-s1-test-matrix.md`（仅本文件，未改任何代码/测试）
> 效力：本文列出的**语义与阈值**对 IR1-O1/O2/O3/G2 具约束力（阈值全部溯源到已冻结 Gate，见 §5）；
> 函数/参数**命名**以 IR1-F3 公共 API 文档为准，冲突时改名不改语义。
> 纪律：RUL-07 —— 达不到的阈值用 `pytest.mark.xfail(strict=True, reason="<数值差距>")` 登记，**禁止放宽阈值**。修改本文任何阈值需书面 ADR。

---

## 0. 范围与归属

S1 停止条件（`s1s4/DISPATCH.md`）：二阶形函数或明确 xfail；应变/VSG；2D pipeline；精度测试可跑。
本矩阵按用户指定四轴组织：**平移（TR）／单轴应变（UX）／VSG 尺寸（VSG）／空 AOI（EA）**。

| 测试文件 | 归属 | 覆盖 |
|---|---|---|
| `tests/test_icgn_second.py` | IR1-O1 | TR-01…05、UX-01…03、EA-01 |
| `tests/test_strain.py` | IR1-O2 | UX-04…08、VSG-01…09、EA-02/03 |
| `tests/test_pipeline_2d.py` | IR1-O3 | TR-06/07、UX-10、EA-04/05/06 |
| `tests/test_s1_metrology.py` | IR1-G2 | TR-08/09、UX-09、VSG-10（A1/A2/A4 门测） |

既有 `tests/test_icgn_synth.py`（127 例，一阶内核）**不重复**：新入口只需复现其同类保证（见 §4 横切不变量）。散斑生成器直接 `import test_icgn_synth`（pytest prepend 导入模式下同目录可导入，只读复用，勿改该文件）。

**合成变形图生成纪律**（对全部 UX 用例强制）：变形图必须由**连续纹理在解析变形坐标下重渲染**得到——脉冲中心按 `φ(X) = x₀ + F·(X−x₀)` 移动、PSF 不变、过采样 ≥8 后块平均落到传感器像素。**严禁**用被测插值器扭曲参考图（否则测的是自洽性不是精度）。平移场沿用 Fourier 移位法（解析精确）。应变场位移随 |X−x₀| 增长：AOI 半径 ≤60 px 且 ε·半径超过 ~3 px 拉入域时必须给整数种子（FFT-CC 或解析值取整——种子只解决收敛域，亚像素答案仍由求解器自己迭代得出，不算作弊）。

---

## 1. TR — 平移

一阶平移已被 `test_icgn_synth.py` 全覆盖；本组针对**二阶求解器、pipeline、门级计量**。

| ID | 文件 | 建议名 | 安排 | 断言 |
|---|---|---|---|---|
| TR-01 | `test_icgn_second.py` | `test_second_order_recovers_subpixel_translation` | 192px 散斑对，真值 (0.37, −0.42) px，默认参数网格 | 全点 `CONVERGED`；mean\|err\| < 5e-3 px；**全部 10 个非平移参数** \|·\| < 2e-3（纯平移下梯度与曲率必须归零） |
| TR-02 | `test_icgn_second.py` | `test_second_order_subpixel_phase_sweep` | u ∈ {0, 0.1, …, 0.9}（≥11 相位），逐相位求 bias_u | 每相位 \|bias\| < 0.01 px；bias 曲线峰峰 ≤ 0.01 px（A2 语义在求解器层的镜像） |
| TR-03 | `test_icgn_second.py` | `test_first_second_order_parity_on_translation` | 同一图对分别跑一阶/二阶 | 逐点 \|u₁−u₂\| 与 \|v₁−v₂\| ≤ 1e-3 px；status 一致 |
| TR-04 | `test_icgn_second.py` | `test_second_order_integer_translation_is_exact` | 整像素移位 {(1,0),(2,3),(3,−2)}（无插值误差处无处可藏） | max\|err\| < 1e-4 px；曲率项 < 1e-5；zncc.min() > 0.9999 |
| TR-05 | `test_icgn_second.py` | `test_second_order_large_translation_with_fftcc_seed` | 真值 (7.35, −5.6)，`search_radius=12` | 全点收敛；max\|err\| < 0.05 px 且 mean\|err\| < 5e-3 px；无种子时不得静默给错答案（复现一阶同名保证） |
| TR-06 | `test_pipeline_2d.py` | `test_pipeline_translation_end_to_end` | 图像对 → pipeline（相关+应变）一次调用 | 位移 mean\|err\| < 5e-3 px；全场应变 \|ε\| < 1e-4（平移不产生应变）；结果对象含参数快照与 `L_VSG` |
| TR-07 | `test_pipeline_2d.py` | `test_pipeline_writes_full_p_and_status_to_hdf5` | TR-06 结果写 HDF5，纯 h5py 重读 | 保存**完整 `p`**（不只 u,v）；`status`/`zncc` 与场同维；重读值与内存位一致 |
| TR-08 | `test_s1_metrology.py` | `test_a2_scurve_peak_to_peak_gate` | 稳定 ICGN API（非标量 stub）跑 ≥11 相位 S 曲线 | **峰峰 ≤ 0.01 px**（A2 v1 门）；测得值供 IR1-G3 写入 `benchmarks/metrology/metrics.json` |
| TR-09 | `test_s1_metrology.py` | `test_a1_static_noise_floor_gate` | 零位移 + 独立噪声实现（σ_n=2 灰度级/8-bit），**≥3 套散斑种子**取平均 | **σ_u ≤ 0.01 px 且 σ_v ≤ 0.01 px**（A1 v1 门）；逐种子值也入报告 |

## 2. UX — 单轴应变

真值场：`u = ε·(x−x₀)`，`v = 0`（纯单轴）；泊松变体 `v = −ν·ε·(y−y₀)`。阈值源自 R1-O1 §5.4 T4（冻结）：ε ≤ 0.10 时 \|ε̂−ε\| < 1e-4；泊松比误差 < 0.01。

| ID | 文件 | 建议名 | 安排 | 断言 |
|---|---|---|---|---|
| UX-01 | `test_icgn_second.py` | `test_first_order_recovers_uniform_uniaxial_strain` | ε = 5e-3 渲染对，一阶求解 | mean\|û_x−ε\| < 1e-4；\|u_y\|,\|v_x\|,\|v_y\| < 1e-4；位移逐点误差 < 5e-3 px |
| UX-02 | `test_icgn_second.py` | `test_strain_sweep_first_order`（parametrize） | ε ∈ {1e-3, 5e-3, 1e-2, 5e-2, 1e-1}（大 ε 给整数种子） | 每档 \|û_x−ε\| < 1e-4（T4 冻结阈值；不达标 strict xfail 登记数值） |
| UX-03 | `test_icgn_second.py` | `test_second_order_on_uniform_strain_zeroes_curvature` | 同 UX-01 图对，二阶求解 | \|û_x−ε\| ≤ 一阶同项；全部曲率项 \|·\| < 1e-4（均匀应变无二阶项） |
| UX-04 | `test_strain.py` | `test_pls_is_exact_on_analytic_linear_field` | 解析位移场直接喂应变引擎（不经求解器） | 线性场 + 线性 PLS ⇒ ε̂_xx = ε、ε̂_yy = ε̂_xy = 0，容差 1e-12（机器精度级） |
| UX-05 | `test_strain.py` | `test_green_lagrange_conversion` | 同场，tensor=GREEN_LAGRANGE，ε = 0.05 | E_xx = ε + ε²/2 = 0.05125（容差 1e-12）——与工程应变差 1.25e-3，公式错必炸 |
| UX-06 | `test_strain.py` | `test_poisson_ratio_recovery` | u=εx、v=−νεy（ν=0.30）：解析场 + 求解器输出两版 | 解析版 \|ν̂−ν\| < 1e-10；求解器版 \|ν̂−ν\| < 0.01（T4） |
| UX-07 | `test_strain.py` | `test_strain_invariant_to_superposed_rigid_translation` | UX-01 场 + 叠加 (0.3, −0.4) px 刚体平移 | 两版 ε̂ 场逐点差 < 1e-6（平移不得漏进应变） |
| UX-08 | `test_strain.py` | `test_rigid_rotation_discriminates_tensor_families` | 解析纯转动场 θ = 1° | GREEN_LAGRANGE：\|E\| < 1e-8；ENGINEERING：max\|ε\| > 1e-4（θ²/2 ≈ 1.52e-4）——张量族接错必炸 |
| UX-09 | `test_s1_metrology.py` | `test_a4_strain_noise_floor_gate` | 静态带噪对（σ_n=2 灰度级），默认 subset 21 / step 5 / window 5 ⇒ **声明 L_VSG = 41 px**，≥3 套散斑 | **σ_ε ≤ 100 µε（1e-4）**（A4 v1 门）；输出必须携带声明的 `L_VSG`，缺声明即 FAIL |
| UX-10 | `test_pipeline_2d.py` | `test_pipeline_uniaxial_strain_end_to_end` | ε = 5e-3 图像对全链 | 应变场 mean\|ε̂_xx−ε\| ≤ 1e-4；结果记录 tensor 族 + `L_VSG`（px 与物理单位） |

## 3. VSG — 虚拟应变片尺寸

冻结公式（iDICs GPG Eq. 7.2，R1-O1 §1.7/§2.11）：`L_VSG = (L_window − 1)·L_step + L_subset`；`L_VSG_phys = L_VSG / image_scale`；`FROM_SHAPE_FUNCTION` 模式 `L_VSG = L_subset`。

| ID | 文件 | 建议名 | 安排 | 断言 |
|---|---|---|---|---|
| VSG-01 | `test_strain.py` | `test_vsg_formula_exact`（parametrize ≥20 组） | (L_subset, L_step, L_window) 组合扫描 | 报告的 `L_VSG` **整数严格相等**于公式值 |
| VSG-02 | `test_strain.py` | `test_vsg_physical_units` | 给定 image_scale（px/mm） | `L_VSG_phys == L_VSG / image_scale`（容差 1e-12） |
| VSG-03 | `test_strain.py` | `test_from_shape_function_vsg_equals_subset` | 直接取 `p` 梯度模式 | `L_VSG == L_subset` |
| VSG-04 | `test_strain.py` | `test_uniform_strain_independent_of_vsg` | UX-01 场，window ∈ {3, 5, 9, 15} | 解析场：各档 ε̂ 极差 < 1e-10；求解器场：极差 < 5e-5（均匀场对窗口不敏感是 PLS 的定义性质） |
| VSG-05 | `test_strain.py` | `test_strain_noise_decreases_with_vsg` | 静态带噪对（固定种子），window ∈ {3, 5, 9, 15} | σ_ε 逐档**非增**，且 σ_ε(15) < 0.5·σ_ε(3)（稳健主断言） |
| VSG-06 | `test_strain.py` | `test_spatial_resolution_transfer_vs_vsg` | 解析正弦场 u = 0.5·sin(2πx/λ)，λ ∈ {40, 80, 160, 320} px 直接喂引擎 | λ > 2·L_VSG 处应变幅值传递 Â/A > 0.9（R1-O1 T5）；传递率随 window 单调下降——"VSG=空间分辨率"语义锁定 |
| VSG-07 | `test_strain.py` | `test_strain_recompute_does_not_touch_images` | 应变引擎输入仅 (points, p/位移, valid)——API 不得收图像；跑完相关后删除图像数组再改 window 重算 | 重算成功且不重跑相关（R1-O1 T10 性能契约："改窗口秒级出结果"） |
| VSG-08 | `test_strain.py` | `test_edge_points_with_deficient_neighbors_are_nan` | AOI 边缘点邻点数 < neighbor_min（默认 0.5·L_window²） | 该点应变 = NaN（禁止外推），内部点不受影响 |
| VSG-09 | `test_strain.py` | `test_strain_params_reject_nonsense` | window 偶数 / <3、image_scale ≤ 0、未知 tensor 名 | 全部 `ValueError`（对齐 `ICGNParams.__post_init__` 风格） |
| VSG-10 | `test_s1_metrology.py` | `test_a4_measurement_declares_vsg` | 调 A4 计量入口 | 返回结构同时含 σ_ε、`L_VSG`、参数快照三者；供 IR1-G3 metrics.json 消费（RUL-08：无 VSG 声明的应变噪声数字非法） |

## 4. EA — 空 AOI 与不变量横切

既有契约（`test_icgn_synth.py` "Empty AOI" 段）：空点集是合法 AOI，返回正确形状/dtype 的空数组，**不抛错**。S1 三个新入口必须继承。

| ID | 文件 | 建议名 | 安排 | 断言 |
|---|---|---|---|---|
| EA-01 | `test_icgn_second.py` | `test_second_order_empty_aoi`（parametrize 空输入 4 形态） | `np.empty((0,2))` / `[]` 等 | `n_points == 0`；标量场 shape (0,)；`p.shape == (0, 12)`；`status_counts() == {}`；开协方差时 shape (0, 12, 12) |
| EA-02 | `test_strain.py` | `test_strain_engine_empty_field`（parametrize） | 空位移场入引擎 | 各应变分量 shape (0,)、dtype float64；`L_VSG` 照常计算返回；无异常无警告 |
| EA-03 | `test_strain.py` | `test_strain_on_all_invalid_field_is_all_nan` | 非空但全点 `OUT_OF_BOUNDS`/`SINGULAR_HESSIAN` | 应变全 NaN、形状保持；不得把无效位移当 0 参与拟合 |
| EA-04 | `test_pipeline_2d.py` | `test_pipeline_empty_aoi_full_chain` | 空 AOI 全链跑通并写 HDF5 | 正常完成（0 点是成功不是错误）；HDF5 各数据集 0 行、纯 h5py 可开可读；状态计数为空 |
| EA-05 | `test_pipeline_2d.py` | `test_pipeline_aoi_fully_outside_image` | 非空 AOI 全部越界 | 0 个 valid；应变全 NaN；pipeline 报告逐 status 计数而非抛错 |
| EA-06 | `test_pipeline_2d.py` | `test_nan_masking_propagates_into_strain_halo` | 混合 AOI（含平坦补丁致 SINGULAR） | 无效点及其 window 邻域按文档化 halo 语义为 NaN；远处点应变不受污染（阈值同 UX-01） |

**横切不变量**（每个新公共入口至少各 1 例，归属各自文件）：
1. **确定性**：同输入连跑两次，输出数组 `np.array_equal` 位级一致（S3 C1 的 S1 先行桩）。
2. **float64 规范**：结果 dtype float64（RUL-02，CPU 参考实现即计量规范）。
3. **输入验证**：NaN/Inf 图像或位移场、错形状 points → `ValueError`（沿用一阶入口的边界检查语义，B 样条 IIR 预滤波会把单个 NaN 扩散到全部系数）。

---

## 5. 阈值溯源与验收

| 门 | 用例 | 阈值 | 出处 |
|---|---|---|---|
| A1 位移噪声底 | TR-09 | σ_u ≤ 0.01 px（≥3 散斑平均） | R2-F1 §2 A 表（冻结） |
| A2 S 曲线 | TR-08（求解器层镜像 TR-02） | 峰峰 ≤ 0.01 px | 同上 |
| A4 应变噪声底 | UX-09 + VSG-10 | σ_ε ≤ 100 µε @ 声明 L_VSG | 同上 + RUL-08 |
| 二阶形函数 | TR-01…05、UX-03、EA-01 | 表内各值 | S1 停止条件；不可达 → strict xfail |
| 应变/VSG 引擎 | UX-04…08、VSG-01…09、EA-02/03 | 表内各值 | R1-O1 §2.11/§5.4/§5.10（T4/T5/T9/T10） |
| 2D pipeline | TR-06/07、UX-10、EA-04…06 | 表内各值 | S1 停止条件 |

**验收规则**：上表 34 例全部存在且 pass，或以 `strict=True` xfail 登记并在各自报告写明数值差距；`pytest -q tests src/tests` 全绿（xfail 计入绿）；任何对本文阈值的改动视同放宽门槛，按 RUL-07 拒绝。

*IR1-F2 完。仅本文件，未触碰任何其他路径。*
