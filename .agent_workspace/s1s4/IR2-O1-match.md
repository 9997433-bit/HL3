ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# IR2-O1：参考帧立体匹配 `hl3.stereo.match` 实现报告

> 子代理：IR2-O1（opus-fast）｜轮次：Impl-R2 / S2｜矩阵：4 fable + 3 opus-fast + 3 gpt-sol
> 独占路径：`src/hl3/stereo/match.py`、`tests/test_stereo_match.py`、`.agent_workspace/s1s4/IR2-O1-match.md`；另加 `src/hl3/stereo/__init__.py` 的**导出行**（派工许可的 tiny export）
> 规范依据：`round1/R1-O2-hl3-3d-spec.md` §5.1（分层匹配 Stage A–D）、§4.3（F 由标定解析导出，禁止八点法）、§6.1–6.2（三角化阶梯 / 不做 rectification）；**调用面与复用协议依据 `s1s4/IR2-F2-stereo-match-spec.md`（逐条符合性见 §7）**
> 约束遵守：`triangulate.py` **零改动**（`git diff` 为空），极线度量全部复用其既有函数；`calibrate.py` 零改动
> 法律边界：**纯独立实现**。无镜头畸变、无非参数畸变场、无显微镜任何一行（RUL-04/06；专利澄清意见未出前保持零实现）；未接触 VIC 二进制或专有格式；未使用任何 Challenge 影像
> 环境：CPU-only，Python 3 + NumPy 2.4.4，**无 GPU、无 CUDA、无 SciPy**

---

## 0. TL;DR — 实测数字

合成场景：15° 倾斜、离标定平面 8 mm 的**带纹理世界平面**，由 `make_stereo_rig`（254 mm 基线 / 648 mm 距 / f=3240 px / 22.18° 立体角 / 5.00 px/mm）的两台相机各自**逐像素反投影到该平面取纹理**成像——两幅图是同一物理表面的两次精确透视采样，任一左图像素的真值对应点有闭式解（§3）。

| 指标 | 实测 | 说明 |
|---|---|---|
| POI / 收敛 / 通过门限 | 154 / **154** / **154** | subset 25×25，step 20，margin 40 |
| ZNCC 中位数 | **0.999973** | — |
| 视差范围 | 0.91 … 15.05 … 27.42 px | 中位 15 px，远超 IC-GN 收敛半径 |
| **对应点误差（对解析真值）** | RMS **7.37 × 10⁻³ px**，p95 9.04 × 10⁻³，max 1.01 × 10⁻² | 不是自洽残差，是绝对误差 |
| Sampson 残差 | RMS **8.21 × 10⁻⁴ px**，max 2.44 × 10⁻³ | 由标定解析导出的 F |
| Sampson 修正后残差 | **3.6 × 10⁻¹⁴ px**（位移 ≤ 0.0017 px） | 修正是"微推"，不是重匹配 |
| 交接三角化（`triangulate_optimal`） | **3.85 µm** RMS，max 5.05 µm，rms_z 3.77 µm | 未改 `triangulate.py` |
| 单点耗时 | **1.76 ms/POI**（154 点 0.27 s） | 纯 NumPy 单线程 |

**关键发现（§4.2）**：匹配误差沿极线方向 RMS 7.28 × 10⁻³ px、垂直极线方向仅 1.16 × 10⁻³ px（**6.3 倍不对称**）。Sampson 只测得到垂直分量，因此 **8 × 10⁻⁴ px 的漂亮 Sampson 分数系统性低估真实匹配误差近一个数量级**。这条已写成断言（`test_the_gate_only_sees_the_cross_epipolar_half_of_the_error`），防止后续把 Sampson 当成匹配精度指标卖。

