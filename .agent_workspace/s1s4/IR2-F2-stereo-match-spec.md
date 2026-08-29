ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR2-F2 · S2 立体匹配复用规格：`icgn_first_order` 做左→右匹配 + 解析 F 的极线残差

- **子代理**：IR2-F2（fable，云端）｜Impl-R2 / 10 代理（4 fable + 3 opus-fast + 3 gpt-sol）
- **日期**：2026-08-28
- **输入**：`s1s4/IR2_DISPATCH.md`、`round1/R1-O2-hl3-3d-spec.md` §4.3/§5/§6、`src/hl3/correlate/icgn.py`（S1 内核，含 `icgn_first_order` / `icgn_second_order`）、`src/hl3/stereo/triangulate.py`（`fundamental_from_projections` / `sampson_distance` / `epipolar_distance` / `sampson_correct`）、`src/hl3/stereo/calibrate.py`（`StereoRig`）、`src/hl3/pipeline/dic2d.py`（内核复用先例）
- **本文冻结的对象**：S2 参考帧左→右立体匹配的**复用协议**（内核怎么调、种子从哪来、极线残差怎么算怎么门）与 `hl3.stereo.match` 的**调用面**。
- **本文不冻结的对象**：内核数值语义（效力归 R1-O1 §2 / R2-O1）；极线几何与三角化数值语义（效力归 R1-O2 §4.3/§6 与 `triangulate.py` 既有实现）；各 draft 阈值的最终数值（归 IR2-F1 门禁文档，凭 IR2-G3 实测分布定稿）。
- **约束对象**：IR2-O1（`src/hl3/stereo/match.py`、`tests/test_stereo_match.py`）、IR2-O2（`src/hl3/pipeline/dic3d.py` 只准消费 §2 冻结面）、IR2-F1（阈值定稿）、IR2-G3（metrics 落数）。
- **法务**：独立实现公开算法（Jiang OLE 2023 / Lin OLE 2021 的极线约束立体 DIC 属公开文献方法族）；零显微镜实现（RUL-04/L-7）；无"比 VIC 快/准"表述（RUL-03）；不接触任何商业码二进制。

---

## 0. 复用论证：为什么 `icgn_first_order` 一行不改就能做跨相机匹配（规范性）

立体匹配和时间匹配在内核眼里是同一个问题：给定一张"参考"、一张"目标"、一组 POI，求每个子集的仿射 warp。内核从未假设两张图来自同一台相机，逐条对照：

| 立体匹配的需求 | 内核既有能力（证据） |
|---|---|
| 左右相机增益/偏置/渐晕不同 | ZNSSD 对 `g = a·f + b (a>0)` **精确不变**（`icgn.py` 模块 docstring；跨相机光度差正是这条不变性的用武之地） |
| 两视图间存在真实透视畸变 | 局部平面片的左→右映射是单应，其对子集中心的一阶泰勒展开恰是仿射——6 参数形函数承接；斜面上的系统性欠匹配作为已知偏差登记于 §7 |
| 视差达数十至数百 px，远超收敛域 | `initial_guess` 入口已有：`(n, 2)` 视差或 `(n, 6)` warp 逐点种子（`_resolve_initial_guess`） |
| 逐点失败不炸场 | 9 态 `Status` 枚举 + fail-closed 纪律，空 AOI / 越界 / 平坦子集全有定义行为 |
| 匹配质量的独立体检 | `fundamental_from_projections` 从标定**解析**求 F（spec S4.3：绝不从对应拟合），`sampson_distance` / `epipolar_distance` 现成 |

**冻结裁决**：

