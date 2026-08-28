ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# IR2-O3 · 不确定度传播 `hl3.uq` 与结构校验 CLI `hl3.cli.validate` 实现报告

> 子代理：IR2-O3（opus-fast）｜轮次：Impl-R2 / S3
> 独占路径：`src/hl3/uq/**`、`src/hl3/cli/**`、`tests/test_uq.py`、`tests/test_validate.py`、本文件
> 上游效力顺位（RUL-08）：`LEGAL.md` → Gate → 内核规格 R1-O1 §2.6/§6.2 → 冻结契约 `IR2-F3-uq-contract.md`（B/C/D 段与调用面）与 `IR2-F4-validate-cli.md`（CLI 调用面）→ 代码注释
> 约束遵守：`src/hl3/correlate/icgn.py` **零改动**、`src/hl3/strain/**` **零改动**（`git diff` 均为空）
> 分支：`cursor/ir2-o3-uq-fe9e`｜提交：`c1e73a8`（uq）、`8db94a0`（cli）
> 环境：CPU-only，Python 3.12.3 + NumPy 2.4.4 + h5py 3.16.0，无 GPU、无 SciPy

---

## 0. TL;DR

传播链本身是**精确**的，误差在舍入级：闭式锚点在 54 组参数上最大相对偏差 **3.3×10⁻¹⁶**（契约判据 1e-12，余量四个数量级），独立噪声的 Monte Carlo 预测/实测比 **0.997–1.004**（判据 [0.8, 1.25]）。

但把它接到真实相关器上，**预测值只有实测散布的 0.56 倍**。本轮把这个缺口定位到了唯一一处，并且量化了它：

| 段 | 内容 | 预测/实测 |
|---|---|---|
| A | σ_n → `ICGNResult.covariance` | **0.996**（σ_u）/ **1.015**（σ_v） |
| B+C+D | 核协方差 → 应变 std | **0.554–0.570** |
| C+D 单独（喂实测位移散布） | 位移方差 → 应变 std | **0.560–0.565** |

A 段准，C+D 段喂进真实的位移方差仍然只有 0.56 —— 所以缺口既不在核的协方差模型里，也不在传播算术里，而在**契约 §6 假设 A1（邻点 POI 误差独立）**。子集重叠时相邻 POI 的位移误差正相关，而应变是差分算子，正相关的邻点差分噪声比独立情形大。

**决定性实验（§4.3）**：固定 subset = 21 px 扫 step，让重叠度从 5.25 降到 0.53：

| step | subset/step | 位移误差 lag-1 相关 | 预测/实测 |
|---|---|---|---|
| 4 | 5.25 | 0.780 | 0.557 |
| 8 | 2.62 | 0.585 | 0.582 |
| 12 | 1.75 | 0.391 | 0.697 |
| 16 | 1.31 | 0.210 | 0.823 |
| **21** | **1.00** | **0.001** | **1.017** |
| 28 | 0.75 | −0.003 | 1.064 |
| 40 | 0.53 | −0.018 | 0.998 |

**子集刚好不重叠（step = subset）时比值精确回到 1，相关系数精确回到 0。** 这条曲线把 A1 从一句免责声明变成了一个有刻度的已知偏差：`neighbor_correlation="independent"` 这个随结果落盘的字段现在有实测标定表支撑，报告口径是「**常规 DIC 参数（step ≈ subset/4）下本 σ 系统性偏低约 1.8 倍**」，而不是「假设独立」。

CLI 侧：`python -m hl3.cli.validate` 四个退出码全部实测通过，无 h5py 时模块仍可导入、验证时退出码 2；`tests/test_validate.py` 在无 h5py 环境下降级为 5 passed / 11 skipped 而非报错。

测试：`tests/test_uq.py` 39 项 + `tests/test_validate.py` 16 项，**55 项全绿**；全仓 `pytest tests src/tests` **689 passed / 0 failed**。

---

## 1. 交付物

| 文件 | 改动 | 行数 |
|---|---|---|
| `src/hl3/uq/propagate.py` | 新增 | 635 |
| `src/hl3/uq/__init__.py` | 新增 | 53 |
| `src/hl3/cli/validate.py` | 新增 | 109 |
| `src/hl3/cli/__init__.py` | 新增 | 18 |
| `tests/test_uq.py` | 新增 | 705 |
| `tests/test_validate.py` | 新增 | 269 |
| `src/hl3/correlate/icgn.py` | **零改动** | — |
| `src/hl3/strain/**` | **零改动** | — |