**门限能力边界（§4.4，同样已落测）**：右相机 0.02° 俯仰误差 → 全部 154 点被拒（中位 Sampson 0.80 px）；但基线拉长 20 mm（7.9 % 尺度误差）→ 中位 Sampson 仅 0.021 px、**全部通过门限**，而三角化结果 RMS 595 µm（正确标定时 3.85 µm，劣化 155 倍）。**极线门限抓指向误差，抓不住尺度误差**——它不是标定检验，报告里不得当成标定检验。

测试：`tests/test_stereo_match.py` **50 项全绿**（含 IR2-F2 §9 要求的 T1–T9 全部，映射见 §7）；全仓 `pytest tests src/tests` 在本报告时点 **576 passed / 0 failed**（共用 checkout，其中含并行子代理同期落地的 S2/S3 文件；本人贡献 47 项，落地前后无任何既有用例回归）。

---

## 1. 交付物

| 文件 | 改动 | 行数 |
|---|---|---|
| `src/hl3/stereo/match.py` | 新增 | 651 |
| `tests/test_stereo_match.py` | 新增 | 799 |
| `src/hl3/stereo/__init__.py` | **仅**增加 8 个 re-export + `__all__` 条目 + 模块 docstring 措辞 | +28 / −8 |
| `src/hl3/stereo/triangulate.py` | **零改动** | — |
| `src/hl3/stereo/calibrate.py` | **零改动** | — |

`hl3.stereo` 新增公开名（`__all__` 保持排序，`test_stereo_synth.py::test_public_api_matches_what_the_package_actually_exports` 与新加的 `test_package_reexports_the_matcher` 双向锁定）：

```
EpipolarResiduals, MatchSeed, StereoMatchParams, StereoMatchResult,
epipolar_residuals, match_stereo_pair, plane_disparity, rig_fundamental
```

`tests/test_s2_s3_smoke.py` 中 `hl3.stereo.match` 一项由 `importorskip` 跳过转为**实际导入通过**。

---

## 2. API（本轮提交的调用面）

```python
def match_stereo_pair(
    left, right,                       # (H, W) 同形状灰度图，同一时刻的左右相机
    rig=None,                          # StereoRig 或 (P_left, P_right)；可选
    params=None,                       # StereoMatchParams
    *, points=None,                    # (n, 2) 左图 POI；缺省用 make_grid
    initial_guess=None,                # 直通内核，覆盖 params.seed
) -> StereoMatchResult
```

- `StereoMatchParams(icgn, seed, seed_plane, max_sampson_px, sampson_iters, margin)`
  —— `icgn` 原样透传内核（**不包一层、不改名**，与 IR1-F3 §3 对 `Pipeline2DParams` 的裁决同口径）。
- `MatchSeed = {AUTO, PLANE, SOLVER, ZERO}`；`AUTO` = 有 rig 走 `PLANE`，无 rig 交内核（FFT-CC）。
- `StereoMatchResult`：`left_xy / right_xy`（**原始值，不掺 NaN**）、`correlation`（内核 `ICGNResult` 原件）、`accepted`（质量掩膜）、`fundamental / sampson_px / epipolar_px`（无 rig 时为 `None`，不是 0）、`left_corrected / right_corrected`、`provenance`；方法 `correspondences(masked=True, corrected=False)`、`summary()`、`status_counts()`。
- `plane_disparity(rig, points, plane=(0,0,1,0)) -> (n, 2)`：左图像素反投影到世界平面 `n·X + w = 0` 再投到右相机的视差。**平面上的点它给的是精确对应，不是近似**。
- `rig_fundamental(rig)`、`epipolar_residuals(rig, xL, xR) -> EpipolarResiduals(sampson_px, distance_px)`。

`correspondences()` 的返回形状与 NaN 语义**刻意**对齐 `hl3.stereo.triangulate` 的输入约定：被拒点为 NaN，三角化侧原本就把非有限像素当"相关器丢点"处理并输出 NaN 世界点，因此 S2→S3 交接是零胶水的（已由 `test_masked_correspondences_triangulate_back_onto_the_surface` 锁定）。