1. **角色映射**：`reference = 左图`，`target = 右图`，`points = 左图 POI`。收敛后 `(u, v) = (p[:, 0], p[:, 3])` 即视差向量 `d = x_R − x_L`，`x_R = x_L + d`。
2. **内核零修改**。若 S2 发现必须改 `hl3/correlate/icgn.py` 才能做立体，先停下写 ADR——那说明复用论证有洞，不许用补丁掩盖。
3. **每图对恰好一次内核调用**（对全部 POI 批量），不允许逐候选、逐点循环调 ICGN。种子的搜索开销只准花在廉价的几何预测/整数 ZNCC 上（§4）。
4. 视差是**二维向量**：不做 rectification（R1-O2 §6.2，重采样 = 额外一次 PIB 注入），故没有"视差只有水平分量"的假设；极线约束**只做事后诊断，不进代价函数**（§5 的独立性论证正建立在此上）。

## 1. 几何与方向约定（全部冻结）

- **左相机为主相机**：POI 网格、后续时间匹配与应变网格都锚定左参考图；对应关系按构造是单向（左→右）的。
- **F 的方向**：`F = fundamental_from_projections(P_left, P_right)` ⇔ `x̃_R^T F x̃_L = 0`；右图中对应 `x_L` 的极线是 `l_R = F @ x̃_L`。参数顺序即语义，必须有回归测试锁定（§9 T8）。
- `fundamental_from_projections` 返回单位 Frobenius 范数的 F；`epipolar_distance` / `sampson_distance` 对 F 的整体缩放**不变**（分子分母同乘），所以归一化不影响任何以 px 计的残差。
- 相机中心重合的退化 rig 在 `fundamental_from_projections` 处 `ValueError`——这是配置错误不是测量失败，必须在任何相关计算**之前**炸出来。
- 所有残差单位为像素；世界量单位 mm（与 `triangulate.py` 约定一致）。

## 2. 冻结的调用面：`hl3.stereo.match`

`__all__` 恰好八个名字：`match_stereo_pair`、`StereoMatchParams`、`StereoMatchResult`、`MatchSeed`、`plane_disparity`、`rig_fundamental`、`epipolar_residuals`、`EpipolarResiduals`。

```python
def match_stereo_pair(
    left, right,                    # (H, W) 同形状灰度图，同一时刻两相机
    rig=None,                       # StereoRig | (P_left, P_right) | None
    params=None,                    # StereoMatchParams | None
    *,
    points=None,                    # (n, 2) 左图 POI；None → make_grid(left.shape, params.icgn)
    initial_guess=None,             # (n, 2) 视差或 (n, 6) warp；给出即覆盖 params.seed
) -> StereoMatchResult
```

```python
class MatchSeed(enum.Enum):
    AUTO = "auto"      # 有 rig → PLANE，无 rig → SOLVER
    PLANE = "plane"    # 名义平面预测（§4），需要 rig
    SOLVER = "solver"  # guess=None 交给内核：icgn.search_radius > 0 时 FFT-CC
    ZERO = "zero"      # 零视差起步；只对近零基线 rig 与测试对照有意义

@dataclass(frozen=True)
class StereoMatchParams:
    icgn: ICGNParams = ICGNParams()          # 原样透传内核，不摊平不重命名
    seed: MatchSeed = MatchSeed.AUTO
    seed_plane: tuple = (0., 0., 1., 0.)     # n·X + w == 0，mm；默认 z=0 即 make_stereo_rig 的瞄准面
    max_sampson_px: float = 1.0              # 极线门；inf 关闭几何门（数值为 draft，IR2-F1 定稿）
    sampson_iters: int = 10                  # 0 = 不产出修正对
    margin: int | None = None                # None → make_grid 默认边距
```