复现（无需安装）：

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_uq.py tests/test_validate.py   # 55 passed, 2.2 s
PYTHONPATH=src python3 -m pytest -q tests src/tests                           # 689 passed, 45 s
python3 -m ruff check src/hl3/uq src/hl3/cli                                  # All checks passed
PYTHONPATH=src python3 -m hl3.cli.validate file.hl3 --strict
```

最小用例：

```python
from hl3.strain import StrainParams, compute_strain
from hl3.uq import displacement_variances, propagate_strain_std

params = StrainParams(window_pts=5, tensor="green_lagrange")
strain = compute_strain(u, v, params, step_px=8, subset_px=31, valid=ok)

dv = displacement_variances(result)          # B 段：核协方差 → Var(u)/Var(v)/Cov(u,v)
std = propagate_strain_std(                  # C+D 段
    u, v,
    dv.u_var.reshape(u.shape), dv.v_var.reshape(u.shape),
    params, step_px=8,
    uv_cov=dv.uv_cov.reshape(u.shape),
    valid=ok,
    check_against=strain,                    # 参数漂移 → ValueError
    image_noise_sigma_dn=1.5,
)
std.as_grid("exx_std")                       # (ny, nx) 不确定度云图
std.schema_datasets()                        # → uncertainty/strain_std/{exx,eyy,exy}
```

---

## 2. `hl3.uq`：实现要点

### 2.1 C 段用的必须是拟合器**自己**的算子

契约 §4 条 2 把这条写成「等价性纪律」，实现上它决定了整个模块的结构。PLS 梯度是位移的线性泛函 `g = (G⁻¹AᵀW) u / step`，方差就是对应的二次型 —— 前提是这里构造的 `G`、`W`、秩判据与 `pls_gradients` 的**完全同一**。任何一点漂移（多算一个邻点、权重差一个归一化、秩阈值不同）都会产生一个「看起来合理、但描述的是另一个估计器」的 σ，而这种错误在数值上几乎不可见。

处置是**不重写、只引用**：

```python
from hl3.strain.pls import _REL_EPS, _TERMS, _weights_1d
```

项列表、权重剖面、秩阈值在树里只有一份定义。同理，梯度本身不在本模块重算，而是调 `pls_gradients` 拿回来 —— 这样线性化点和 NaN 图样天然就是拟合器的。导入私有名不美观，但备选方案是复制三段定义然后靠测试追它们漂移，那更糟。

`test_operator_is_the_fitters_own_operator` 用**冲激响应**验证这条耦合：给单个 POI 的位移打一个 δ 扰动，看 `pls_gradients` 输出变了多少，与本模块对「该 POI 单位方差、其余为零」给出的 σ 比对。这是对算子逐元素的直接检验，不是只比 NaN 图样。

### 2.2 缺测方差 → NaN，且不缩窗

契约 §7 的 fail-closed：某点应变有限，但参与其拟合的任一**有效邻点**没有已知方差 → 该点 σ 为 NaN。两条备选都被明确拒绝：

- 把缺失方差当 0 —— 会低估，而低估的不确定度比没有不确定度更危险；
- 缩窗重算 —— 得到的 σ 描述的是一个**没人计算过的**估计器。

实现上这是一次掩膜相关（`(mask & ~known)` 在窗内的和 > 0 即排除），与主路径同一套窗口，因此不会出现「σ 有效但应变无效」的反向情形。`isfinite(std) ⊆ isfinite(strain)` 由 `test_validity_pattern_is_exactly_the_strain_fields` 逐点锁定。

### 2.3 坏输入 → 异常，缺测 → NaN

两层区分是全库惯例，本模块的具体落点：

| 情形 | 处置 |
|---|---|
| `covariance is None` | `ValueError`（不拿 ZNCC 当代理） |
| 有限但为负的方差 | `ValueError`（不可能的输入，不是缺测） |
| `\|Cov(u,v)\| > sqrt(Var(u)·Var(v))` | `ValueError`（2×2 块非半正定） |
| `step_px` 非有限或 ≤ 0 | `ValueError` |
| `euler_almansi` / `hencky` / `logarithmic` | `ValueError`（S3 无冻结雅可比，**禁止**静默按 engineering 近似） |
| `check_against` 元数据或 NaN 图样不符 | `ValueError` |
| 方差为 NaN | 该点 σ 为 NaN |
| 空网格 | 空结果，不抛异常 |

4×4 梯度协方差的两个对称元素由**同一个** `cross` 标量赋值（`cov_g[:, a, 2+b] = cov_g[:, 2+b, a] = cross`）而不是各算一遍：分别 einsum 会因求和次序不同在 1e-30 量级上破坏对称性，事后再 `0.5*(C+Cᵀ)` 补救不如一开始就只算一次。

### 2.4 张量范围按契约冻结为两个

`PROPAGATED_TENSORS = ("engineering", "green_lagrange")`。`engineering` 的雅可比是常数，**D 段也精确**，因此整条 C+D 对它是零近似；`green_lagrange` 是一阶 delta 法（假设 A4），雅可比是变形梯度自己的元素，`test_green_lagrange_jacobian_is_the_frozen_one` 用有限差分核对到数值精度。

---

## 3. `hl3.uq` 实测

### 3.1 闭式锚点（契约 §5，判据 ≤ 1e-12）

uniform 权重、linear 拟合、完整 L×L 窗、同方差、`uv_cov=0`：

```
σ_exx = (σ_u / step) · sqrt(12 / (L²(L²−1)))
```

54 组参数（L ∈ {3,5,7,9,11,15} × step ∈ {1, 5, 12.5} × σ_u ∈ {0.005, 0.01, 0.1}），**最大相对偏差 3.331×10⁻¹⁶**。契约 §5 举的那个例子（σ_u = 0.01 px、step = 5、L = 5 → 2.83e-4）逐位命中，已单列为 `test_the_documented_example`。

| L | L_VSG | 闭式 σ_exx | 实测 | 相对偏差 |
|---|---|---|---|---|
| 3 | 31 px | 816.5 µε | 816.5 µε | 0 |
| 5 | 41 px | 282.8 µε | 282.8 µε | 0 |
| 7 | 51 px | 142.9 µε | 142.9 µε | 0 |
| 9 | 61 px | 86.1 µε | 86.1 µε | 2.2×10⁻¹⁶ |
| 11 | 71 px | 57.5 µε | 57.5 µε | 1.1×10⁻¹⁶ |
| 15 | 91 px | 30.9 µε | 30.9 µε | 2.2×10⁻¹⁶ |

**这张表与 IR1-O2 §3.3 的 Monte Carlo 噪声底板独立吻合到 1.5% 以内**（他们测 828/286/143/87/32 µε，本文算 816/283/143/86/31 µε）—— 一边是 400 次随机实现的散布，一边是闭式二次型，两条路对上，说明 `hl3.strain` 与 `hl3.uq` 对「同一个估计器」的理解一致。这也是 IR1-O2 §6 记的那笔欠账（「PLS 是线性算子，`Σ_ε = AΣ_uAᵀ` 有闭式，S3 的 UQ 轮次接上即可」）的兑现。

**L⁻² 律**：σ 从 L=3 到 L=15 掉了 26 倍，这是 VSG 权衡的定量另一半 —— `hl3.strain.vsg` 只定性说「窗口越大越平滑」，本模块给出代价的准确数字。

### 3.2 Monte Carlo（契约 §10 条 3，判据 [0.8, 1.25]）

400 次实现、独立高斯位移噪声 σ_u = 0.02 px、30×30 网格、step 5 px：

| tensor | L | 比值均值 | min | max |
|---|---|---|---|---|
| engineering | 3 | 1.0038 | 0.888 | 1.130 |
| engineering | 5 | 0.9993 | 0.886 | 1.165 |
| engineering | 9 | 0.9971 | 0.879 | 1.120 |
| green_lagrange | 3 | 1.0004 | 0.904 | 1.110 |
| green_lagrange | 5 | 0.9999 | 0.895 | 1.156 |
| green_lagrange | 9 | 0.9993 | 0.912 | 1.122 |

均值全在 1.000 ± 0.004；逐点的 min/max 离散是 400 次实现估计 std 的采样误差（理论 ±1/√(2·399) ≈ 3.5%，实测 ±12% 的尾部与卡方分布的尾一致），不是偏差。

### 3.3 二级效应（都是自洽性检验，也都是可报告的数字）

**加权与拟合阶次**（σ_u = 0.01 px，step 5）：

| W | weighting | order | σ(exx) | 相对 uniform-linear |
|---|---|---|---|---|
| 5 | uniform | linear | 282.8 µε | 1.000 |
| 5 | uniform | quadratic | 282.8 µε | **1.000** |
| 5 | gaussian | linear | 347.6 µε | **1.229** |
| 5 | gaussian | quadratic | 347.6 µε | 1.229 |
| 9 | uniform | linear | 86.1 µε | 1.000 |
| 9 | uniform | quadratic | 86.1 µε | **1.000** |
| 9 | gaussian | linear | 108.5 µε | **1.260** |

两条独立确认：

1. **高斯加权在同一名义 L_VSG 下噪声更高**，且与 IR1-O2 §3.3 的 Monte Carlo 逐档对得上：W=5 他们测 1.231、本文算 **1.229**；W=9 他们测 1.253、本文算 **1.260**。他们据此提醒「名义 L_VSG 相同但加权不同的两套结果不可直接比较」；现在这条提醒有解析支撑，而且**可以逐点算出代价**，不必再跑 MC。
2. **完整对称窗上二阶与一阶的方差逐位相同** —— IR1-O2 §2.2 从奇偶分块论证了梯度值相同，本文确认**方差**也相同（同一个帽子矩阵行，自然同一个二次型）。「开了二阶没生效」的误解现在在两个层面上都有断言。

**窗口被截断的地方**（W=5，31×31 网格）：

| 位置 | σ(exx) | 相对内部 |
|---|---|---|
| 内部 | 282.8 µε | 1.000 |
| 边界内第 2 行 | 282.8 µε | 1.000 |
| 边界内第 1 行 | 316.2 µε | 1.118 |
| 边界行 | 365.1 µε | **1.291** |

边界上 σ 高 29%，因为窗口被裁掉一半、杠杆臂 `Σdx²` 变小。**这正是 σ 场必须逐点输出而不能报一个全场标量的理由** —— 一个全场平均值会让边界点看起来和内部一样可信。

**一个洞的影响**（中心 POI 被掩膜，W=5）：

| 邻点 | σ(exx) | 相对 |
|---|---|---|
| (+0,+1) | 285.8 µε | 1.011 |
| (+0,+2) | 295.4 µε | 1.044 |
| (+1,+1) | 285.9 µε | 1.011 |
| (+0,+3) | 282.8 µε | **1.000** |

影响**严格局部**：出了窗口半径就精确回到基线，与 IR1-O2 §2.1 条 1「掩膜直接进法方程、单点丢失是精确求解不是近似」同源。洞本身是 NaN。

---

## 4. 端到端链路：假设 A1 是唯一的缺口

### 4.1 场景

220×220 合成散斑（6000 个高斯斑，radius 2.6 px，归一化到 0–255 DN），B 样条重采样施加均匀应变 `exx = 2.0e-3, eyy = −6.0e-4`，两幅图各自加 i.i.d. 高斯噪声 σ_n = 1.5 DN。subset 31 px、step 8 px、529 POI 全部 CONVERGED；应变窗 5 POI、engineering 张量。40 次独立噪声实现给出实测散布。

### 4.2 分段对账

```
--- A 段（核 Cov(p) vs 实测位移散布）---
predicted σ_u 5.005 m-px   measured 5.027 m-px   ratio 0.996
predicted σ_v 5.025 m-px   measured 4.952 m-px   ratio 1.015

