ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# IR1-O1：二阶（12 参数）IC-GN 形函数实现报告

> 子代理：IR1-O1（opus-fast）｜轮次：Impl-R1 / S1｜矩阵：4 fable + 3 opus-fast + 3 gpt-sol
> 独占路径：`src/hl3/correlate/**`、`tests/test_icgn_second.py`、`.agent_workspace/s1s4/IR1-O1-second-order.md`
> 门禁依据：`s1s4/IR1-F1-s1-gates.md` A 组 G-S1-SF2-1…4｜规范依据：`round1/R1-O1-hl3-2d-spec.md` §2、`round2/R2-O1-icgn-impl.md` §2.7
> 法律边界：**纯独立实现**。二阶形函数与其群表示来自公开文献（Lu & Cary 1998；Gao et al. 2015，见 §8），未复制 OpenCorr / Ncorr / DICe 任何代码，未接触任何 VIC 二进制或专有格式。
> 环境：CPU-only，Python 3.12.3 + NumPy，**无 GPU、无 CUDA、无 SciPy**。

---

## 0. TL;DR — 实测数字

在**解析二次位移场**（系数已知、生成器不含任何重采样，见 §3）上，160×160 图、subset 31×31（r=15）、step 20、25 个 POI、两阶均 25/25 收敛：

| 指标 | 一阶（6 参数） | 二阶（12 参数） | 增益 |
|---|---|---|---|
| **位移 RMS 误差** | 4.050 × 10⁻² px | **6.115 × 10⁻⁴ px** | **66×** |
| 位移最大 \|误差\| | 5.177 × 10⁻² px | 1.389 × 10⁻³ px | 37× |
| 位移梯度 RMS 误差 | 6.391 × 10⁻⁴ | 2.977 × 10⁻⁵ | 21× |
| ZNCC 最小值 | 0.999581 | **0.999996** | — |
| 平均迭代数 | 4.44 | 5.04 | — |
| 曲率项最大绝对误差 | 不可表示 | 1.878 × 10⁻⁵ px⁻¹ | — |
| 曲率项最差相对误差 | 不可表示 | **3.27 %** | — |

六个曲率参数（真值 `u_xx=8×10⁻⁴`、`u_xy=−2×10⁻⁴`、`u_yy=3×10⁻⁴`、`v_xx=−3.6×10⁻⁴`、`v_xy=3×10⁻⁴`、`v_yy=−5×10⁻⁴`）逐项相对误差 2.0 %–3.3 %，**全部符号与量级正确**。

**这不是自洽性伪影**：目标图与参考图都是同一个解析带限纹理在不同坐标处的**闭式取值**，生成过程零重采样、零插值（§3.1），因此上表测的是形函数模型误差本身。

代价侧同样落测（不是口头声明）：纯平移含噪场（σ=2 灰阶）上二阶散布 σ_u 是一阶的 **2.58×**（0.0084 px vs 0.0033 px），单点耗时 +13 %（2.13 ms vs 1.88 ms）。**一阶仍是默认**。

测试：`tests/test_icgn_synth.py` **127 项零改动全绿** + `tests/test_icgn_second.py` **44 项新增全绿** = 171 passed。

---

## 1. 交付物

| 文件 | 归属 | 改动 |
|---|---|---|
| `src/hl3/correlate/icgn.py` | IR1-O1 独占 | 求解器改造为阶数通用；新增二阶代数与 `icgn_second_order` / `icgn`（+394 / −33 行，现 1306 行） |
| `src/hl3/correlate/__init__.py` | IR1-O1 | 仅再导出新符号 + docstring 更新 |
| `tests/test_icgn_second.py` | IR1-O1 独占 | 新增，44 项测试 + 解析二次形变生成器，826 行 |
| `.agent_workspace/s1s4/IR1-O1-second-order.md` | IR1-O1 独占 | 本文 |

**未触碰**：`src/hl3/strain/`、`src/hl3/pipeline/`、`src/hl3/io/`、`src/hl3/stereo/`、`tests/test_icgn_synth.py`、`tests/test_s1_metrology.py`、`benchmarks/`、`pyproject.toml`。

