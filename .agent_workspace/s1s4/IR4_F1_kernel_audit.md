# IR4-F1 — HL3 S1–S4 内核正确性审计（对照已发表 DIC 文献）

**审计对象**: `src/hl3/correlate/icgn.py`、`src/hl3/strain/*`、`src/hl3/stereo/*`、`src/hl3/pipeline/*`、`src/hl3/uq/*`、`tests/`
**对照文献**: Sutton/Orteu/Schreier《Image Correlation for Shape, Motion and Deformation Measurements》；Pan et al. 2013 IC-GN（Exp Mech 53:1277）；Pan 2009 RG-DIC；Pan et al. 2007 PLS 应变（Opt Eng 46:033601）；Gao et al. 2015 二阶 IC-GN 复合代数；Blaber et al. Ncorr（Exp Mech 55:1105）；Schreier & Sutton 2002（形函数欠匹配）；Hartley & Zisserman《Multiple View Geometry》；iDICs Good Practices Guide（VSG Eq. 7.2）；Reu DIC Challenge / Stereo-DIC Challenge 系列。
**方法**: 逐行公式核对 + 独立数值实验（本轮新做：PLS vs 暴力加权最小二乘、ICGN 协方差 Monte-Carlo 绝对标定、S 曲线相位扫描、B 样条预滤波小图误差、pipeline 应变 pitch 缺陷复现）。全部 691 项现有测试在 numpy 2.4.4 / python 3.12 下通过（43 s）。

---

## 0. 先说结论摘要

数学内核（IC-GN、PLS、张量族、三角化、UQ 传播）**公式层面与文献一致，未发现使算法系统性偏离文献的推导错误**；本轮独立复算全部通过。发现的确实缺陷集中在 **pipeline 装配层**（1 个会产出错数的已确认 bug）、**数值边界**（B 样条预滤波小图截断）、**默认值/语义**（sigma_px、INCREMENTAL、shape_order 静默忽略）。三维链条的结构性缺口（无畸变、无 Zhang 标定、立体匹配仅一阶）已在源码 docstring 中自我声明，但直接决定"能否对标 VIC"的答案（见 §4）。

已验证正确（抽样列举，均与文献逐项核对）：

| 项目 | 位置 | 对照 | 结果 |
|---|---|---|---|
| ZNSSD IC-GN 增量 `Δp = −(JᵀJ)⁻¹Jᵀ(f̄ − (Δf/Δg)ḡ)` | `icgn.py:1110-1113`（Hessian `:1065-1078`，2/Δf² 因子两侧相消） | Pan 2013 Eq.(10)-(12) | ✔ 一致 |
| 逆复合更新 `W(p) ← W(p)·W(Δp)⁻¹`（闭式 2×2 逆） | `icgn.py:1118`, `compose_inverse :639-675` | Baker–Matthews IC | ✔ |
| 二阶 6×6 单项式截断复合（矩阵各行手工展开核对） | `icgn.py:709-755, 786-811` | Gao et al. 2015 | ✔（含 `tests/test_icgn_second.py:386` 截断阶数测试） |
| FFT-CC 整数搜索（零均值参考 × 原始窗口 + 积分图归一 = 精确 ZNCC；无循环卷绕；位移符号核对） | `icgn.py:448-539` | Pan 2009 / 标准 NCC | ✔ |
| 收敛准则 `‖Δp·diag(1,r,r,…)‖ < tol` | `icgn.py:1130-1132` | Pan 2013 建议 | ✔ |
| PLS 应变（linear/quadratic × uniform/gaussian，含洞、掩膜、边界截窗） | `pls.py:309-364` | Pan 2007 | ✔ **本轮独立暴力 lstsq 复算，最大偏差 2.7e-15** |
| Green-Lagrange / Almansi / Hencky / 主应变 / 极分解转角 | `tensors.py:101-210, 314-327` | Sutton 教材 | ✔ |
| von Mises 等效应变系数 `2/√3`（spec 写的 2/3 是错的，代码用推导值并记录偏离） | `tensors.py:270-289` | 标准推导（单轴 (e,−e/2) 回代 = e） | ✔ 代码对，spec 错 |
| VSG `L_VSG = (L_window−1)·step + L_subset` | `vsg.py:121-141`, `dic2d.py:97-110`, 单一实现在 `hdf5_schema.py:403` | iDICs GPG Eq. 7.2 | ✔ |
| `F = [e₂]ₓ P₂ P₁⁺`、Sampson 距离/校正、中点法闭式、Hartley 归一化 DLT、多视 GN | `triangulate.py:283-314, 371-425, 512-536, 439-480, 603-687` | HZ §9.2.2/§12 | ✔（中点法方程组、Sampson 一阶校正向量逐项核对） |
| 三角化协方差 `(Σ JᵢᵀJᵢ/σᵢ²)⁻¹` | `triangulate.py:759-813` | 一阶传播 | ✔ 且 `tests/test_stereo_synth.py:286-300` 有 MC 比值门 |
| RQ 分解 / DLT resection / Umeyama | `calibrate.py:452-586` | HZ / Umeyama 1991 | ✔ |
| UQ 段 C 精确传播（帽矩阵行 = 拟合器自身算子）、GL 雅可比 | `propagate.py:410-482, 515-548` | IR2-F3 / delta 法 | ✔（`tests/test_uq.py:343` MC 比值 ±5%） |
| ICGN 协方差 `Cov(p)=2σ²(JᵀJ)⁻¹` 绝对标定 | `icgn.py:1163-1173` | Wang/Sutton 2009 噪声传播 | ✔ **本轮 MC（400 次注入图像噪声）：σ_pred/σ_emp = 0.90–1.00，无常数因子错误** |
| 插值偏差（S 曲线） | 整个内核 | Schreier/Sutton 插值偏差; Pan 2013 | **本轮实测**（自产 speckle σ=1.4 px，19 个相位）：峰值 1.0 毫像素，RMS 0.64 毫像素 — 达到文献中三次 B 样条的最好水平 |