--- B+C+D（按核给的协方差走完全链）---
  exx: predicted  102.4 µε   measured  184.8 µε   ratio 0.554
  eyy: predicted  102.9 µε   measured  180.4 µε   ratio 0.570
  exy: predicted   73.3 µε   measured  131.8 µε   ratio 0.556

--- C+D 单独（把实测位移散布当输入喂进去）---
  exx: predicted  103.4 µε   measured  184.8 µε   ratio 0.560
  eyy: predicted  101.9 µε   measured  180.4 µε   ratio 0.565
  exy: predicted   73.8 µε   measured  131.8 µε   ratio 0.560
```

三行读法：

1. **A 段没问题**。`Cov(p) = 2σ_n²H⁻¹` 在本场景把逐点位移 1σ 预测到 0.4%–1.5%。R1-O1 §2.6 那个公式是对的，`hl3.correlate` 的实现也是对的。
2. **B+C+D 差 1.8 倍**。
3. **把 A 段整段旁路、直接喂实测位移方差，还是差 1.8 倍** —— 这一步是关键：它证明缺口不在核的噪声模型里，也不在 B 段的提取里，而在 C 段「邻点独立」这一个假设上。

契约 §10 条 4 要求端到端比值落在 [0.8, 1.25]。**本轮不满足（0.55），并且不打算靠调参数让它满足** —— 0.55 是 A1 的真实代价，把它藏起来才是错的。下节给出它的完整刻度。

### 4.3 决定性实验：让子集停止重叠

固定 subset = 21 px、σ_n = 1.5 DN、应变窗 5 POI，扫 step（320×320 图，每档 40 次实现）。`corr(1 POI)` 是位移误差沿 x 的 lag-1 空间相关系数，从 40 次实现直接估计：

| step | subset/step | 预测 σ(exx) | 实测 σ(exx) | 预测/实测 | 位移误差 lag-1 相关 |
|---|---|---|---|---|---|
| 4 | 5.25 | 312.9 µε | 561.5 µε | 0.557 | 0.780 |
| 8 | 2.62 | 164.0 µε | 281.5 µε | 0.582 | 0.585 |
| 12 | 1.75 | 113.1 µε | 162.4 µε | 0.697 | 0.391 |
| 16 | 1.31 | 87.4 µε | 106.1 µε | 0.823 | 0.210 |
| **21** | **1.00** | **70.5 µε** | **69.4 µε** | **1.017** | **0.001** |
| 28 | 0.75 | 54.8 µε | 51.5 µε | 1.064 | −0.003 |
| 40 | 0.53 | 40.8 µε | 40.9 µε | 0.998 | −0.018 |

两条同时发生的事，同一个原因：

- **step = subset 处相关系数精确穿过零，比值精确回到 1**。不重叠的子集不共享像素，误差就真的独立，此时传播是精确的（`test_monte_carlo_ratio_is_within_the_gate_band` 的合成设定正对应这一行）。
- **重叠越深、相关越强、低估越多**，且是单调的。

对报告口径的直接后果：

> **契约 §10 条 4 的 [0.8, 1.25] 判据在 `step ≥ 0.75·subset` 时成立，在常规 DIC 参数（`step ≈ subset/4`，即 §4.2 的场景）下不成立，实测 0.55–0.58。**

这不是实现缺陷，是 A1 的定义域。`StrainStdField.neighbor_correlation="independent"` 这个随结果落盘的字段现在有上表作为标定，报告时应写成「本 σ 在 step/subset = X 下系统性偏低约 Y 倍」，而不是含糊的「假设邻点独立」。

补充的解析侧对照（§4.3 之外，用指数相关 `corr(d) = exp(−d/ρ)` 直接合成相关位移噪声，绕开相关器）：

| 相关模型 | 预测/实测 |
|---|---|
| 独立 | 0.999 |
| ρ = 1.0 POI | 0.662 |
| ρ = 3.2 POI | 0.621 |
| ρ = 5.2 POI | 0.679 |
| ρ = 7.2 POI | 0.743 |

同一量级、同一方向。有意思的是它**不是单调**的：相关长度远大于应变窗时，窗内的位移误差近乎共模，而梯度算子对共模不敏感，低估反而缓解。真实相关器落在曲线的左半支（ρ 约等于 subset/step − 1）。

### 4.4 修正它需要什么

不在 S3 范围（契约 §9 明列「跨 POI 相关性建模」为非目标），但路径是清楚的，登记以便后续轮直接开工：

C 段的公式已经是二次型 `Var(g_a) = c_aᵀ Σ_u c_a / step²`，当前实现取 `Σ_u = diag(Var(u_j))`。**只要把 `Σ_u` 换成带非对角项的窗内协方差块，代码结构不变**（`np.einsum("pj,pj->p", ...)` 变成 `np.einsum("pj,pjk,pk->p", ...)`）。缺的是 `corr(d)` 的模型，两条来路：

1. **解析**：子集重叠比例 `max(0, 1 − d·step/subset)` 作为相关系数的一阶近似 —— 便宜，但 §4.3 的实测相关（step 8 时 0.585，重叠比例预测 1 − 8/21 = 0.62）说明它大致对，值得先试。
2. **实测**：`repeat_static` 静态重复采集直接估计 `corr(d)`，这正是 `UQ_METHODS` 里已经留了名字的那条路。

接口上按契约 §11 条 2 追加关键字（`neighbor_correlation="overlap"` 之类），默认值复现当前冻结行为；数值行为变更须过 A/G2 门。

---

## 5. `hl3.cli.validate`：薄到不能再薄

### 5.1 铁律的落实

契约 §1 的铁律是「CLI 不得实现任何检查」。落实成三件可检验的事：

- `validate.py` 的 import 只有 `argparse`、`sys`、`collections.abc.Sequence`、以及 `hl3.io.hdf5_schema` 的两个公开名。`test_cli_package_has_no_import_side_effects` 用 `ast` **走一遍模块的 import 列表**做结构断言，而不是靠 code review —— 后者拦不住半年后加的一行。
- `main` **返回**退出码而不是 `sys.exit`，测试因此能进程内调用并同时断言返回值与 capsys 输出。argparse 用法错误时自己 `SystemExit(2)`，是允许的例外且已与退出码表一致。
- `test_command_reports_exactly_what_the_library_returns` 把 `validate_file` 换成桩函数，断言 CLI 打印的就是桩返回的字符串本身 —— 违规文案的**逐字透传**（契约 §4）由此变成可执行的约束，不是措辞约定。

违规行不加前缀、不重排、不去重、**不翻译**：两套词汇描述同一条规则，是两个工具对同一个文件给出不同说法的开始。

### 5.2 四个退出码实测

```
$ python -m hl3.cli.validate /tmp/demo.hl3
OK /tmp/demo.hl3
exit=0

