ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast
<!-- SPDX-License-Identifier: Apache-2.0 -->

# IR2-O2：立体 DIC 三维流水线（`hl3.pipeline.dic3d`）

> 子代理：IR2-O2（opus-fast）｜轮次：Impl-R2 / S2+S3
> 独占路径（与 `s1s4/IR2_DISPATCH.md` 一致）：`src/hl3/pipeline/dic3d.py`、`src/hl3/pipeline/__init__.py`、`tests/test_pipeline_3d.py`、本报告
> **未触碰**：`src/hl3/stereo/**`（含 IR2-O1 的 `match.py`）、`src/hl3/correlate/**`、`src/hl3/strain/**`、`src/hl3/uq/**`、`src/hl3/cli/**`、`src/hl3/io/**`、`benchmarks/**`、`docs/**`、`README.md`、`pyproject.toml`、`.github/**`
> 环境：CPU-only，Python 3.12.3 + NumPy 2.4.4，纯 NumPy，无新依赖
> 法律边界：只调用本仓自己的内核（R2-O1 IC-GN、R2-O2/R3-O2 三角化、IR1-O3 2D 流水线、IR2-O1 立体匹配）；**显微镜畸变零实现**（规格 §4.1 L6 / §10.4 仍被专利检索意见封锁）；无 VIC 逆向

---

## 0. TL;DR — 实测数字

| 项 | 数值 |
|---|---|
| **新增代码** | `src/hl3/pipeline/dic3d.py` **1887 行**；`src/hl3/pipeline/__init__.py` 46 → 77 行（只加再导出） |
| **新增测试** | `tests/test_pipeline_3d.py` **1378 行 / 120 用例**，`120 passed in 15.2s` |
| 全仓（CI 口径 `pytest -q`） | **`689 passed in 44.4s`**，0 failed |
| **刚体平移复现（亚像素，81 POI，无噪）** | bias **−0.008 / +0.005 / +0.042 µm**；RMS **0.022 / 0.033 / 0.072 µm**（真值 +60 / −40 / +30 µm） |
| 刚体平移（多像素，同一次运行） | bias **+0.000 / −0.010 / +0.017 µm**；RMS **0.027 / 0.041 / 0.097 µm**（真值 +150 / +100 / −80 µm） |
| 形貌（应为 z = 0 平面） | \|z\| 中位 **0.247 µm**，最大 **0.391 µm** |
| 倾斜 20° 平面 | 有效点 **100%**；位移 bias ≤ **0.038 µm**；拟合法向误差 **0.0006°** |
| **2 灰阶噪声** | bias **+0.005 / −0.006 / −0.239 µm**；散布 **0.274 / 0.274 / 1.584 µm** |
| **四路闭环残差（规格 §6.4）** | 干净图像上中位 **3.2e−05 px**（倾斜面 4.2e−04 px）——默认计算，默认不用它拒点 |
| Sampson / 重投影残差 | 中位 **1.6e−04 px** / **1.4e−04 px** |
| 内置匹配 vs `hl3.stereo.match` | 对应点差 **2.9e−06 px**，U/V/W 差 **1.5e−10 mm**（同一个 ZNSSD 极小值，只差种子） |
| **倾斜面上补齐的收益** | `MatchMode.REQUIRED`（只用 IR2-O1）匹配率 **46.9%** → `AUTO`（缺口交给内置深度扫描）**100%**，43/43 全部补回 |
| 吞吐 | 81 POI × 3 帧、含闭环 **1.2 s**；关闭闭环的两帧运行 **0.4 s**（单线程纯 NumPy） |

一句话：**三维链路只做"把已有的东西按正确顺序串起来"——参考帧立体匹配一次、每视图各跑一遍 2D 流水线、两帧各三角化一次、相减得世界系 U/V/W；相关、三角化、应变的数学一行都没有重写。** 参考对应关系**只解一次**然后被时间匹配带着走，所以一个物质点在整个序列里保持同一个身份；规格 §6.4 的四路闭环残差是**默认计算**的，而且它的回程两条腿只用环内量做种子，不看它要审计的那条左时间匹配。

---

## 1. 交付物

| 文件 | 改动 |
|---|---|
| `src/hl3/pipeline/dic3d.py` | 新增，1887 行 |
| `src/hl3/pipeline/__init__.py` | +31 行，只做再导出（`dic3d` 的 13 个名字） |
| `tests/test_pipeline_3d.py` | 新增，1378 行 / 120 用例 |
| `.agent_workspace/s1s4/IR2-O2-dic3d.md` | 本报告 |