---

## 1. 算法正确性问题（bug vs 文献）

### BUG-1（已确认，产出错误数值，中高严重度）：pipeline 应变把 `config.step` 当网格间距，无视用户 POI 网格的真实 pitch

- 位置：`src/hl3/pipeline/dic2d.py:918-919`（`"step": config.step, "step_px": float(config.step)`），payload 组装于 `dic2d.py:906-923`；`run_sequence` 接受用户 `points` 时（`dic2d.py:577-585`）不校验其点阵 pitch 与 `config.icgn.step` 一致。
- 复现（本轮实验）：用户网格 pitch = 10 px、`icgn.step = 5`（默认）→ pipeline 产出的 `exx` **恰好是正确值的 2 倍**（`compute_strain(step_px=5)` 与 pipeline 输出逐点一致到 0，`step_px=10` 才是对的）。应变是梯度除以 pitch，错 pitch 就整场错 scale——这正是 `strain/field.py:352-354` docstring 里警告的那类"silently wrong by the image scale"错误，被自家 pipeline 犯了。
- 连带错误：`Dic2DConfig.l_vsg_px`（`dic2d.py:178-180`）与 provenance 的 `l_vsg_px`（`dic2d.py:790-791`）用同一个 `config.step`，VSG 报告随之失真；`dic3d.py` 的 `temporal_config()` 继承同一路径。
- 另一半：各向异性 pitch（x、y 步距不同）的合法点阵，`pls_gradients` 只收一个标量 `step_px`（`pls.py:209`），pipeline 既不能表达也不报错。
- 修复建议：`lattice_shape` 已经算出了轴（`dic2d.py:445-447`），从 `np.diff(xs)/np.diff(ys)` 推真实 pitch；与 `config.step` 不符时用真实 pitch 并记入 provenance，x/y pitch 不等时 raise。

### BUG-2（API 陷阱，低-中）：`Dic2DConfig` 静默忽略 `shape_order=2`