```python
@dataclass(frozen=True)
class StereoMatchResult:
    left_xy: np.ndarray        # (n, 2) 左图 POI（原始值）
    right_xy: np.ndarray       # (n, 2) = left_xy + (u, v)（原始值，不掺 NaN）
    correlation: ICGNResult    # 内核返回值原样保存，不重排不改写
    accepted: np.ndarray       # (n,) bool = 收敛 ∧ 极线门（§5）
    params: StereoMatchParams
    provenance: dict
    fundamental: np.ndarray | None    # 无 rig 时 None，绝不填零
    sampson_px: np.ndarray | None     # (n,) 默认质量场（S4.3）
    epipolar_px: np.ndarray | None    # (n,) 对称点-极线距离，直观对照场
    left_corrected / right_corrected: np.ndarray | None   # Sampson 修正对（可选产物）

    disparity: (n, 2)  # right_xy − left_xy
    status / zncc      # 转发 correlation
    valid: (n,) bool   # 仅收敛判据（几何门前）
    def correspondences(masked=True, corrected=False) -> (x_left, x_right)  # 喂三角化的唯一出口
    def summary() -> dict   # n_points / n_accepted / zncc 中位 / sampson rms·p95·max …
```

冻结条目：

- **原始值 + 掩膜**口径与 IR1-F3 §5 一致：`left_xy` / `right_xy` 永远保存内核产出的原始数，`accepted` 单独说话；要 NaN 版走 `correspondences(masked=True)`。
- **无 rig 是定义过的降级**，不是错误：仍返回对应，但 `fundamental` / `sampson_px` / `epipolar_px` / 修正对全为 `None`（填零会读成满分），`accepted` 退化为"内核收敛"。
- `params.icgn.shape_order != 1` → `ValueError`。静默忽略该字段会误报产出结果的形函数；二阶接入路径见 §7。
- `points` 必须有限；左右图形状必须一致（内核校验）。异构传感器 rig 是非目标（§10）。
- 纯函数：不碰文件、无 RNG、单线程 float64，同输入逐位可复现。
- `provenance` 至少含：`stage / solver / shape_function / criterion / interpolation / rectified=False / distortion_model="none_pinhole_l0" / seed / seed_fallback_points / max_sampson_px / has_rig / epipolar_source="analytic_from_projections"`。

## 3. 内核调用协议（规范性）

1. **一次调用**：`icgn_first_order(left, right, poi, params.icgn, guess)`。返回值原样进 `StereoMatchResult.correlation`——下游要能拿到与直接调内核逐位相同的数。
2. **种子与内核搜索互斥**：`initial_guess is not None` 时内核的 `_resolve_initial_guess` 提前返回，FFT-CC 不可达。因此 `SOLVER` 种子 ⇔ `guess=None`；其余种子模式下 `icgn.search_radius` 惰性。两条路径不得混用叠加。
3. 逐点失败语义完全沿内核：越界 = `OUT_OF_BOUNDS`、平坦/单向纹理 = `SINGULAR_HESSIAN`、种子太差 = `NOT_CONVERGED`/`DIVERGED`。match 层**不新增、不改写任何 `Status` 值**（枚举编号已冻结，R2-O1 §2.7）。
4. 大视差下右图子集贴近图缘的 POI 会以 `OUT_OF_BOUNDS` 逐点退出而非炸场——这是预期行为，测试须覆盖而非规避。

## 4. 种子分层（规范性 + 适用包络）

视差在收敛 rig 上是数十到数百 px，即远超 IC-GN 收敛域（约 3–5 px，R1-O2 §5.1 Stage B 的步长依据）。无种子求解不是"精度差一点"，是**回答错误的问题**。优先级从高到低：