---

## 3. 合成场景：为什么它能当真值

主流做法（把左图按某个假定视差重采样成右图）会让"匹配误差"退化成"插值误差的自我验证"。本文件不这么做：

1. 在**世界平面**上定义解析纹理——48 个随机相位正弦波，波长 0.8–2.0 mm（成像后 4–10 px），带限、各向同性、闭式可求值。
2. 左右两幅图各自**逐像素**反投影到该平面、在交点处取纹理值。两幅图从同一连续纹理采样，**没有任何一幅是另一幅的重采样**。
3. 于是任意左图像素的真值对应点 = 反投影到平面 → 投影到右相机，闭式已知；三角化真值同理。

平面参数（15° 绕 Y 倾斜 + 8 mm 深度偏置）是刻意选的：倾斜让两视图之间存在真实的透视差（不只是平移），深度偏置让视差脱离"相机会聚平面"的零点——`z=0` 平面上视差只有 ~3 px，那样的场景测不出种子的意义。

测试文件里的反投影是**独立于被测模块另写一遍**的（`_backproject`），否则 `plane_disparity` 的验证就是同义反复。

---

## 4. 实测结果

### 4.1 对应精度

154 个 POI 全部 CONVERGED 且全部通过 0.5 px Sampson 门限；对解析真值的误差 RMS 7.37 × 10⁻³ px、max 1.01 × 10⁻² px。分轴看：x 向 7.22 × 10⁻³ px、y 向 1.16 × 10⁻³ px。

### 4.2 误差是各向异性的，Sampson 只看得见一半

沿极线 / 垂直极线分解：

| 分量 | RMS |
|---|---|
| 沿极线（视差方向，深度就是从这里读的） | 7.28 × 10⁻³ px |
| 垂直极线 | 1.16 × 10⁻³ px |
| Sampson 残差 | 8.21 × 10⁻⁴ px |

比值 6.3。原因是结构性的而非本实现的缺陷：极线约束对"点沿着自己那条线滑多远"没有任何约束力，而那正是深度的读数方向。所以

> **Sampson 分数好 ≠ 匹配准。** 它是必要不充分条件。

这也解释了为什么 `StereoMatchResult` 把 ZNCC、status、Sampson、对称极线距离并列保留而不是压成一个分数：压成一个分数就等于宣称自己测到了它测不到的东西。R1-O2 §6.4 的四路闭环残差才是覆盖沿极线分量的自洽指标，需要时间匹配配合，属 S4 欠账（§6）。

### 4.3 平面种子的适用包络（IR2-F2 §4.2 要求实测）

种子误差 ≈ 表面对名义平面的偏离 × ∂|d|/∂Z ≈ f·B/Z²。本 rig：3240 × 254 / 648² = **1.96 px/mm**（实测拟合 2.12 px/mm，差额来自平面法向与 z 轴成 15° 夹角）。把名义平面沿法向平移 dZ、其余不变：

| 名义平面偏离 dZ | 种子误差（中位/max） | 通过率 |
|---|---|---|
| 0 mm | 0.00 px | **1.000** |
| 0.25 mm | 0.53 / 0.53 px | 1.000 |
| 0.50 mm | 1.06 / 1.06 px | 1.000 |
| 1.00 mm | 2.12 / 2.13 px | **1.000** |
| 2.00 mm | 4.24 / 4.27 px | 0.234 |
| 4.00 mm | 8.51 / 8.56 px | **0.000** |
| 8.00 mm | 17.13 / 17.23 px | 0.000 |