- 位置：`dic2d.py:43`（只 import `icgn_first_order`）、`_solve_tracked` 固定调用一阶（`dic2d.py:705-707`）、`Dic2DConfig.__post_init__`（`dic2d.py:142-167`）不检查 `icgn.shape_order`。
- `hl3/stereo/match.py:286-293` 对同一情况**显式 raise**（"silently ignoring the field would misreport which warp produced the result"）——同一代码库对同一错误一处拒绝、一处静默，用户配 `Dic2DConfig(icgn=ICGNParams(shape_order=2))` 得到的是一阶结果，provenance 里 `"shape_function": "first_order_affine"`（`dic2d.py:770`）虽然诚实，但没有任何报错。`compose_total`（`dic2d.py:378-415`）也只支持 6 参数，意味着二阶时间链参考更新根本没有实现路径。
- 顺带：`dic3d.py` 的 `stereo_icgn` 二阶经 `icgn()` 分派**可用**（`dic3d.py:810`，内部匹配器），但 provenance 硬编码 `"temporal_shape_order": 1`（`dic3d.py:1846`）——正确但值得注释来源。

### BUG-3（文档性声明过强）：`triangulate_optimal` 不是精确 L2 最优

- 位置：`triangulate.py:393-400`（"iterating it converges to the Hartley–Sturm optimum"）、`:539-549`。
- 迭代 Sampson 收敛到**满足极线约束**的点对（此后 DLT 确实精确交汇），但收敛点只是 Hartley–Sturm 六次多项式最优解的一阶近似，二者不重合（HZ §12.5 明确指出 Sampson 校正是 first-order）。实际差异 ≪ 噪声（`tests/test_stereo_synth.py:239` 只验证了"精确交汇"，没验证 L2 最优性），但作为"对照文献的正确性"必须点名：函数名 `triangulate_optimal` 与 docstring 的 "L2-optimal" 是过强声明，报告/论文里引用会被审稿人抓。

### BUG-4（诊断字段定义不一致，低）：`NOT_CONVERGED` 点报告的 ZNCC 滞后一次复合

- 位置：`icgn.py:1115`（zncc 在 `:1118` 的 `compose_inverse` **之前**计算）。迭代预算耗尽（`NOT_CONVERGED`）或 `DIVERGED` 时，返回的 `p` 含最后一次增量而 `zncc` 属于上一迭代的 warp。只有 `CONVERGED` 分支在 `:1134-1156` 重算。无效点不进 `valid`，实际影响小，但"zncc 描述的是返回的 p"这一契约在失败分支上不成立，做收敛诊断/参数调优时会误导。

### BUG-5（低，可放大）：协方差用的是加了对角载荷的 Hessian

- 位置：`icgn.py:1076-1077`（`hessian_raw += hessian_reg·tr(H)/n·I`）先于 `:1171`（`cov = 2σ²·inv(hessian_raw)`）。
- 文献公式是 `2σ²(JᵀJ)⁻¹`（未正则化）。默认 `hessian_reg=1e-9` 时可忽略，但它是公开参数（`icgn.py:108`），用户调大（比如为了压制病态 subset）后协方差被系统性低估且无任何警告。协方差应从加载荷**之前**的 `JᵀJ` 求逆。

### BUG-6（默认值失真，中——针对 3D 质量场语义）：`Dic3DConfig.sigma_px = 1.0`

- 位置：`dic3d.py:207-209`。传播进 `position_sigma_mm` 的图像面匹配噪声默认 1 px；实际 DIC 亚像素匹配噪声典型 0.005–0.05 px（Sutton 教材、本内核自测 σ_u≈0.006 px @ σ_n=2 灰度级）。默认下 `position_sigma_mm` 高估 20–200 倍，`max_position_sigma_mm` 门槛的物理语义随用户是否记得改 `sigma_px` 而漂移。文献惯例（如 VIC-3D 置信区间）是从残差/相关函数曲率**估计**匹配噪声而不是让用户拍脑袋。至少应默认从 ICGN 协方差（内核已有）回填。

### BUG-7（术语，低）：`ReferenceMode.INCREMENTAL` 与行业语义不符

- 位置：`dic2d.py:63-68`、触发逻辑 `:747-754`。VIC/Ncorr 等文献语境里 incremental correlation = **每帧**换参考并累加；这里 INCREMENTAL = ZNCC 中位数跌破 `reference_zncc` 才换（质量触发，其实是更好的策略）。行为本身没错、有测试（`tests/test_pipeline_2d.py:405`），但名字会让迁移用户误判 500% 应变大变形序列的可用性——真正的每帧增量模式（大变形必需）**不存在**。

### 观察-8（有限应变下的闭合近似未声明）：`von_mises`/`tresca` 的 `e3 = −(e1+e2)`