1. **调用方显式 `initial_guess`**：原样透传，覆盖 `params.seed`（研究与管线均需此逃生口）。
2. **`PLANE`（有 rig 的默认）**——R1-O2 §5.1 Stage A（特征 + 视差面）的廉价替身：把每个左像素反投影到名义世界平面，再投进右相机。

   `M = P_L[:, :3]`，`C_L = −M⁻¹ P_L[:, 3]`，射线 `r = M⁻¹ x̃_L`，`λ = −(w + n·C_L)/(n·r)`，`X = C_L + λ r`，`d⁰ = π(P_R, X) − x_L`。

   表面真在平面上时这是**精确**对应而非近似，求解器要消掉的残差只剩表面对平面的偏离。射线与平面平行、或 `X` 落在任一相机身后（投影深度 ≤ 0）→ 该点无预测。
   - **降级裁决（冻结）**：无预测的点降级为零视差种子并在 `provenance["seed_fallback_points"]` 计数，而不是全场拒算（内核对非有限种子整批 `ValueError`，少数掠射点不值得陪葬），也不是静默——计数必须落盘。这些点的错锁风险由 §5 的门兜底。
   - **适用包络（IR2-O1 报告必须写明）**：种子误差 ≈ 表面偏离 × `∂|d|/∂Z ≈ f·B/Z²`。`make_stereo_rig` 默认几何（f = 35 mm / 3.45 µm ≈ 10145 px，B = 254 mm，Z = 648 mm）下约 **6.1 px/mm**，即平面种子容忍约 ±0.5–0.8 mm 的表面偏离。超出此包络需要 Stage-B 极线一维扫描（见下），S2 合成验收数据在包络内。
3. **`SOLVER`**：`guess=None`，`icgn.search_radius > 0` 时内核 FFT-CC 围绕**零视差**搜索——只适用于预期 `|d| ≤ search_radius` 的小视差 rig。
4. **`ZERO`**：测试对照组（证明"不种即错"）与近零基线特例。

**预留槽位（本文冻结其语义，S2 不实现）**：`MatchSeed.EPIPOLAR_SCAN` = R1-O2 §5.1 Stage B 的极线一维扫描——深度界 `[z_min, z_max]` 沿左射线投影到右图得极线段，以 ≤ 3 px 步长采样、候选取整、整数对齐零均值 ZNCC（平坦/越界哨兵 −1，纪律同 `integer_search_fftcc`）取 argmax 为种子。落地时按新增枚举值进入 `MatchSeed`，`match_stereo_pair` 签名不变；候选按构造落在极线上，扫描不会掩蔽坏 F。畸变层落地后同一槽位改为沿极**曲线**采样（R1-O2 §6.3），调用面仍不变。

**禁止**：在大视差 rig 上把静默零种子当默认（`AUTO` 有 rig 必须走 `PLANE`）。

## 5. 极线残差与质量门（规范性）

1. **F 每图对计算一次**，只走 `fundamental_from_projections(P_left, P_right)`（可经 `rig_fundamental` 薄适配）。**绝不**从被评分的对应估计 F（S4.3）：度量必须来自匹配没有参与选择的几何，否则是自我评分。
2. **计算对象**：先把未收敛点掩成 NaN（陈旧坐标会打出貌似合理甚至优秀的分数），再在**未修正**的原始收敛坐标上算
   - `sampson_px = sampson_distance(F, x_L, x_R)`——S4.3 钦定的默认 POI 质量场（一阶最优修正量的模）；
   - `epipolar_px = epipolar_distance(F, x_L, x_R, symmetric=True)`——对称点-极线距离，留作人看得懂的对照场。
   NaN 输入按 `triangulate.py` 的 `_safe_divide` 语义传播为 NaN，绝不折成 0。