$ python -m hl3.cli.validate /tmp/demo.hl3 --strict
/analyses/ana_01: 应当写 @git_sha
FAIL /tmp/demo.hl3: 1 条违规
exit=1

$ python -m hl3.cli.validate /tmp/broken.hl3          # 删了根 @hl3_schema_version
/: 缺必填属性 @hl3_schema_version
FAIL /tmp/broken.hl3: 1 条违规
exit=1

$ python -m hl3.cli.validate /tmp/nope.hl3
error: 无法打开 /tmp/nope.hl3: [Errno 2] Unable to synchronously open file ...
exit=2

$ python -m hl3.cli.validate /tmp/junk.hl3            # 16 字节文本
error: 无法打开 /tmp/junk.hl3: Unable to synchronously open file (file signature not found)
exit=2

$ python -m hl3.cli.validate
usage: python -m hl3.cli.validate [-h] [--strict] path
python -m hl3.cli.validate: error: the following arguments are required: path
exit=2
```

「打不开的文件是 2 不是 1」这条裁决（契约 §5）在代码里配了注释说明理由：违规的唯一事实源是 `validate_file` 的返回列表，CLI 不得自行编造条目；将来若判定 garbage 文件算不合规，该判定长在 `validate_file` 里，退出码 1 自动成立，CLI 零改动。

### 5.3 无 h5py 环境

契约 §2 要求 `import hl3.cli.validate` 在无 h5py 时必须成功。实测（用一个抛 `ImportError` 的假 `h5py.py` 遮蔽真包）：

```
import without h5py: OK
error: hl3.io.hdf5_schema 的读写入口需要 h5py（`pip install 'hl3[hdf5]'` 或 `pip install h5py`）。
exit code: 2