⚠️ **协作事故（如实登记）**：本轮多个子代理共用同一个 checkout，工作树与索引都是共享的。我的第一次提交 `3fa436f` 虽然只 `git add` 了两个 correlate 文件，但**当时索引里已被兄弟代理暂存了** `.agent_workspace/s1s4/IR1-F3-public-api.md`、`.agent_workspace/s1s4/IR1-G3-metrics.md`、`benchmarks/metrology/metrics.json`，`git commit` 连带把它们一起提交了。这三个文件是兄弟代理的合法产出、内容未被我改动，且已在分支上；按"不改写已推送历史"纪律**不做 force push 回退**。此后所有提交改用 pathspec 形式 `git commit -- <路径>` 绕开共享索引，`f57125c`、`990f24b` 均为单文件干净提交。同期工作树的分支也被兄弟代理切走过一次（`cursor/dic-sota-plan-259d` → `cursor/ir1-o2-strain-068c`），故本代理改用显式 refspec `git push origin HEAD:cursor/dic-sota-plan-259d` 推送，不再争抢本地分支指针。

---

## 2. 设计：为什么是 6×6 矩阵表示

### 2.1 形函数

二次形函数（Lu & Cary 1998）把 POI 偏移 `(dx, dy)` 处的子集点位移为

```
xi  = u + u_x·dx + u_y·dy + u_xx·dx²/2 + u_xy·dx·dy + u_yy·dy²/2
eta = v + v_x·dx + v_y·dy + v_xx·dx²/2 + v_xy·dx·dy + v_yy·dy²/2
```

参数向量固定为 `p = (u, u_x, u_y, u_xx, u_xy, u_yy, v, v_x, v_y, v_xx, v_xy, v_yy)`，与 `hdf5_schema.SHAPE_PARAM_COUNT` 的 quadratic=12 槽位对齐。

### 2.2 核心困难与取法

IC-GN 要求形函数集合对**复合与求逆封闭**——增量作用在参考子集上，更新式是 `W(p) ← W(p)∘W(dp)⁻¹`。一阶仿射天然封闭（3×3 齐次矩阵群），**二次多项式不封闭**：两个二次映射复合出四次项。

标准解法（Gao et al. 2015）：不表示多项式本身，而表示它**对单项式向量的作用**。取

```
S(dx, dy) = (dx², dy², dx·dy, dx, dy, 1)ᵀ
```

则每个二次形函数对应一个 6×6 矩阵 `W(p)`，满足 `W·S(dx,dy) = S(xi_abs, eta_abs)`（丢弃三次/四次单项式）。矩阵天然可乘可逆，复合与求逆退化为线性代数；第 3、4 行原样携带形函数系数，读回即得参数。

实现要点（`icgn.py` §"Second-order shape function algebra"）：

- `warp_matrix_second_order(p)` → 6×6；第 5 行恒为 `e6`，故乘积与逆都保持该行，群结构闭合。
- `warp_params_second_order(M)` **只读第 3、4 行**——冗余的乘积行被忽略，这正是"截断复合"良定义的原因。
- `compose_inverse_second_order(p, dp)`：先用与一阶**同一套相对行列式判据**筛掉线性部分退化的增量（`|det| ≤ 1e-12·mag²` → `LinAlgError`），再解 `W(dp)ᵀ·Xᵀ = W(p)ᵀ`（不显式求逆）。

### 2.3 截断误差有多大——已量化并锁死（G-S1-SF2-1 要求）

门禁允许二阶复合不精确封闭，**前提是写明近似及误差界并由测试锁住**。`composition_defect()` 测量 `W(p)∘W(dp)⁻¹` 再作用回 `W(dp)` 与直接 `W(p)` 在 31×31 子集九个角点/中点上的最大像素差：

| 增量平移尺度 | 子集上最大缺陷 | 测试上界 |
|---|---|---|
| 0.1 px | 1.899 × 10⁻⁴ px | < 1 × 10⁻³ |
| 0.01 px | 1.151 × 10⁻⁵ px | < 1 × 10⁻⁴ |
| 0.001 px | 7.640 × 10⁻⁷ px | < 1 × 10⁻⁵ |

缺陷随增量**每缩小一个数量级下降一个数量级以上**（测试断言 ≥ 5×，实测 ~15×），即复合是二阶精确的。IC-GN 收敛判据是缩放 `‖dp‖ < 1e-4 px`，此时截断贡献外推约 10⁻⁷–10⁻⁸ px，比测量量本身低约七个数量级，**不可能影响不动点**。

在**仿射子群上截断为零**（`test_the_composition_is_exactly_closed_on_the_affine_subgroup`，实测 < 1e-11）：平方一个仿射映射不产生三次项。任何真实变形的绝大部分都住在仿射子群里，这是该表示可以放心建求解器的根本理由。

往返精度（G-S1-SF2-1 的 1e-12 判据）：`warp_params_second_order(warp_matrix_second_order(p))` 实测最大误差 **8.7 × 10⁻¹⁸**；`compose_inverse_second_order(p, p) = 0` 实测 **5.1 × 10⁻¹⁷**。