提交（分支 `cursor/ir2-o2-dic3d-88ad`）：

1. `feat(pipeline): stereo-DIC 3D chain from reference match to world U/V/W`
2. `tests: 120 cases for the 3D pipeline on a rigidly translated plane`
3. `docs(s2): IR2-O2 report on the 3D pipeline, its matcher hand-off and its gates`

公开 API（`from hl3.pipeline import ...`）：

```
run_stereo_sequence, correlate_stereo_pair        # 入口
Dic3DConfig, MatchMode, Triangulator              # 配置
Dic3DRun, Frame3D, MatchOutcome, RejectReason     # 结果
match_reference_stereo, epipolar_depth_search     # 内置匹配（可单独用）
triangulate_correspondence                        # 三角化分派（含缺测过滤）
resolve_match_backend, MatchUnavailableError      # 对接 hl3.stereo.match
```

---

## 2. 链路：规格 S2–S6 各段落在哪里

```
S2 参考帧立体匹配   hl3.stereo.match.match_stereo_pair（在场时）
                    └ 缺口 / 缺席 → 本模块的极线深度扫描 + IC-GN
S4 时间匹配         hl3.pipeline.dic2d.run_sequence ×2（左、右各一遍，互不知情）
S3/S5 三角化        hl3.stereo.triangulate 四级阶梯，默认线性 DLT
S6 三维位移         U,V,W = X_def − X_ref（世界系，规格 §7.1），并给 |A|
质量门             ZNCC → Sampson → 三角化有限性 → cheirality → 3×3 协方差 → 四路闭环
```

三条决定了这一版形状的选择：

**(1) 参考配对只解一次。** 物质点由左图 POI 定义，右图搭档只在参考帧找一次，之后靠各自视图的时间匹配走。每帧重新立体匹配会让点漂到另一块材料上，`W` 就变成"匹配器今天心情"的函数而不是试件的函数。代价是右视图的 POI 不在整数栅格上——这没关系，IC-GN 本来就吃浮点中心。

**(2) 时间匹配直接复用 2D 流水线，而不是重写。** 左视图用原 POI 网格跑一遍 `run_sequence`，右视图用参考匹配给出的 `x_right` 跑一遍。种子传递、参考更新（`FIXED`/`EVERY_N`/`INCREMENTAL`）、状态簿记全部照单继承。三维层里**没有**第二套相关逻辑。

**(3) 应变在这一层是关掉的。** 曲面应变是 S7 在世界系场上的工作；顺手把每个视图的 2D 应变算出来叫同一个名字，是个会骗人的量。`Dic3DConfig.temporal_config()` 显式写 `StrainMode.OFF`。

---

## 3. 与 IR2-O1 `hl3.stereo.match` 的对接（本轮唯一的跨代理接口）

写这个模块时 `match.py` 还没进树，写完时进了。两种状态都必须能跑，所以对接是**解析式**的，不是硬 import：

| `MatchMode` | 语义 |
|---|---|
| `AUTO`（默认） | 用 `hl3.stereo.match`；**它没匹配上的点交给内置深度扫描补齐**；模块缺席/报错/签名不符则整体降级到内置，原因写进 `MatchOutcome.reason` |
| `INTERNAL` | 只用内置匹配。`match.py` 进树前后的运行逐位可比 |
| `REQUIRED` | 只要那个模块，不降级也不补齐；拿不到就 `MatchUnavailableError` |

三处不那么显然但必要的细节：

- **参数类要按它的类型构造。** `match_stereo_pair(params=...)` 要的是 `StereoMatchParams`，不是裸 `ICGNParams`；直接把后者塞进去会在它内部炸成 `AttributeError`（不是我 `except` 的 `TypeError/ValueError`），整轮运行就没了。`_backend_params()` 因此按后端模块暴露的参数类去构造，并按签名裁剪关键字。
- **把它的几何门关掉，而不是把本轮的阈值递下去。** `StereoMatchParams` 默认 1 px Sampson 上限。若递下去，被它拒的点回来是"没匹配上"，和相关失败无法区分；而且一次运行明明报告 `max_epipolar_px = inf`，实际却被 1 px 卡过。现在统一传 `max_sampson_px=inf`，Sampson 距离由本模块自己算、自己卡，拒点归因到 `RejectReason.EPIPOLAR`。
- **补齐不是"不信任后端"。** 已被接受的匹配一个都不动，只填它没给出的；被它的质量掩膜**显式排除**（回来是 `Status.MASKED`）的点也不填——质量判断不是缺口。这正是规格 §5.1 "便宜的全局级 → 昂贵的局部级" 的顺序。倾斜 20° 平面上这一步把匹配率从 46.9% 抬到 100%（它的名义平面种子默认 z = 0，面外偏离在视差上放大到十几像素，超出 IC-GN 收敛半径；深度扫描不需要这个假设）。