3. **门（冻结语义）**：`accepted = (status == CONVERGED) ∧ (sampson_px ≤ max_sampson_px)`，NaN 比较为 False——fail-closed。门**只是附加布尔场**，不改写 `correlation.status`；调用方可改阈值重门而不必重匹配。
4. **独立性论证（本规格的立足点）**：ICGN 的代价函数里没有 F（无约束二维优化），F 又解析自标定而非拟合自对应，所以 `sampson_px` 是真正独立的体检。正确匹配的法向漂移 ~ 匹配噪声（L0 合成上 10⁻² px 量级）；错锁散斑周期瓣的法向偏移 ~ 像素量级，中间隔 1–2 个数量级，`max_sampson_px = 1.0` 的 draft 门先保证抓住**粗大**错配。收紧到贴近噪声底的值由 IR2-F1 凭 IR2-G3 的实测分布定稿，禁止在无分布证据时拍数。
5. **盲区如实登记**：恰好落在极线**上**的错锁瓣（错误深度、正确极线）对 ZNCC 门与极线门都不可见。这不是本门的缺陷是它的定义域；归置给视差面残差（R1-O2 §3 指标表）与四路闭环 `ε_loop`（§6.4），两者都在 S2 之后。测试必须把这个盲区**断言出来**（§9 T3），不许假装门是全能的。
6. **Sampson 修正对是可选产物不是替代品**：`sampson_iters > 0` 且有 rig 时产出 `left/right_corrected`（迭代 Sampson，收敛后两射线精确相交）。冻结：一切质量场必须算在未修正坐标上——修正会把点拉回极线，把 `sampson_px` 变成恒零的废数。

## 6. 与三角化 / 3D 管线的交接（约束 IR2-O2）

- 喂给三角化的唯一出口是 `correspondences(masked=True, corrected=…)`：被拒点 NaN，`triangulate.py` 把 NaN 当"缺测"传播为 NaN 世界点而不炸批（其 docstring 已承诺）。
- 两条等价路线，选一条别混跑：原始对 → `triangulate_optimal`（内部自带 Sampson 修正 + DLT）；或修正对 → `triangulate_dlt`（修正已做完，DLT 即 L2 最优）。修正在数值上近幂等，双重修正无害但浪费，且**禁止**在修正对上再算任何质量场（§5.6）。
- 极线门只是 R1-O2 §5.1 Stage D 的匹配侧半边；另半边（cheirality + 位置协方差）由 `triangulation_quality_mask` 在三角化后完成，归 IR2-O2。
- 右→左方向（四路闭环需要）：同一入口对换参数，`F_RL = fundamental_from_projections(P_right, P_left)`（数值上即 `F_LR` 的转置，资料性）。闭环本身与时间匹配的合成归 IR2-O2 及之后。

## 7. 对 R1-O2 §5.1 的 S2 偏差登记（如实）

| R1-O2 要求 | S2 现状 | 归置 |
|---|---|---|
| Stage C 默认**二阶**形函数（斜面透视下一阶系统性欠匹配，Schreier & Sutton 2002） | S2 基线一阶（本派工命名 `icgn_first_order`）；内核已有 `icgn_second_order`，接入 = 换入口 + 平坦区自动降阶，调用面不变；`shape_order != 1` 现在**响亮拒绝**而非静默忽略 | 数值行为变更，须过 IR2-F1 门并在轮次报告留痕后翻转默认 |
| Stage A SIFT/AKAZE 特征 + 视差面拟合 | 未做；名义平面种子是其廉价替身（§4 包络内等效） | 后续轮，`MatchSeed` 新增枚举值 |
| Stage B 极线一维粗扫 | 未做；语义已冻结为 `EPIPOLAR_SCAN` 预留槽位（§4） | 后续轮 |
| 自适应/掩膜感知子集、间断自动检测 | 未做 | 后续轮（Challenge 痛点，不许悄悄砍掉） |
| §6.3 畸变极曲线采样 | L0 针孔 → 极线为直线，无需采样器；与 `triangulate.py` 同一范围声明 | 随畸变模型落地 |
| D2 立体/时间共享参考子集 Hessian（省 ~35% 算力） | S2 参考实现独立调用不共享——正确性优先，性能非目标 | GPU/加速轮 |

## 8. 失败语义表