### 2.4 求解器改造：一条求解器，两个阶

没有复制粘贴出第二个求解循环。`icgn.py` 引入 `_ShapeFunction`，把两阶的全部差异收拢为四件事：

| 关注点 | 一阶 | 二阶 |
|---|---|---|
| 单项式基 `basis(dx,dy)` | `(1, dx, dy)` | `(1, dx, dy, dx²/2, dx·dy, dy²/2)` |
| 最速下降图 | `[fx·basis \| fy·basis]`（6 列） | 同式（12 列） |
| 逆合成 | `compose_inverse` | `compose_inverse_second_order` |
| 收敛/条件数缩放 | `diag(1, r, r) ×2` | `diag(1, r, r, r²/2, r², r²/2) ×2` |

缩放向量取各基单项式**在子集角点的幅值**，即把每个参数换算成"子集边缘的像素运动"。这在二阶尤其要紧：原始 Hessian 各列跨越 `1` 到 `r²`，r=15 时是 225 倍，不缩放的话一个完全健康的子集会仅因参数化而显得病态被误杀。`_well_conditioned` 因此由收 `radius` 改为收缩放向量。

对角加载与迹归一同步改为按 `n_params` 而非硬编码 6。

### 2.5 API：三个入口，语义不含糊

- `icgn_first_order(...)` — 恒为 6 参数，**不看** `params.shape_order`（按名索取就必须拿到）。
- `icgn_second_order(...)` — 恒为 12 参数。
- `icgn(...)` — **唯一**按 `ICGNParams.shape_order`（默认 1）派发的入口。

`ICGNParams.shape_order: int = 1` 在 `__post_init__` 校验只能取 1 或 2。派工单给的是"二选一"，这里两个都做了：既有具名入口，也有字段派发；具名入口忽略字段这一点在 docstring 里明写，不做静默行为。

`ICGNResult` 新增 `shape_order`（默认 1，位于所有既有字段之后，构造签名向后兼容）与 `p_labels`。**`v` 属性按阶取列**：一阶第 3 列、二阶第 6 列——这是最容易写错的地方，已有专门测试（`test_second_order_result_has_twelve_labelled_columns` 断言 `result.v` 不等于 `p[:, 3]`）。

`initial_guess` 二阶额外接受 `(n, 6)` 仿射场并以零曲率嵌入，即"先跑一阶、再用其结果播种二阶"的两段式路径；实测播种后平均迭代数 5.04 → 2.04。

---

## 3. 测试方法学：解析二次形变的真值从哪来

### 3.1 为什么不能沿用一阶套件的生成器

`tests/test_icgn_synth.py` 用傅里叶相移生成变形图，解析精确但**只能表达刚体平移**——对二阶形函数毫无信息量。二阶必须在**弯曲**位移场上测。

本套件改用**闭式带限纹理** `h(x,y)`：有限项余弦和，频率填满半径 0.30 cyc/px 的圆盘（远低于 Nyquist，即使被 1 % 应变拉伸后仍安全），幅值按散斑 σ=1.4 px 的高斯包络加权——即高斯相关随机场的截断傅里叶级数。它是二元实变量的普通函数，**可在任意实坐标求值**。

于是把图像对写成

```
target(x, y)    = h(x, y)
reference(x, y) = h(x + u(x,y), y + v(x,y))
```

即恒等地 `reference(x, y) = target(W(x, y))`，**`W` 就是求解器要找的那个 warp，精确到最后一位**，生成器全程零重采样。取 `u, v` 为坐标的二次多项式，则二阶形函数**精确可表示**、一阶形函数按已知量欠拟合——这正是对照实验需要的落差。

在 POI `(x0, y0)` 处把全局二次场展开，六个全局系数解析地给出六个形函数参数（`QuadraticField.params_at`），这是逐点真值：

```
u     = u0 + a1·X0 + a2·Y0 + a3·X0² + a4·X0·Y0 + a5·Y0²
u_x   = a1 + 2·a3·X0 + a4·Y0
u_y   = a2 + a4·X0 + 2·a5·Y0
u_xx  = 2·a3      u_xy = a4      u_yy = 2·a5
```

### 3.2 两个刻意的取舍（如实说明）

1. **点采样而非像素面积积分**。这是 B 样条插值器所对应的采样模型，插值误差因此远低于形函数模型误差，对照实验只测被测的东西。像素积分偏置是一阶套件的职责，本套件不重复。代价：本文数字**不可**当作绝对精度指标外推到真实相机——它们是**两阶之间的相对比较**。
2. **灰度归一取两图联合 min/max 而非百分位**，保证零截断。截断是非线性，会破坏 `reference(x,y) = target(W(x,y))` 恒等式，从而污染真值。