---

## 4. 内置匹配：极线深度扫描（规格 §5.1 Stage B + §6.3）

不是占位实现，是完整的匹配器：

- **在世界里走射线，而不是在右图里走直线。** 对左图每个 POI 沿其视线采样距离 s，把 `C + s·d` 投进右相机。针孔下这两者是同一条曲线；但等畸变模型进来（规格 §6.3 极线是曲线）这个参数化仍然成立，而且每个候选都有物理含义——一个距离。
- **按 1/s 均匀采样**：像面位移对逆距离是线性的，按 s 均匀会在远场步进不到一个像素、在近场一步跨几十像素。
- **采样数由几何推出来，不由配置猜。** 254 mm 基线在 ±35% 深度范围内扫过数千像素；任何"对这套装置合适"的固定采样数换一套装置就是错的。默认按相邻候选在右图相距 `depth_step_px = 2 px` 定数，`max_depth_samples` 封顶。
- **两个让它跑得动的取舍**：候选落到右传感器外的先跳过（会聚装置下这是扫描的绝大部分），以及粗扫用**抽稀的子集**打分（这一级只需要找到盆地，亚像素归 IC-GN）。
- **深度范围可以自己推**：两条光轴最接近处即为会聚距离（本装置 660.33 mm——沿光轴，不是 rig 记的 648 mm z 向 standoff），取 ±35%。平行装置没有会聚点，此时**拒绝猜**并要求显式 `depth_range_mm`。

---

## 5. 四路闭环残差：唯一不需要真值的自洽指标（规格 §6.4）

```
p_L,ref --立体--> p_R,ref --时间--> p_R,def --立体(变形帧)--> p̂_L,def --时间逆--> p̂_L,ref
ε_loop = ||p̂_L,ref − p_L,ref||
```

前两条腿已经解过了，所以每帧只多算两次相关（约 2× 成本）。要点在**种子**：第三腿用**参考帧视差**做种子，第四腿用它自己的结果取反做种子——两者都来自环内，因此这个残差从不参考它要审计的那条左时间匹配。用左时间匹配的结果去种它，等于让被审计者提供答案。

默认**算**、默认**不拒**：`loop_closure=True` 而 `max_loop_px=inf`。理由是规格把它列为强制一致性检验（D3），而"多少 px 算坏"是现场问题不是库的问题。干净合成图上中位 3.2e−05 px，倾斜面 4.2e−04 px——量级本身就是这条链自洽性的一个上界。

---

## 6. 质量门与拒点归因

`RejectReason` 是本模块自己的 IntEnum，**不是** `hl3.correlate.Status`：三次相关全部收敛的点，仍可能因为射线近平行、或三角化到相机背后而不可用；把这些塞进相关状态码是把几何失败记到相关器头上。

| 顺序 | 原因 | 触发 |
|---|---|---|
| 1 | `NO_STEREO_MATCH` | 参考立体匹配没收敛（或被后端质量掩膜排除） |
| 2 | `EPIPOLAR` | Sampson 距离 > `max_epipolar_px` |
| 3/4 | `LEFT_MATCH` / `RIGHT_MATCH` | 该帧对应视图的时间匹配失败 |
| 5 | `TRIANGULATION` | 三角化返回非有限点 |
| 6 | `CHEIRALITY` | 点在某个相机背后 |
| 7 | `UNCERTAINTY` | `sqrt(tr Σ_X) > max_position_sigma_mm`（规格 §6.6 匹配项；`Σ_cal` 仍未接入） |
| 8 | `LOOP_CLOSURE` | 四路闭环残差 > `max_loop_px` |

被拒的点在浮点场里是 NaN 而不是上一帧的陈值，但**证据保留**：`position_sigma_mm`、`loop_px`、`epipolar_px`、`zncc_left/right` 照常填。门只说明为什么，不销毁依据。