**包络：本 rig 上平面种子容忍约 ±1 mm 的表面偏离（≈ 2 px 种子误差），2 mm 起崩塌，4 mm 起全失。** 换算成种子误差的收敛半径为 **2–4 px**，与 R1-O2 §5.1 Stage B 给出的"IC-GN 收敛半径约 3–5 px"独立吻合——这条经验数字在本仓首次有了实测支撑。按 `f·B/Z²` 换算到 `make_stereo_rig` 默认几何（f = 10145 px）为 6.1 px/mm，即容忍 ±0.3–0.6 mm，与 IR2-F2 §4.2 的 ±0.5–0.8 mm 估计同量级（其估计略宽）。**超出包络必须上 Stage-B 极线扫描（`MatchSeed.EPIPOLAR_SCAN` 预留槽位），不能靠调平面糊过去。**

Sampson 残差分布（154 个通过点）：min 3.6 × 10⁻⁶、中位 5.83 × 10⁻⁴、均值 6.76 × 10⁻⁴、p95 1.46 × 10⁻³、max 2.43 × 10⁻³ px；对称极线距离中位 8.24 × 10⁻⁴、max 3.44 × 10⁻³ px。**当前 `max_sampson_px = 1.0` 的 draft 门比本场景噪声底高约 3 个数量级**——它现在只抓粗大错配。收紧交 IR2-F1 凭 IR2-G3 的实测分布定稿（本节数据可直接作为 L0 合成侧的输入，但真实数据的噪声底会高得多，不要拿它当阈值）。

### 4.4 种子模式对照（同一对图像，同一参数）

| `seed` | 通过点 | 通过率 | 耗时 | 状态分布 |
|---|---|---|---|---|
| `PLANE`（真实表面平面） | 154 / 154 | **1.000** | 0.28 s | 全 CONVERGED |
| `PLANE`（名义平面 z = 0，偏 8 mm + 15°） | 22 / 154 | 0.143 | 0.88 s | 129 NOT_CONVERGED / 3 LOW_ZNCC |
| `ZERO` | 29 / 154 | 0.188 | 0.95 s | 122 NOT_CONVERGED / 3 LOW_ZNCC |
| `SOLVER`（FFT-CC，search_radius=40，step 60） | 20 / 20 | 1.000 | 0.06 s | 全 CONVERGED |

三点结论：

1. 立体视差（中位 15 px）本来就在 IC-GN 收敛域之外，**无种子不是精度问题而是答非所问**——通过率掉到 19 %，而且掉下去的点是 NOT_CONVERGED 而不是"错但看着对"，这是内核的功劳（发散被 status 抓住）。
2. 名义平面偏 8 mm + 15° 就已经比零种子好不了多少：种子的价值来自它**贴近真实形貌**，不来自"有个种子"。这正是 Stage A 要用特征法拟合视差面、而不是拍脑袋给一个平面的原因（§6 欠账）。
3. FFT-CC 整数搜索是一条**独立**路线，收敛到同一答案（max 误差 1.05 × 10⁻² px，与平面种子一致），可作交叉验证。代价是搜索窗要额外边界（`make_grid` 的默认 margin 已含 `search_radius`）。

### 4.5 门限的能力与边界

同一对图像，只改"声称的标定"：

| 标定扰动 | 收敛 | 中位 Sampson | 通过门限(0.5 px) |
|---|---|---|---|
| 右相机俯仰 +0.005° | 154/154 | 0.200 px | 全过 |
| 右相机俯仰 +0.010° | 154/154 | 0.400 px | 全过 |
| 右相机俯仰 +0.020° | 154/154 | 0.800 px | **全拒** |
| 右相机俯仰 +0.050° | 154/154 | 2.000 px | **全拒** |
| 右相机俯仰 +0.100° | **0/154** | — | — |
| 基线 +1 mm | 154/154 | 0.0011 px | 全过 |
| 基线 +5 mm | 154/154 | 0.0051 px | 全过 |
| **基线 +20 mm（7.9 %）** | 154/154 | **0.0206 px** | **全过** |