- 位置：`tensors.py:270-305`。对 Green-Lagrange/Hencky 分量直接套小应变不可压缩闭合 `e3=−(e1+e2)`；对 GL，正确的不可压缩条件是 `det F = 1 ⇔ (1+2E1)(1+2E2)(1+2E3)=1`。20% 应变量级误差约百分之几。商业软件同样这么做，但 docstring 只声明了 ν=0.5 与平面应力两个假设（`tensors.py:283-287`），没声明"小应变闭合套在有限应变张量上"这一层——GPG 6.2.1 要求可复现的公式声明，应补。

### 观察-9（结构性，源码已自我声明，此处量化）：立体匹配仅一阶形函数

- 位置：`match.py:283-293`（`shape_order != 1` 直接 raise）、`match.py:41-48`（声明 deferred）。Schreier & Sutton 2002 与 R1-O2 spec S5.1 均要求跨相机匹配默认二阶：会聚 rig 下两视图对倾斜表面的透视差在 subset 内是真曲率，一阶欠匹配产生系统误差（21 px subset、±11° 会聚、表面再倾斜 30° 时约 0.01–0.05 px 量级，随倾角平方增长）。内核有二阶（`icgn_second_order`），`dic3d` 内部匹配器经 `stereo_icgn=replace(icgn, shape_order=2)` 可用（`dic3d.py:171-175` 有说明），唯独 `hl3.stereo.match` 拒绝。属"诚实的缺口"而非 bug，但对标 VIC-3D 时是精度项。

### 观察-10（结构性）：无镜头畸变、无 Zhang 平面标定

- 位置：`calibrate.py:25-39`、`triangulate.py:22-34`、`match.py:33-40`（均自我声明）。现有"标定"= 已知非共面 3D 点的 DLT resection（`calibrate.py:452-497`）——真实标定板流程（Zhang 平面法 + LM 束调 + Brown–Conrady 畸变 + Σ_cal bootstrap）全部缺失。合成实验（`calibrate.py:1055-1143`）本身构造正确，但它度量的是"针孔世界里的标定误差传播"，与真实相机无关。

### 观察-11（鲁棒性缺口）：无 RG-DIC 种子传播、无 partial/mask-aware subsets

- `icgn.py` 逐点独立求解（`:1035` 循环），种子只有 FFT-CC（`:1290-1305`）、prev-frame（`dic2d.py:664-685`）与显式 guess。Pan 2009 的 reliability-guided 队列传播（Ncorr 的核心鲁棒性来源）没有；掩膜/裂纹/边界附近的 partial subset（Ncorr 支持）没有——subset 越界即 `OUT_OF_BOUNDS`（`icgn.py:1039-1045, 1094-1101`）。不影响"正确性"，影响不连续场景的覆盖率。

### 观察-12（UQ 假设 A1 的量化缺口）

- `propagate.py:43-49` 已注册"POI 间独立"假设；但默认 `step=5, subset=21` 时相邻 subset 重叠 ~76%，位移误差空间相关显著（Wang/Sutton 系列）。MC 门（`tests/test_uq.py:343-358`）注入的是**独立位移噪声**，从**图像噪声端**到应变 σ 的端到端标定不存在，相关性对 PLS 差分算子的净效应（可正可负）未测。报告应变 σ 给客户之前需要一条 image-noise-in 的 MC 链。

---

## 2. 数值问题（float32 / 奇异 / 插值）