### 3.3 44 项测试覆盖面

| 组 | 项数 | 内容 |
|---|---|---|
| 参数簿记 | 4 | `shape_param_count/labels`、`shape_order` 校验（0/3/−1/1.5 全拒）、`n_shape_params` |
| 二阶代数 | 11 | 往返、矩阵作用于单项式、仿射无截断、自逆归零、与一阶在仿射子群一致、截断界与其二阶收敛、退化增量拒绝、输入校验 |
| 结果对象 | 3 | 12 列布局与标签、`v` 取列正确、`masked`/`status_counts`、空 AOI `(0,12)` 与 `(0,12,12)` 协方差 |
| 精度对照 | 4 | 二次场位移增益、曲率恢复、ZNCC 更优、梯度更优 |
| 一阶已覆盖工况 | 5 | 纯平移、单轴拉伸、平移偏置不劣化 2×、收敛率不劣于一阶、含噪代价 |
| 入口/播种/失败语义 | 17 | `icgn` 派发、`icgn_first_order` 逐位不受 `shape_order` 影响、一阶播种、平移播种、畸形 `initial_guess`、平坦子集、单向纹理、增益/偏移不变性、12×12 协方差、越界、`Status` 编号不变 |

---

## 4. 门禁对账（A 组）

| 门 ID | 判据摘要 | 结论 | 证据 |
|---|---|---|---|
| **G-S1-SF2-1** 代数正确性 | 往返 ≤ 1e-12；`W(p)∘W(p)⁻¹=I`；不精确封闭须写明近似与误差界并锁测 | **pass** | 往返 8.7e-18、自逆 5.1e-17；截断界见 §2.3 三档实测 + `test_the_composition_truncation_is_second_order_and_bounded` |
| **G-S1-SF2-2** 一阶零回归 | `test_icgn_synth.py` 不改一行断言全绿；一阶平移 MAE < 5e-3 px | **pass** | 127 passed，该文件**零改动**（`git show --stat` 可核）；MAE 门由既有 `test_subpixel_translation_recovered` 持有 |
| **G-S1-SF2-3** 二阶精度增益 | 收敛点比例 ≥ 一阶；位移 MAE 低一个写死裕度；纯平移偏置 ≤ 2× 一阶 | **pass** | 25/25 vs 25/25；RMS 6.115e-4 vs 4.050e-2（测试写死 `< rms_first/10`，实测 66×）；平移偏置 u 5.16e-4 vs 5.61e-4（**更小**）、v 4.84e-4 vs 3.90e-4（1.24×，< 2×） |
| **G-S1-SF2-4** 失败语义不变 | `Status` 数值不变；12×12 病态复用 `SINGULAR_HESSIAN`；docstring 更新 | **pass** | `test_status_enum_numbering_is_unchanged` 钉死 9 个值；单向纹理/平坦子集二阶下均返回 `SINGULAR_HESSIAN`（两项专测）；模块 docstring 已改写形函数条目 |

**不属于本代理路径**：G-S1-A2（S 曲线）与 G-S1-A1（位移噪声底）落在 `tests/test_s1_metrology.py` + `benchmarks/metrology/metrics.json`，责任在 IR1-G2 / IR1-G3。本代理已把二阶入口 `icgn_second_order` / `icgn(shape_order=2)` 备妥，可直接被相位扫描与噪声底脚本调用；**本文不代其宣称任何 A1/A2 成绩**。

---

## 5. 代价侧：什么时候不该用二阶

十二个参数由同一批像素拟合，噪声底必然抬高，Hessian 条件数必然变差。这不是缺陷，是参数化的定价，已落测而非口头声明：

| 工况（纯平移，σ=2 灰阶噪声，192×192，subset 31×31，144 POI） | 一阶 | 二阶 |
|---|---|---|
| 有效点比例 | 100 % | 100 % |
| σ(u) 散布 | 0.0033 px | **0.0084 px（2.58×）** |
| bias(u) | +0.0005 px | +0.0005 px |

耗时（160×160、169 POI、r=15）：一阶 1.88 ms/点，二阶 2.13 ms/点（+13 %）。二阶的额外成本不在迭代次数（4.54 → 4.91），而在每次迭代 12 列而非 6 列的 Jacobian 与 12×12 求解。

**选型建议**：