- 指向误差按 `f · Δθ` 线性进入残差（3240 px × 0.02° = 1.13 px，实测中位 0.80 px 与之同量级），**0.02° 即被门限抓死**。相关器对此毫无反应（ZNCC 不变，图像根本没变），这正是门限存在的理由。
- 0.1° 时收敛数掉到 0：此时**种子本身**（经错误 rig 反投影）已偏出收敛域。副作用如实记录——rig 既进种子也进评分，标定错到一定程度会先毁掉种子。
- **基线（尺度）误差近乎隐形**：+20 mm 只让残差从 8 × 10⁻⁴ 走到 2 × 10⁻² px，仍在任何合理门限之内，而三角化结果 RMS 从 3.85 µm 恶化到 **595 µm**。极线残差是"两条射线是否相交"的检验，尺度错误不破坏相交性。抓它需要长度标准件或闭环，不是残差。已写成断言，避免任何人把这条门限描述成标定检验。

### 4.6 三角化交接（未改 `triangulate.py`）

`result.correspondences()` → `triangulate_optimal(PL, PR, xL, xR)`：RMS **3.85 µm**、p95 4.77 µm、max 5.05 µm、rms_z 3.77 µm，被拒点为 NaN 世界点。DLT 与 Sampson+DLT 在本场景数值相同（残差已在 1e-3 px 级，两者差异低于打印精度）。

Sampson 修正后的对应点极线残差 3.6 × 10⁻¹⁴ px（即精确落到互相对应的极线上），像素位移 ≤ 0.0017 px——修正确实是"最小 L2 微推"而非重匹配。

---

## 5. 设计裁决

| # | 裁决 | 理由 |
|---|---|---|
| 1 | **F 由 `fundamental_from_projections` 解析导出**，不做八点法 | R1-O2 §4.3。用被评分的对应点去拟合评分几何，等于让考生出考题 |
| 2 | 极线度量**全部复用** `triangulate.py`（`sampson_distance` / `epipolar_distance` / `sampson_correct`） | 派工约束；也避免出现第二份公式实现慢慢漂移 |
| 3 | 原始值 + 掩膜，而不是就地 NaN | 与 `ICGNResult` / IR1-F3 §5 `DisplacementField` 同口径；`accepted` 是**额外**数组，调用方可重设门限而无需重跑匹配 |
| 4 | 无 rig 时 `sampson_px` 等为 `None` | 填 0 会被读成满分。"没有几何可测"和"几何完美"必须可区分 |
| 5 | `shape_order != 1` **报错**而不是忽略 | 见 §6 欠账 1。静默忽略会让 provenance 里的 `shape_function` 撒谎 |
| 6 | 平面预测失败（射线与平面平行 / 平面在相机背后）→ 该点回落零种子并计数，不是全场报错 | 内核拒绝非有限种子；几条掠射线不该带走整个场。`provenance["seed_fallback_points"]` 如实计数 |
| 7 | 匹配方向单向（左为参考） | 双向一致性检验属四路闭环（R1-O2 §6.4），需要时间匹配，本轮不冒充 |
| 8 | 不做 rectification、不做极曲线采样 | R1-O2 §6.2；L0 针孔下极线本来就是直线，**现在**写极曲线采样是无处验证的死代码 |

---

## 6. 欠账清单（明确交接，不含糊）