1. **精度**：内核全程 float64。仓库内唯一 float32 在 `io/hdf5_schema.py:697-707`（合成文件写盘，存储压缩场景合理，读回也不参与计算）。✔ 无 float32 污染计算链。
2. **B 样条预滤波在小图像上不精确（已量化）**：`icgn.py:285` 的 `horizon = min(n, ceil(log 1e-16 / log|z|))` 把 Unser causal 初始化截断在图像长度上，n < ~28 时丢掉镜像折返项。实测整数点重建误差：n=48→1.4e-13、n=16→1.2e-7、n=8→4.7e-3、n=4→1.06 灰度级，**违反类 docstring "returns the original pixel values to round-off"（`icgn.py:315-318`）**。真实 DIC 图像不受影响，但 `BSplineInterpolator` 是公开 API 且被 `dic3d.epipolar_depth_search`（`dic3d.py:692-695`）复用。修复：horizon ≥ n 时改用精确闭式（折叠镜像和），标准 Unser 参考实现有。
3. **奇异性防护整体到位且阈值相互一致**：Hessian 用**重标定后**条件数 ≤1e10 判奇异（`icgn.py:1225-1243`，重标定的理由 `:1066-1071` 写得对——裸 Hessian 的条件数混入参数化因子 r²）；warp 增量 det 相对阈 1e-12（`icgn.py:652-655`）；PLS Gram 特征值相对阈 1e-12（`pls.py:85-90, 361-362`）；三角化 `_REL_EPS=1e-12` 同源（`triangulate.py:95-101`）。批量 `eigvalsh`/`solve` 前先剔除奇异项避免整批炸掉的处理（`pls.py:355-364`、`triangulate.py:643-651, 800-812`）符合 NumPy 语义现实。
4. **一维纹理与平坦 subset**：以整图 std 为尺度的相对对比度阈（`icgn.py:68-74, 235-259`）+ 定向纹理经条件数拒绝（`tests/test_icgn_synth.py:497`），比常见实现（绝对阈）更符合 ZNSSD 的增益不变性。✔
5. **FFT-CC 的两处可容忍抵消**：积分图 `sums_sq − sums²/count`（`icgn.py:519`）对 8-bit 图像损失 ~3 位有效数字（float64 下无碍，方差已 clip≥0）；float64 cumsum 对超大图误差 O(N·eps)。均在 `_CONTRAST_REL_EPS` 缓冲之内。
6. **插值偏差**：实测 S 曲线峰值 1.0 mpx（自产谱 σ_speckle=1.4 px）。三次 B 样条本身即文献推荐档；未提供 Pan 2013 建议的高斯预低通选项（对更硬的 speckle 谱、真实相机噪声下偏差会升到几 mpx），属可选增强而非缺陷。注意：无噪声诱导偏差（bias ∝ σ_noise²，Su/Wang 系列）的任何测量或测试（见 §3）。
7. **梯度边界回退**：`reference_gradients` 的 4 阶→2 阶→单侧回退（`icgn.py:393-401`）与 `make_grid` 默认 margin `r+search+2`（`icgn.py:428`）恰好错开；用户自供贴边 POI 会静默用低阶梯度，仅降精度不出错。
8. **性能而非精度**：`_cho_solve`（`icgn.py:1187-1190`）用一般 `np.linalg.solve` 解三角阵（O(k³) 应为 O(k²)）；`_well_conditioned` 每点一次 `eigvalsh`；主循环纯 Python 逐点（`icgn.py:1035`）。数学正确，吞吐与 C++ 商业实现差 2–3 个数量级。
9. **`grid_from_points` 容差取整边界**（`field.py:447`）：`round(coord/tol)·tol` 可能把两个近同坐标劈到相邻倍数 → 轴分裂，随后的 spacing 校验会报"not on a regular grid"，报错语义偏离真实原因（浮点抖动）。极端 case，低危。
10. **`dic3d._as_projection` 用精确零判奇异**（`dic3d.py:494`：`abs(det) <= 0.0`）——近奇异 P 会漏过，下游 `_viewing_rays` 的 `solve` 放大误差。与同库其它地方的相对阈值风格不一致。

---

## 3. 缺失的测试（能抓住上述问题的那种）

现有 8600 行测试的密度和刁钻程度高于多数开源 DIC（截断复合阶数、算子等价、MC 比值带、失败路径 RuntimeWarning 清零等都有）。缺的是这些：