- 位移场在**单个子集内**弯曲时用二阶——弯曲、裂尖邻域、孔边应力集中、大梯度区。
- 场在子集内近似线性时用一阶——这是绝大多数工况，也是 `ICGNParams.shape_order` 默认 1、`icgn()` 默认派发一阶的原因。
- 大变形下先跑一阶再用 `initial_guess=first.p` 播种二阶，把六个新参数约束在合理起点附近（实测迭代 5.04 → 2.04）。

---

## 6. 已知限制（不掩饰）

1. **绝对精度数字不可外推到真实相机**。§3.2 已说明：本套件用点采样而非像素积分，测的是两阶之间的相对落差。真实传感器的像素积分、量化、噪声相关性都不在模型内。
2. **仅在无噪解析二次场上验证过"精确可表示"这一最有利工况**。真实变形场在子集内含三次以上成分时，二阶同样欠拟合，增益会收窄；本套件未测三次场。
3. **未做自适应选阶**。何时切二阶目前是调用方的决定，没有基于残差或条件数的自动判据。
4. **二阶协方差已产出 12×12 且随 σ² 正确缩放，但未做 Monte-Carlo 校核**。一阶的 `Cov ≈ 2σ²(JᵀJ)⁻¹` 论证直接沿用，二阶下的实际覆盖率未验证——测试只锁了"曲率项方差 > 平移项方差"这一定性关系。
5. **未实现邻域/可靠性引导播种**。二阶在大变形下的初值鲁棒性依赖调用方提供一阶场，内核不自动做。
6. **双五次 B 样条未评估**。按 G-S1-F1 的记录性决策纪律，等 G-S1-A2 实测双三次 S 曲线后再定，本代理不预设。

---

## 7. 复跑

```bash
cd <repo-root>
PYTHONPATH=src python3 -m pytest tests/test_icgn_synth.py tests/test_icgn_second.py -q
# 期望：171 passed
```

全量（含兄弟代理路径）：

```bash
CUDA_VISIBLE_DEVICES="" HL3_CI_CPU_ONLY=1 python3 -m pytest -q tests src/tests
```

> 本文写作时全量为 441 passed + 1 failed，唯一失败项是 `tests/test_s1_metrology.py::test_uniform_strain_smoke`。该用例以 `pytest.importorskip("hl3.strain")` 开头：`src/hl3/strain/` 不存在时它 skip，一旦目录存在但尚未导出 `compute_strain`/`local_plane_fit`/`strain_from_displacement` 就 fail。兄弟代理 IR1-O2 的 strain 模块此刻正处于这个中间态，故转红。**与本代理改动无关**：该用例整条路径不触及 `hl3.correlate`；在 IR1-O2 动工前它是 skip，本代理的两次提交都不曾使它由绿转红。

§0 各项数字的复算脚本内联于 `tests/test_icgn_second.py` 的对照测试中，测试断言持有的是**比实测宽一档的门限**（例如实测 66× 增益，断言写死 10×），以便回归时先报警而非先失败。

---

## 8. 文献与法律边界

二阶形函数与其群表示均取自公开文献，仅取**数学表述**，未参考任何实现代码：

- Lu, H. & Cary, P. D. (2000). *Deformation measurements by digital image correlation: implementation of a second-order displacement gradient.* Experimental Mechanics 40(4), 393–400. —— 二次形函数的提出。
- Gao, Y. et al. (2015). *High-efficiency and high-accuracy digital image correlation for three-dimensional measurement.* Optics and Lasers in Engineering 65, 73–80. —— IC-GN2 的 6×6 单项式群表示与逆合成更新式。
- Baker, S. & Matthews, I. (2004). *Lucas-Kanade 20 years on: a unifying framework.* IJCV 56(3), 221–255. —— 逆合成框架本身。

§2.2 的 6×6 矩阵各行系数由本代理**自行推导**（对 `xi²`、`eta²`、`xi·eta` 按总次数 ≤ 2 截断展开），推导结果由 `test_warp_matrix_second_order_applies_the_shape_function` 与 `test_affine_warps_are_represented_without_truncation` 独立校验，不依赖任何文献中的矩阵抄录。

未复制 OpenCorr / Ncorr / DICe 任何代码；未接触 VIC 二进制、专有格式或其输出；本文不含任何"比 VIC 快/准"表述（RUL-03）。无显微镜相关实现（GAP-5 fail-closed）。

---

*IR1-O1 完。本文只写入独占路径 `.agent_workspace/s1s4/IR1-O1-second-order.md`；代码改动仅限 `src/hl3/correlate/**` 与新建 `tests/test_icgn_second.py`（§1 的协作事故除外，已如实登记）。*