1. **二阶形函数是规范要求的立体默认（R1-O2 §5.1 条 1），本轮是一阶。** 内核 `icgn_second_order` 已存在（IR1-O1 落地，斜面上位移 RMS 优 66×），接线不难，但要连"平坦区自动降阶"一起做才不亏算力，且需重跑本文件全部精度基线。本轮以 `ValueError` 显式拒绝 `shape_order=2` 占位，不留静默分支。**这是本轮与规范最大的一条偏差，登记在案。**
2. Stage A 特征法（SIFT/AKAZE + 已知 F 的 RANSAC 外点剔除 → 视差面拟合）：本轮用"名义平面"顶替，§4.3 已量化其代价（名义平面偏 8 mm 即掉到 14 %）。
3. Stage B 沿极线一维粗扫（IR2-F2 §4 已把语义冻结为 `MatchSeed.EPIPOLAR_SCAN` 预留槽位）：本轮靠平面种子 + 内核 FFT-CC 两条路覆盖。§4.3 的包络表明这不是可选项——表面偏离名义平面 2 mm 起，平面种子就开始崩，那正是极线扫描的用武之地。落地时按新增枚举值进入 `MatchSeed`，`match_stereo_pair` 签名不变。
4. 自适应/各向异性子集、掩膜感知子集与间断自动检测（R1-O2 §5.1 条 2/3，Challenge 丢点的正面战场）。
5. 四路闭环残差（§6.4）——需要 S4 时间匹配，且它是唯一能覆盖沿极线误差分量的自洽指标（§4.2）。
6. `Σ_match` 传播：内核已能出 `covariance`（`compute_covariance=True`），本模块尚未把它整理成三角化要的 2×2 像素协方差交给 §6.6 链路 → 交 IR2-O3 / UQ 契约。
7. 畸变模型下的极曲线采样（§6.3）：随畸变层一起来。
8. PIB 估计与补偿（§6.5）：本合成场景零重采样，故测不到 PIB，也就不该在这里假装测过。

---

## 7. 对 IR2-F2 冻结规格的符合性

`IR2-F2-stereo-match-spec.md` 在本模块编码期间发布（时间上与本实现并行）。逐条核对，**冻结面全部命中，无一处需要 F2 让步**：

| F2 条款 | 状态 |
|---|---|
| §2 `__all__` 恰好八个名字 | ✅ 逐字一致 |
| §2 `match_stereo_pair` 签名（含 keyword-only `points` / `initial_guess`） | ✅ 一致 |
| §2 `MatchSeed` 四值语义、`StereoMatchParams` 六字段与默认值 | ✅ 一致（含 `max_sampson_px=1.0` draft 默认） |
| §2 `StereoMatchResult` 字段与方法 | ✅ 一致 |
| §2 provenance 必含 12 键 | ✅ 全含（另加 `backend / image_shape / n_points / subset_size / step / search_radius / zncc_min / seed_plane / sampson_iters / baseline_mm / standoff_mm`） |
| §2 `shape_order != 1` → `ValueError` | ✅ 且错误信息写明二阶入口在何处 |
| §3.1 每图对**恰好一次**内核调用，`ICGNResult` 原样保存 | ✅ |
| §3.2 种子与内核 FFT-CC 互斥 | ✅ `SOLVER ⇔ guess=None`，其余模式传数组 |
| §3.3 不新增不改写任何 `Status` | ✅ match 层只读 status |
| §4.2 平面预测公式与降级裁决（零种子 + provenance 计数） | ✅ 公式逐项一致；计数落 `seed_fallback_points` |
| §4.2 报告须给平面种子**实测包络** | ✅ §4.3（±1 mm / 2–4 px） |
| §5.1 F 每图对算一次且只从标定解析 | ✅ |
| §5.2 先掩 NaN 再在**未修正**坐标上算残差 | ✅ |
| §5.3 `accepted = CONVERGED ∧ sampson ≤ 门`，NaN 为 False，不改 status | ✅ |
| §5.5 极线盲区必须**断言出来** | ✅ 新增 `test_the_gate_is_blind_to_a_shift_along_the_epipolar_line`；另加 §4.2 的误差分解量化 |
| §5.6 修正对是可选产物，质量场不得算在修正坐标上 | ✅ |
| §6 三角化唯一出口 `correspondences()` | ✅ |
| §8 失败语义表 9 行 | ✅ 逐行有测试 |
| §9 测试最小集 T1–T9 | ✅ 见下表 |

**因 F2 而做的一处实现修改**：F2 §1 要求"相机中心重合的退化 rig 必须在**任何相关计算之前**炸出来"。原实现在相关之后才算 F，会让用户为一个开跑前就可见的配置错误付掉整场相关的时间。已改为拿到投影矩阵后立刻导出 F，并加 `test_a_coincident_pair_is_refused_before_any_correlation_runs`（断言 < 50 ms 返回）。