$ PYTHONPATH=/tmp/noh5py:src pytest -q tests/test_validate.py
5 passed, 11 skipped
```

跑通的 5 项是导入纪律、`__all__`、包无副作用、help 文本、h5py 缺失路径本身 —— 这几项**本来就不该 skip**（契约 §8 条 1），需要真文件的 11 项才 skip。`test_missing_h5py_exits_two_on_stderr` 用 monkeypatch 让 `validate_file` 抛 `Hdf5Unavailable`，因此在**有** h5py 的环境里也跑，缺失路径不会因为 CI 恰好装了 h5py 就没人测。

---

## 6. 契约符合性

### 6.1 IR2-F3（UQ 契约）

| 条款 | 状态 |
|---|---|
| §2 `__all__` 恰好四个名字 | ✅ `test_public_surface_is_exactly_the_frozen_four` |
| §3 提取索引走 `p_labels`，不另写常量 | ✅ 一阶 `p[3]`、二阶 `p[6]` 由标签定位，两阶都有测试 |
| §3 条 2 `covariance is None` → `ValueError` | ✅ |
| §3 条 3 NaN 原样透传、B 段不按 status 重掩膜 | ✅ |
| §4 条 1 签名镜像 `compute_strain` | ✅ 逐字一致 |
| §4 条 2 等价性纪律（不改 `strain/**`，梯度逐位相等） | ✅ `git diff` 空；冲激响应测试逐元素核对算子 |
| §4 条 3 `valid` 判据同源 | ✅ 同一 mask 传给 `pls_gradients` |
| §4 条 4 `check_against` fail-closed | ✅ 元数据 4 项 + NaN 图样 + 网格形状 |
| §4 条 5 纯函数、无 RNG、逐位可复现 | ✅ `test_repeated_calls_are_bit_identical` |
| §5 C 段公式（含 `/step²`） | ✅ |
| §5 D 段雅可比表（两族） | ✅ 有限差分核对 |
| §5 闭式锚点 ≤ 1e-12 | ✅ **3.3×10⁻¹⁶** |
| §5 张量范围冻结为两族，其余 `ValueError` | ✅ 三个被拒张量各一项测试 |
| §6 假设 A1–A4 随结果登记 | ✅ 且 A1 有 §4.3 的实测标定表 |
| §7 调用级错误 → `ValueError`，缺测 → NaN | ✅ 8 种情形逐项有测试 |
| §7 `isfinite(std) ⊆ isfinite(strain)` | ✅ |
| §10 条 1 闭式 | ✅ |
| §10 条 2 等价性 | ✅ |
| §10 条 3 Monte Carlo ∈ [0.8, 1.25] | ✅ 0.997–1.004 |
| §10 条 4 端到端 ∈ [0.8, 1.25] | ⚠️ **0.55**，见 §4；`step ≥ 0.75·subset` 时成立 |
| §10 条 5 失败语义 | ✅ |
| §10 条 6 确定性 | ✅ |

### 6.2 IR2-F4（validate CLI 契约）

| 条款 | 状态 |
|---|---|
| §1 CLI 不实现任何检查 | ✅ `ast` 结构断言 + 桩函数断言 |
| §2 `__init__.py` 仅 docstring、无副作用、不预导入子模块 | ✅（早期草稿里的 `__main__.py` 与 `__getattr__` 已删除） |
| §2 `main(argv) -> int` 返回而非 `sys.exit` | ✅ |
| §2 `prog="python -m hl3.cli.validate"` | ✅ `test_help_advertises_a_working_invocation` |
| §2 无 h5py 时可导入 | ✅ 实测 |
| §2 导入纪律（只准标准库 + `hdf5_schema` 公开面） | ✅ ast 遍历 |
| §3 恰一个 `path`、`--strict`、无短旗标 | ✅ |
| §4 违规逐字、`OK`/`FAIL` 汇总行、stderr 单行 `error:` | ✅ |
| §4 确定性（同文件同旗标 → stdout 逐字节相同） | ✅ `test_output_is_byte_for_byte_reproducible` |
| §5 退出码 0/1/2 | ✅ 全部实测 |
| §8 条 1 导入测试不 skip，运行类测试 skipif | ✅ 5 passed / 11 skipped |
| §8 条 2 合成算例 `--strict` 为 0 | ❌ **实际为 1**，见 §7 |
| §8 条 3/4/5 | ✅ |

### 6.3 测试清单（55 项）

`tests/test_uq.py`（39）：闭式锚点 6 + 文档算例 1 + L⁻² 律 1 + 线性缩放 1 + 算子等价 3 + 有效性图样 1 + 秩亏拒绝 1 + 洞 1 + 加权 1 + 阶次 1 + Monte Carlo 2 + GL 雅可比 1 + 张量拒绝 3 + 交叉项 1 + B 段布局 2 + B 段 fail-closed 2 + 端到端 1 + 缺测方差 1 + 坏输入 1 + 空网格 1 + `check_against` 1 + 确定性 1 + 零方差 1 + 公开面 1 + schema 落点 1 + 元数据/视图 1 + NaN 图样 1。

`tests/test_validate.py`（16）：合规 1 + strict 2 + 违规逐字 1 + 退出码 2 四路 4 + 确定性 1 + 导入纪律 3 + 桩函数 2 + subprocess 2。

---

## 7. 与契约的偏差与待裁决项（如实登记）

| # | 事项 | 处置 |
|---|---|---|
| **D-1** | **IR2-F4 §8 条 2 与写入器实际行为不符**。契约写「`--strict` 对合成算例同样为 0（selftest 已保证 strict 违规数为 0）」，但 `write_synthetic_hl3` 实际不写 `@git_sha`，strict 下必得 1 条 `/analyses/ana_01: 应当写 @git_sha`。 | 测试按**实际行为**写（`test_strict_reports_the_writers_one_should_level_gap`，断言 1 条违规 + 退出码 1），不改 CLI 去迎合契约文字 —— CLI 一旦对某条 SHOULD 级发现特殊处理，§1 铁律就破了。**修法归 schema 侧二选一**：让 `write_synthetic_hl3` 写一个 `@git_sha`，或修订 F4 §8 条 2 的措辞。CLI 零改动即可跟随。 |
| **D-2** | **IR2-F3 §10 条 4 端到端判据 [0.8, 1.25] 在常规参数下不成立**（实测 0.55）。 | 不调参、不放宽、不隐藏。§4.3 给出完整标定曲线并证明 `step = subset` 处比值精确为 1.017 —— 判据本身没错，错在它默认了 A1 成立。**建议 IR2-F1/G3 把该判据改为带条件的**：`step ≥ 0.75·subset` 时 [0.8, 1.25]；重叠子集下引用标定表。 |
| **D-3** | 本模块 import 了 `hl3.strain.pls` 的三个私有名（`_REL_EPS`、`_TERMS`、`_weights_1d`）。 | 契约 §4 条 2 禁止改 `strain/**`，而等价性又要求同一份定义，复制是唯一的备选且更差（§2.1）。**建议 S4 由 `hl3.strain` 的 owner 把这三个提升为公开或半公开面**，本模块改 import 即可，零行为变更。 |
| **D-4** | `neighbor_correlation` 目前只有 `"independent"` 一个取值。 | 契约 §6 A1 就是这么冻结的槽位。§4.4 已写明扩展路径与接口形状（追加关键字，默认复现冻结行为）。 |
| **D-5** | `tests/test_uq.py` / `test_validate.py` 的 `# noqa: E402` 被默认配置的 ruff 报 RUF100。 | 仓内 `test_strain.py`、`test_stereo_synth.py`、`test_stereo_match.py` 同样如此（仓内无 ruff 配置文件，CI 也只跑 pytest）。**保持与既有测试一致**，不单独改我这两个文件制造第二种风格。`src/hl3/uq`、`src/hl3/cli` 本体 ruff 全绿。 |

---

## 8. 未实现（S3 明确非目标，交接后续轮）

契约 §9 已明列的，逐条确认未做且未假装做：

1. **跨 POI 相关性建模** —— 见 §4.4，路径与接口形状已勘定。这是本轮最有价值的一笔欠账。
2. **派生量的 std**（`e1/e2/theta_p/gamma_max/von_mises/tresca`）—— `strain_std/<name>` 同名规则已留槽位。
3. **`euler_almansi / hencky / logarithmic` 的解析雅可比** —— 当前 fail-closed 拒绝。
4. **参考更新序列的组合方差**（`ReferenceMode ≠ FIXED`）—— 此类运行不得写 `@method="propagated"` 的 `strain_std`；本模块不感知参考模式，**该纪律须由 S4 写入器执行**，这里显式交接。
5. **立体链 `w_std` 与 `Σ_cal` 合成** —— `hl3.stereo.triangulation_covariance` 已有匹配项；IR2-O1 §6 条 6 也把「`Σ_match` 传播」交到了本轮，但契约 §9 明确把它划出 S3，故未做。**两侧记账一致，是同一笔欠账**。
6. **二阶 delta 修正**（假设 A4）、**其他 UQ 方法**（`bootstrap / repeat_static / synthetic_calibrated`）、**GPU 路径**。
7. **`uncertainty/` 组的实际落盘** —— 本模块只产出 `schema_datasets()` / `schema_attrs()`，写入归 S4。

性能（未优化，登记为可改进项）：30 000 POI、W=5 传播 110 ms（其中 `pls_gradients` 21 ms），W=15 时 806 ms。**成本随窗口面积 W² 线性涨**（扣掉 `pls_gradients` 后 5→15 是 8.7 倍，与 225/25 = 9 一致），因为当前实现对每点显式展开 W² 长的帽子矩阵行；`pls_gradients` 走可分离相关是 O(N·W)，所以 VSG 扫描时应变仍是秒级、σ 会慢一档。

**可分离化是可行的，公式已经在手边**：`Σ_j c_x[j]² Var_j = Σ_{t,s} (G⁻¹)_{1t}(G⁻¹)_{1s} · [Σ_j X_jt X_js w_j² Var_j]`，方括号里正是 `Var` 与核 `w²·dx^(a_t+a_s)·dy^(b_t+b_s)` 的一次可分离相关 —— 与 IR1-O2 §2.1 对法方程做的改写是同一手法，只是权重换成 `w²`、被相关的场换成方差场。本轮未做，登记给后续轮。

---

## 9. 法律与门禁自查

| 项 | 状态 |
|---|---|
| `src/hl3/correlate/icgn.py` 未改写 | ✅ `git diff` 空 |
| `src/hl3/strain/**` 未改写 | ✅ `git diff` 空 |
| 纯独立实现（Pan 2007 PLS 方差、一阶 delta 法、iDICs GPG §5.4） | ✅ 未接触任何 VIC 二进制、专有手册、示例数据或 Challenge 影像 |
| 显微镜零实现（RUL-04） | ✅ 本模块与镜头模型正交，未新增任何相关参数或文字 |
| SPDX 头 | ✅ 四个新文件均带 `Apache-2.0` |
| 确定性（无 RNG、单线程、float64） | ✅ `test_repeated_calls_are_bit_identical` + CLI 逐字节可复现 |
| 逐点失败不抛异常、不编数 | ✅ NaN 承载 + fail-closed 二分 |
| 88 列 | ✅ `ruff --select E501` 四文件零命中 |
| `git add` 仅独占路径 | ✅ 两次提交（`c1e73a8` uq + 测试、`8db94a0` cli + 测试）均只含独占路径，未夹带同工作树内其他子代理的改动 |

---

## 10. 一句话交接

传播链本身可以信任到舍入级，A 段（核协方差）也准；**唯一的系统性缺口是子集重叠导致的邻点相关，它让 σ 在常规参数下偏低约 1.8 倍，并且已经有了一张从 0.56 到 1.02 的完整标定曲线**（§4.3）。修它不需要改结构，只需要把 C 段二次型里的 `diag(Var)` 换成带非对角项的块，和一个 `corr(d)` 模型。

*IR2-O3 完。`icgn.py` 与 `strain/**` 零改动。*