1. **自定义 pitch 点阵 + 已知均匀应变场的 pipeline 端到端测试** → 直接抓 BUG-1。构造 pitch=10 的用户网格、`icgn.step=5`，命令一个 `exx=1e-3` 的合成拉伸，断言 pipeline 应变 = 1e-3（现在会得 2e-3）。同时断言各向异性 pitch 被拒绝。
2. **PLS 对独立 oracle 的回归测试**：`tests/test_uq.py:182`（算子等价）与 `propagate.py:80` 共享 `_weights_1d`/`_TERMS` —— 拟合器和传播器**同源**，同源 bug 两边一起错、测试照样绿。把本轮的暴力 `np.linalg.lstsq`（含权、含洞、含边界截窗、四种变体）对照固化进 `tests/test_strain.py`。
3. **ICGN 协方差绝对标定 MC**：`tests/test_icgn_synth.py:345` 只测 σ²→4σ² 的缩放，丢常数因子 2、或误用重标定/加载荷 Hessian（BUG-5 的放大形态）都不会被抓。加一个 300–500 次图像噪声注入、断言 `σ_emp/σ_pred ∈ [0.85, 1.15]` 的测试（本轮实测 0.90–1.00，可行）。
4. **图像噪声 → 应变 σ 的端到端 MC**（观察-12）：现有 MC 门从位移端注入独立噪声；需要一条从加噪图像对经 `compute_covariance=True` → `displacement_variances` → `propagate_strain_std` 与直接 MC 应变散布对比的链路，在默认 `step<subset` 下量化 A1 假设的实际偏差并把结论写进 `neighbor_correlation` 的文档。
5. **B 样条小图契约测试** → 抓数值问题 §2.2：对 n∈{4,8,16,64} 断言整数点重建 <1e-9，当前 n≤16 全挂；修复后转为回归护栏。
6. **`Dic2DConfig(shape_order=2)` 必须 raise（或生效）** → 抓 BUG-2。与 `match.py` 的行为对齐。
7. **ZNSSD↔ZNCC 一致性与失败分支 zncc 定义**：直接断言收敛点 `C_znssd = 2(1−zncc)`（用求解器内部量重算），并断言 `NOT_CONVERGED` 点的 zncc 与返回的 p 同一 warp → 抓 BUG-4。
8. **噪声诱导偏差测试**：固定亚像素相位 0.25，扫 σ_noise ∈ {0,2,4,8} 灰度级，断言 bias 增长 ∝σ²且封顶（文献值 ~几 mpx @ σ=8/255）。当前测试只在 σ=2 断言精度（`test_noise_degrades_precision_gracefully`），偏差与噪声的耦合完全未测。
9. **公共基准数据**：全部精度证据来自单一自产谱（σ_speckle=1.4 px, `tests/test_icgn_synth.py:107-134`）。要主张 VIC-class，至少需要 (a) speckle 尺寸/对比度扫描（Reu 建议 3–5 px speckle 的敏感性), (b) 2D DIC Challenge 2.0 Sample 14/15（star 场）空间分辨率-噪声曲线，(c) Stereo-DIC Challenge 几何的实测（`calibrate.py:256-272` 已复刻其 rig 参数却没有配套 gate 测试把 rms_um 钉死成回归阈值——`run_synthetic_experiment` 是脚本不是测试）。
10. **一阶 vs 二阶立体匹配的欠匹配量化**（观察-9）：倾斜平面 + Challenge rig，断言一阶匹配的系统视差误差和二阶（经 `dic3d` 内部匹配器）的差值 —— 给 `match.py` 的 deferred 决策一个数字依据，也防止未来接线二阶时无回归基准。
11. **长序列参考更新漂移**：`tests/test_pipeline_2d.py:385` 只经历 1–2 次切换。≥10 次 EVERY_N 切换、连续运动的复合误差增长测试缺失（每次切换都在非整数坐标重采样，误差应 ~√k·插值噪声，需确认不超线性增长）。
12. **`sigma_px` 语义测试**（BUG-6）：断言默认 `position_sigma_mm` 与 ICGN 协方差推出的真实匹配噪声之间的比值被记录/警告——现在 `tests/test_pipeline_3d.py:1212` 只测缩放关系，不测绝对语义。

---

## 4. 结论：能否在纸面上对标 VIC 级局部 DIC？

### 能对标的部分（in-principle，合成/针孔域内）