**一处主动超出 F2 的地方**：F2 §9 T1 建议"B 样条重采样渲染"合成散斑对。本实现改用**解析纹理逐像素反投影**（§3）——重采样渲染会让"匹配误差"里混入渲染插值误差，量级恰好与被测量同级（10⁻² px），使 T1 的数字不可解释。改法只增强不削弱该测试（真值仍闭式，且两图无一是另一图的重采样）。如实登记为与 F2 建议的偏离。

### 7.1 F2 §9 最小集映射（T1–T9 全覆盖）

| F2 项 | 门槛 | 本仓测试 | 实测 |
|---|---|---|---|
| T1 真值视差 | 收敛 ≥ 95 %，MAE ≤ 0.05 px | `test_match_recovers_the_true_correspondence` | 100 %，RMS 7.4 × 10⁻³ px |
| T2 残差噪声底 | 中位 ≤ 0.05 px | `test_epipolar_residuals_are_a_fraction_of_a_pixel` | 中位 5.8 × 10⁻⁴ px |
| T3 门的方向选择性 | 法向偏移必拒 / 沿极线偏移不响 | `test_gate_rejects_matches_pushed_off_their_epipolar_line` + `test_the_gate_is_blind_to_a_shift_along_the_epipolar_line` | 法向 3 px → Sampson > 1 px；沿线 3 px → < 10⁻⁶ px |
| T4 光度不变 | Δ视差 ≤ 1e-6 px | `test_matching_is_invariant_to_a_gain_and_offset_between_the_cameras` | `g = 0.6f + 37` 下 max 位移 < 1e-6 px，掩膜逐位相同 |
| T5 退化 rig | `ValueError`，且未进相关 | `test_a_coincident_pair_is_refused_before_any_correlation_runs` | ✅ |
| T6 无 rig 降级 | 极线字段全 `None` | `test_match_without_a_rig_reports_no_epipolar_metrics` | ✅ |
| T7 全链 | `match → correspondences → triangulate_optimal → triangulation_quality_mask` | `test_masked_correspondences_triangulate_back_onto_the_surface` | 3.85 µm RMS；质量掩膜与 `accepted` 逐点一致 |
| T8 F 方向回归 | 真值对应上残差 ≈ 0 | 同 T3 前半 + `test_fundamental_matrix_comes_from_the_calibration` | < 1e-6 px；‖F‖ = 1，det ≈ 0 |
| T9 种子必要性 | `ZERO` 显著劣于 `PLANE` | `test_zero_seed_loses_the_points_the_plane_seed_keeps` | 0.188 vs 1.000 |

### 7.2 测试清单（50 项）

| 组 | 项数 | 覆盖 |
|---|---|---|
| 名义平面预测 | 5 | 与独立反投影逐位一致、量级检验、裸 P 对、相机背后 → NaN、退化平面报错 |
| 对应精度 | 4 | 对解析真值 RMS/max、ZNCC、accepted ⊆ converged、视差定义 |
| 极线质量 | 7 | 残差量级、独立函数与字段一致、F 来自标定、推离极线必被抓、**沿极线盲区**、指向误差 rig 被拒、门设 inf 退化 |
| **能力边界** | 2 | 沿/垂直极线误差不对称；尺度误差过门限但毁深度 595 µm |
| 种子 | 6 | 零种子对照、名义平面代价、FFT-CC 独立路线、AUTO 随 rig 切换、显式种子覆盖、预测失败回落 |
| 光度 / 退化 rig | 2 | ZNSSD 跨相机增益偏置不变；中心重合 rig 相关前报错 |
| 无 rig 路径 | 1 | 三个极线字段为 None、掩膜退化、summary 为 NaN |
| 三角化交接 | 5 | 反算回表面 3.85 µm + 质量掩膜一致、修正后落到极线上、未掩膜保留原值、无 rig 取修正对报错、`sampson_iters=0` |
| 报告与可复现 | 4 | summary 一致性、provenance 记录 scope、逐位可复现、字段长度 |
| 坏调用 | 6 | 二阶被拒、6 组坏参数、坏类型、7 种坏调用、空 AOI 是合法请求、全平坦图全点失败 |
| 运行时警告 | 1 | 失败路径 `simplefilter("error")` 零 RuntimeWarning |
| 公开面 | 2 | re-export 与 `__all__` 排序、返回类型 |