| 输入/事件 | 行为 | 类别 |
|---|---|---|
| 左右图形状不一致、非 2-D、非有限像素 | `ValueError`（内核边界） | 调用级，抛 |
| 相机中心重合的退化 rig | `ValueError`（`fundamental_from_projections`），在任何相关之前 | 调用级，抛 |
| `points` 非有限 / 形状错、平面法向为零、阈值非法 | `ValueError` | 调用级，抛 |
| `PLANE` 无 rig | `ValueError`（指明改用 SOLVER/ZERO 或补 rig） | 调用级，抛 |
| 平面预测无定义的个别点 | 零种子降级 + provenance 计数 | 逐点，不抛 |
| 种子太差 / 右图子集越界 / 平坦子集 | 内核 `Status` 逐点退出 | 逐点，不抛 |
| 收敛但 `sampson_px` 超门或为 NaN | `accepted=False`，status 不动 | 逐点，不抛 |
| 无 rig | 极线字段全 `None`，门退化为收敛判据 | 定义过的降级 |
| 空 AOI | n=0 各数组，rig 校验照做 | 定义行为 |

## 9. `tests/test_stereo_match.py` 最小集（约束 IR2-O1；阈值均 draft，实测落 IR2-G3）

- **T1 真值视差**：`make_stereo_rig` + 已知表面（平面及带起伏面）渲染合成散斑对（B 样条重采样渲染），收敛率 ≥ 95%，收敛点视差误差 MAE ≤ 0.05 px。
- **T2 残差噪声底**：T1 收敛点上 `sampson_px` 与 `epipolar_px` 中位 ≤ 0.05 px。
- **T3 门的方向选择性**：向对应注入**法向** ≥ 1 px 偏移 → 门必拒；注入**沿极线**偏移 → 门不响——把 §5.5 的盲区断言成预期行为。
- **T4 光度不变**：`right' = a·right + b (a>0)` 与原 `right` 的视差差 ≤ 1e-6 px（ZNSSD 不变性的跨相机复认）。
- **T5 退化 rig**：中心重合 → `ValueError`，且未进入任何相关计算。
- **T6 无 rig 降级**：极线字段全 `None`，`accepted` = 收敛掩膜，无异常。
- **T7 全链**：`match → correspondences(masked=True) → triangulate_optimal → triangulation_quality_mask`，重建面 RMS 达 mm 级 draft 门限，NaN 点不炸批。
- **T8 F 方向回归**：解析投影的真值对应上 `epipolar_distance(F, x_L, x_R) ≈ 0`，锁定 `(P_left, P_right)` 参数顺序语义。
- **T9 种子必要性**：默认 rig 上 `ZERO` 种子收敛率显著劣于 `PLANE`（证明 §4 的"不种即答错题"不是空话）。

## 10. 非目标（S2 明确不在本契约内）

rectification；任何镜头畸变层（L1–L5）与畸变极曲线；显微镜非参数畸变场（RUL-04，专利意见前零实现——本行是范围排除，不描述任何已有物）；特征法/深度学习种子；自适应与掩膜感知子集；时间匹配（归 `dic2d`/`dic3d`）；四路闭环与视差面残差；`Σ_cal` 标定协方差；GPU/多线程；异构传感器 rig。

## 11. 交接清单

- **IR2-O1**：按 §2–§5 实现与测试；报告写明平面种子适用包络的实测数（§4）与 `sampson_px` 分布；二阶接入**不做**。
- **IR2-O2**：`dic3d` 只 import §2 的八个名字 + `hl3.stereo.triangulate` 公开面；三角化路线二选一（§6）；闭环归其后续。
- **IR2-F1**：`max_sampson_px` 与 §9 各 draft 阈值凭 G3 分布定稿；禁放宽已冻结语义。
- **IR2-G3**：`summary()` 的 sampson rms/p95/max、收敛率、accepted_fraction 落 `benchmarks/metrology/metrics.json` s2 段。

冲突消解按 RUL-08：`LEGAL.md` → ADR → Gate/协议 → 内核规格（R1-O1/R2-O1）→ 3D 规格（R1-O2）→ 本文（调用面与复用协议）→ 实现代码注释。

*IR2-F2 完。本文未改动 `src/**` 任何文件。*