- **2D 位移内核（S1）：能。** 配方就是文献里 VIC-2D/Ncorr 的那一套（ZNSSD IC-GN 一阶+二阶、双三次 B 样条预滤波插值、FFT-CC 整数种子、条件数/对比度门控），公式逐项核对无误；本轮实测 S 曲线峰值偏差 ~1 mpx、噪声下位移 σ ~0.006 px @ σ_n=2 DN 且协方差自校准——这些数字放进 Pan 2013 / Ncorr 论文的表里不丢人。二阶形函数的截断复合代数（Gao 2015）实现严谨，甚至比多数开源实现讲得清楚。
- **应变（S1）：能，且透明度超过商业软件。** PLS 与独立加权 lstsq 一致到 3e-15；张量族齐全、rigid-rotation 零应变有精确断言；VSG 严格 GPG Eq. 7.2 且全库单一实现。前提是修掉 BUG-1——目前自定义网格下 pipeline 会安静地给出错 scale 的应变。
- **UQ（S4）：框架能，且是差异化亮点。** 位移→应变的方差传播是"拟合器自身算子"的精确二次型，MC 校准 ±5%；四条假设 A1–A4 显式注册。补上图像噪声端到端 MC（§3.4）后可以对外背书。
- **三角化/极线度量（S2/S3 的几何半边）：能。** HZ 教科书级正确，协方差有 MC 门，质量门（cheirality + 协方差上限）设计正确地抓住了远场退化。

### 不能对标的部分（结构性，与 bug 无关）

1. **真实 3D 测量：目前不能。** 无任何镜头畸变模型（L0 针孔）、无 Zhang 平面标定/束调、无 Σ_cal。真实镜头 k1~1e-3–1e-1 在图像边缘造成数像素畸变，比本内核 1 mpx 的匹配floor 大 3–4 个数量级；Stereo-DIC Challenge 的结论（商业软件差异主要来自标定）恰恰说明这块是决定性短板。源码处处诚实声明了这一点，但结论就是：**在真实相机数据上与 VIC-3D 不可比，直到 L1+ 畸变与真实标定链落地。**
2. **立体匹配一阶限制**（`match.py:286`）：大倾角表面系统欠匹配，Schreier–Sutton 建议的二阶缺省未接线（内核具备，装配层拒绝）。
3. **鲁棒性特性缺失**：无 RG-DIC 种子传播、无 partial/mask-aware subset、无每帧增量参考模式 → 裂纹/大变形/局部脱散场景的覆盖率会低于 VIC/Ncorr。这不改变"收敛点的数字是对的"，改变的是"多少点能收敛"。
4. **吞吐**：纯 NumPy 逐点 Python 循环，与多线程 C++ 差 2–3 个数量级。"on paper" 精度不受影响，但任何实际工作流（10⁵ POI × 10³ 帧）都跑不动，这也是为什么文首 docstring 自称 normative reference 而非产品内核（`icgn.py:1-5`）——定位是对的。
5. **证据链**：所有精度主张目前建立在**自产合成谱**上（生成器与被测插值器解耦，方法学正确，`tests/test_icgn_synth.py:1-11`），没有任何公共 Challenge 数据点。"VIC-class"在拿到 DIC Challenge star 场曲线和 Stereo Challenge 几何的钉死回归阈值之前，只能是内部判断，不能写进对外材料。

### 修复优先级

| # | 项 | 位置 | 动作 |
|---|---|---|---|
| P0 | BUG-1 应变 pitch | `dic2d.py:919` | 从 lattice 推 pitch；不一致 raise/覆盖 + 测试 §3.1 |
| P1 | BUG-6 sigma_px 默认 | `dic3d.py:208` | 从 ICGN 协方差回填或强制显式传入 |
| P1 | BUG-2 shape_order 静默 | `dic2d.py:142-167` | `__post_init__` 拒绝，或接线二阶（含 compose_total 12 参版） |
| P2 | BUG-5 协方差用加载 Hessian | `icgn.py:1077/1171` | 求逆用未加载 JᵀJ |
| P2 | 数值-2 预滤波小图 | `icgn.py:285-291` | horizon≥n 用精确镜像闭式 |
| P2 | BUG-4 zncc 滞后 | `icgn.py:1115` | 失败分支同样重算或文档声明 |
| P3 | BUG-3 文档 / BUG-7 命名 / 观察-8 假设声明 | `triangulate.py:394`、`dic2d.py:63`、`tensors.py:283` | 措辞修正 |

（本审计所用验证脚本：PLS 暴力对照、协方差 MC、S 曲线扫描、预滤波小图误差、pitch bug 复现——均为一次性脚本，未入库；建议按 §3 固化为测试。）