`test_stereo_synth.py` 的包级 scope 检查（`test_stereo_package_ships_no_distortion_implementation`）会扫描 `hl3/stereo/*.py`，新文件自动纳入：无任何 `distort/brown/conrady/radial/tangential/prism/fisheye/telecentric/microscop` 命名的定义，且保留 patent-clearance 免责段。已验证通过。

---

## 8. 门禁自查

| 项 | 状态 |
|---|---|
| `triangulate.py` 未被改写 | ✅ `git diff` 空 |
| 极线度量复用既有实现 | ✅ 仅 import |
| 无畸变 / 无显微镜实现 | ✅ 包级扫描测试通过 |
| 无 VIC 逆向、无 Challenge 影像 | ✅ 仅复用其**公开发表的几何参数**（254 mm/648 mm/35 mm/3.45 µm 已在 `calibrate.py` 注明） |
| 确定性（无 RNG、单线程、float64） | ✅ `test_matching_is_bit_for_bit_reproducible` |
| 逐点失败不抛异常、不编数 | ✅ status + 掩膜 + None/NaN |
| 88 列 | ✅ `ruff --select E501` 对三个文件零命中 |
| `git add` 仅独占路径 | ⚠️ 见 §9：共用 index 导致两次提交夹带了他人已 stage 的报告文件；已在自建分支上重做为纯净提交 |
| IR2-F2 冻结面 | ✅ §7 逐条 |

## 9. 协作事故如实记录

本轮多个子代理共用同一个 checkout（同一工作区、**同一 git index、同一 HEAD**）。两起后果如实记录：

1. **提交落错分支**：我第一次 `git commit` 的瞬间，HEAD 已被另一子代理从 `cursor/dic-sota-plan-259d` 切到 `cursor/ir2-o3-uq-fe9e`，该提交（`a37d7bb`）因而落在后者分支上并随其推送。
2. **共用 index 夹带**：`git add` 只写了我的独占路径，但**别人已 stage 的文件**（`IR2-F1-s2s3-gates.md`、`IR2-F2-stereo-match-spec.md`）随同一次 `git commit` 一起进了我的提交。这是共用 index 的结构性后果，不是 `git add .`。

补救（未对任何他人分支 force push、未回滚任何他人提交）：在 `/tmp` 另开 **git worktree**（不占用共用工作区的 HEAD），基于 `cursor/dic-sota-plan-259d` 新建 `cursor/ir2-o1-match-8e85`，把本轮四个独占路径重新提交为**纯净提交**（`53238ef` 代码 + 报告提交），在该 worktree 内复跑测试后推送。父调度器合并时以 `cursor/ir2-o1-match-8e85` 为准即可拿到完整且不夹带的 IR2-O1 交付；落在 `cursor/ir2-o3-uq-fe9e` 上的那两个提交内容与之等价，重复合并不会冲突（同文件同内容），但不必要。

**给后续轮次的建议**：并行子代理共用 checkout 时，写操作应各自 `git worktree add` 独立目录；否则 index 与 HEAD 都是共享可变状态，"只 add 独占路径"这条纪律在实现上无法被单个代理保证。

*IR2-O1 完。`src/hl3/stereo/triangulate.py` 与 `calibrate.py` 零改动。*