---

## 7. 测试：为什么是"平面刚体平移"

合成场景是一块散斑平面，变形帧是它的**刚体平移**。选这个不是因为它简单，而是因为三件独立的事必须同时对才能复现它：立体对应错了 `W` 就带偏置（面内检查看不出来）；两个时间匹配有一个错了两视图就不自洽，三角化点沿极线方向跑；三角化错了对应关系再准也落在错的世界点上。所以断言是**逐分量**的——`U`、`V` 对而 `W` 漂正是立体 DIC 的典型失效，只看幅值会把它藏起来。

图像生成与求解器不共享任何代码：一个解析的、严格带限的随机相位余弦场定义在**物面**上，按每个相机真实的针孔投影逐像素求交后取值。参考帧和变形帧是同一个连续函数在不同世界位置的两次独立取值，不是数组平移——所以测到的残差是流水线自己的，不是测试自带的。

120 个用例的分布：配置校验 24、相机装配 7、极线扫描与内置匹配 12、后端对接 18、三角化分派 8、刚体平移与形貌 14、运行结构/字段/溯源 12、质量门 12、输入校验 13。整套在 `hl3.stereo.match` **在场与缺席两种状态下都跑过**（缺席态在 `git worktree` 里用本分支的树验证），120 passed 一致。

噪声一档（2 灰阶，图案对比度约 49 灰阶）给出的是有意义的精度数字：面内散布 0.274 µm ≈ 4.2e−03 px，面外 1.584 µm，约为面内的 5.8 倍——这个比值由会聚半角（±11.1°）决定，是立体 DIC 的固有代价，不是实现缺陷。无噪场景的 0.02 µm 量级则应当理解为"这套合成图案 + B 样条插值下的偏置下限"，它没有 PIB、没有噪声，不能当作现场精度承诺。

---

## 8. 明确没做的事

- **畸变**：全链路仍是针孔 L0。规格 §4.1 L1–L5 要跟标定模块一起做；**L6 非参数畸变场（立体显微镜）在本仓任何地方都没有实现**，本模块也没有——§10.4 的书面专利检索意见不存在之前不会有。
- **`Σ_cal`**：3×3 位置协方差只传了匹配项（规格 §6.6 的一半），所以它是"标定完全已知条件下"的下界。bootstrap 标定协方差要等真的标定求解器。IR2-O3 的 `hl3.uq` 落地后，本模块的 `position_sigma_mm` 与 `Frame3D.X` 是它的天然上游。
- **曲面应变（S7）**：不在本轮范围。`Dic3DRun` 输出的世界系 `X`/`U,V,W` 与 `valid` 就是它要的输入。
- **立体匹配用二阶形函数**：规格 §5.1 要它做默认，本模块留了 `stereo_icgn` 这个口子（`replace(icgn, shape_order=2)` 即可），默认没开——IR2-O1 当前也显式只支持一阶。这是**已知偏差**，斜面上的欠匹配偏置要靠它压。
- **特征法 Stage A**：内置匹配从 Stage B（极线搜索）起步。大视差/弱纹理下的 SIFT/AKAZE 全局初值仍是空白。
- **抖动布点**（规格 §6.7 抗三角化 moiré）：`points=` 可以传任意点集，抖动网格由调用方给；模块本身不生成。

---

## 9. 给下一环的接口

```python
run = run_stereo_sequence(left_images, right_images, rig, Dic3DConfig(...))

run.X_ref            # (n, 3) 参考形貌，不可用点为 NaN
run.frames[i].X      # (n, 3) 该帧世界坐标
run.frames[i].displacement          # (n, 3) U, V, W（mm）
run.frames[i].valid / .reject       # 布尔掩膜 + RejectReason 归因
run.frames[i].position_sigma_mm     # 逐点位置不确定度（匹配项）
run.frames[i].loop_px               # 四路闭环残差
run.field("w")       # (n_frames, ny, nx)，栅格化并按 valid 掩膜
run.shape_field()    # (ny, nx, 3)
run.provenance       # 参数 + 几何 + 质量快照（基线、会聚距离、各残差中位数…）
run.left / run.right # 两个 Dic2DRun，需要下钻时用
```

`hl3.uq`（IR2-O3）要的逐点协方差、`hl3.cli.validate`（IR2-F4）要的 provenance 快照、S7 曲面应变要的世界系场，都已经在这些字段里了。
