ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# R1-O1：HL3-2D 核心规格与算法落地方案

> 子代理：R1-O1（opus-fast）｜轮次：Round 1｜矩阵：4 fable + 3 opus-fast + 3 gpt-sol
> 对标：Correlated Solutions **VIC-2D 8**（仅依据公开产品页/发布说明，见 `research/vic_public_feature_baseline.md`）
> 法律边界：**不逆向、不反编译、不安装破解版**。本文所有算法均来自公开文献与开源实现（OpenCorr / Ncorr / muDIC / AL-DIC / DICe），详见 §9 引用。

---

## 0. 本文定位与阅读方式

本文是 **HL3-2D 的可实现级规格书**，目标是让 Round 2 的实现子代理可以直接照着写代码，而不需要再回头查文献。

- §1 用户工作流：逐项对标 VIC-2D 8 的公开功能，给出 HL3 的行为定义与超越点。
- §2 算法规格：给出可直接编码的数学式、数据流、参数默认值与收敛判据。
- §3 二维特有误差与陷阱：离面运动、镜头畸变、显微/SEM。
- §4 `src/` 模块与文件布局，附一个关键接口头文件草案。
- §5 单元测试计划（合成图 + 噪声 + 光照 + 张量代数 + 回归基准）。
- §6 超越 VIC-2D 8 的六条路径。
- §7 参数默认值总表。§8 风险。§9 引用。

**本轮不落地代码**：按派工单要求，本轮只产出规格。故意不创建 `src/` 骨架目录，避免与 R1-O3（共享内核）和 R1-F1（全局架构）的收敛结果冲突；§4 的布局是提案，最终由父调度器在 Round 1 收敛后定稿。

---

## 1. 用户工作流规格（对标并超越 VIC-2D 8）

### 1.0 项目模型与状态机

VIC-2D 的工作流是"工程（project）"驱动的。HL3-2D 采用同样的心智模型，但把工程定义为**可版本化、可 diff、可脚本化**的对象。

工程对象 `Hl3Project2D`：

```
Project2D
├── meta            {name, uuid, created, hl3_version, schema_version}
├── images          ImageSequence（引用而非拷贝，记录绝对/相对路径 + 内容哈希）
├── calibration     Scale2D | Intrinsic2D（可选，见 §3.2）
├── aoi             AOI（多边形/圆/矩形布尔组合 + 排除孔 + 逐帧可变掩膜）
├── analysis_params CorrelationParams（subset/step/SF/插值/准则/路径/阈值）
├── seeds           [Seed]（自动检测 + 用户覆盖）
├── strain_params   StrainParams（张量类型/窗口/权重/滤波）
├── postproc        [PostOp]（刚体去除、自定义变量、提取器）
├── analog          AnalogChannels（时间对齐后的载荷/位移/温度等）
├── results         ResultStore（HDF5，见 §4.4）
└── provenance      每次运行的完整参数快照 + 哈希 + 环境指纹
```

状态机（GUI 与 CLI 共用同一状态机，保证脚本与界面行为一致）：

```
EMPTY → IMAGES_LOADED → AOI_DEFINED → PARAMS_SET → SEEDED
      → RUNNING → CORRELATED → STRAINED → POSTPROCESSED → EXPORTED
```

任一上游状态失效（例如改了 subset）自动把下游标记为 `STALE`，但**保留旧结果**并在 UI 上标灰，支持 A/B 对比。VIC-2D 的公开描述里没有强调这一点；HL3 把"参数扫描对比"做成一等公民，因为 iDICs 的 VSG 研究和噪声底板研究本质上就是参数扫描（iDICs GPG §5.4.4–5.4.5）。

### 1.1 图像序列载入

| 能力 | VIC-2D 8（公开） | HL3-2D |
|---|---|---|
| 格式 | 常见位图 | 8/10/12/16-bit TIFF、PNG、BMP、原始 RAW、CIH/多帧、HDF5/Zarr 图像栈、视频容器（可选 FFmpeg） |
| 序列 | 支持 | 通配符/正则/自然排序/EXIF 或文件名时间戳排序；缺帧检测 |
| 大数据 | — | 内存映射 + 惰性解码 + LRU 页缓存；≥100k 帧序列不全量入内存 |
| 元数据 | — | 采集时间、曝光、增益、相机序列号原样保留写入 HDF5 |

具体行为：

1. 载入时立刻计算每帧的**图像质量指标**并缓存：均值、标准差、饱和像素比例（`I ≥ I_max−1`）、欠曝比例、**平均灰度梯度 MIG** `δ_f = (1/(W·H))·Σ|∇f|`（Pan et al. 2010）、散斑尺寸直方图（由 FFT 自相关半高宽估计，OpenCorr 用 FFTCC 做同样的事）。
2. 参考帧默认取第 0 帧，可任选；支持"每 N 帧更新参考"和"自适应参考更新"（见 §2.9）。
3. 8-bit 以上图像内部统一转 `float32`，归一化到 `[0,1]`，但**保留原始位深信息**用于噪声模型。
4. 序列内容哈希（blake3，按帧）写入 provenance，保证结果可溯源。

**超越点**：VIC-2D 是 Windows 桌面单机流程；HL3 的序列层可以直接指向对象存储（S3/MinIO）上的 Zarr，配合 §1.12 的 CLI 做集群批处理。

### 1.2 AOI（感兴趣区域）编辑器

对标 VIC-2D 的 AOI 编辑器，功能集：

- 图元：矩形、椭圆/圆、任意多边形、画笔（自由涂抹）、魔棒（基于灰度/梯度阈值）。
- 布尔：并、差（挖孔）、交；图元可命名、可排序、可单独启停。
- 逐帧掩膜：支持"AOI 随时间变化"（试样破断、遮挡物移动），以 keyframe + 线性/最近邻插值的方式定义；也支持外部导入 PNG 掩膜序列。
- **自动 AOI 建议**：基于 MIG 与散斑密度自动圈出"图案质量合格"的连通域，把无散斑背景、饱和高光、失焦区剔除。这是 iDICs GPG 中"图案质量评估"的自动化版本。
- 边界处理策略（用户可选）：
  - `STRICT`：subset 必须完全落在 AOI 内（默认，最保守，等价大多数商业软件默认）。
  - `PARTIAL`：允许 subset 部分越界，越界像素在 ZNSSD 求和中被掩蔽，权重归一化（对薄试样/边缘应变很关键）。
  - `SPLIT`：掩膜感知的 subset 分裂（pyALDIC 的 mask-aware subset splitting 思路），用于裂纹两侧。
- AOI 内自动生成 POI 网格（按 step 对齐到参考帧像素栅格，保证不同 step 之间点位可对齐比较）。

### 1.3 Subset / Step 参数与"良好实践向导"

参数定义（全部以参考帧像素为单位，同时显示物理单位）：

- `subset_size`：正方形边长，奇数，默认 **21**（iDICs GPG Recommendation 5.2：21×21 是实用最小值；15×15 是理论下限，要求 3–5 px 特征、约 50% 密度）。内部以半径 `r = (subset_size−1)/2` 表示，支持各向异性 `r_x ≠ r_y`。
- `step_size`：默认 **5**（约 subset 的 1/4~1/3；GPG §5.2.6 建议 1/3~1/2 之间，重叠超过 1/3 subset 后邻点不再独立）。
- `subset_shape`：`SQUARE`（默认）| `CIRCLE`（圆形 subset，边界更各向同性）| `ADAPTIVE`（按局部 MIG 自适应放大，OpenCorr 的 `self_adaptive` 同类思路）。

**良好实践向导（Good-Practices Wizard）** —— 这是 HL3 明确超越 VIC-2D 的地方，把 iDICs GPG 的建议做成交互式检查：

1. 读入参考帧 + 一张"零载荷"静态帧（用户提供）。
2. 图案体检：特征尺寸中位数（目标 3–5 px）、特征密度（目标约 50%）、MIG、饱和/欠曝比例、灰度直方图动态范围利用率。给出红/黄/绿判定与具体整改建议（"散斑偏小，建议提高放大倍率或重新喷涂"）。
3. 依据特征尺寸自动推荐 `subset_size`：保证 subset 内至少 3 个特征在各方向上都有明暗跳变。
4. 自动跑一次**噪声底板**（静态帧对静态帧，全场位移/应变的均值与标准差），报告位移噪声 `σ_u`、应变噪声 `σ_ε`。典型参考值（GPG DIC101 Ch.2）：面内 0.01 px 量级。
5. 若用户提供"高应变梯度帧"，自动跑 **VSG 研究**：扫描 `L_VSG`，画线切最大应变幅值收敛曲线 + 应变噪声曲线，输出推荐 VSG（GPG §5.4.5 全流程自动化）。
6. 2D 专属体检：提示离面运动风险，要求用户填写预估离面位移 `Δz` 与工作距离 `L`，直接算出伪应变量级 `≈ Δz/L`（见 §3.1）。

向导的每一条结论都写进 provenance，最终自动填进 §1.11 的报告。

### 1.4 起点（Seed）检测

VIC-2D 公开宣传"自动起点检测"。HL3 的起点子系统：

1. **候选筛选**：在 AOI 内按 MIG 与局部对比度排序，取 Top-K（默认 K=8）互相距离 ≥ 3·subset 的候选点。
2. **整数搜索**：对每个候选点跑 FFT-CC（§2.4）在全 AOI 范围内找 ZNCC 峰。
3. **亚像素求解 + 校验**：ICGN-1 收敛后要求 `ZNCC ≥ 0.9` 且迭代次数 `< 0.5·max_iter`；多个 seed 之间的位移应满足一致性（若 ≥3 个 seed，拟合仿射并检查残差）。
4. **失败兜底**：若 FFT-CC 全部失败（大变形/大旋转/大平移），退化到 **SIFT 特征 + RANSAC 仿射**估计初值（OpenCorr `FeatureAffine`、`SIFT2D` 的公开做法），再交给 ICGN。这条路径对 >100 px 平移和 >30° 旋转是决定性的。
5. **用户覆盖**：GUI 上可手动点选 seed 并手动拖动到目标帧的对应位置；CLI/Python 可直接给 `(x, y, u0, v0)`。
6. **多 seed**：AOI 被裂纹/孔洞分割成多个连通域时，每个连通域独立 seed（Ncorr 的做法）。HL3 自动检测连通域数量并要求足够的 seed。

### 1.5 运行（相关计算）

运行配置：

```
RunConfig {
  initial_guess : FFTCC | SIFT_AFFINE | PREV_FRAME | USER
  path          : RELIABILITY_GUIDED | PATH_INDEPENDENT | HYBRID   // 见 §2.8
  solver        : ICGN1 | ICGN2 | ICLM1 | ICLM2                    // 见 §2.6
  reference     : FIXED | INCREMENTAL(threshold) | EVERY_N(n)      // 见 §2.9
  mode          : LOCAL | GLOBAL_FE | ALDIC                        // 见 §2.13
  backend       : CPU | CUDA | AUTO
  threads       : int (0 = hardware_concurrency)
  deterministic : bool（true 时结果与线程数无关，见 §5.16）
}
```

运行时体验：

- 进度：每帧、每 POI 两级进度；实时显示已收敛点数 / 失败点数 / 平均 ZNCC / 平均迭代数。
- **可中断可续跑**：结果按帧增量写入 HDF5，中途 Ctrl-C 后可从断点续算。VIC-2D 公开资料未强调这点；对 10 万帧高速序列这是刚需。
- 实时预览：边算边把当前帧的 `u/v/ZNCC` 场推给可视化层。
- 失败点诊断：每个失败点记录失败原因枚举（`LOW_ZNCC` / `NOT_CONVERGED` / `OUT_OF_BOUNDS` / `SINGULAR_HESSIAN` / `NO_INITIAL_GUESS` / `MASKED`），在 GUI 上以颜色区分——这直接对应 iDICs 报告要求里的"阈值与被剔除数据"。

### 1.6 应变计算

见 §2.11 的数学。用户侧参数：

- `strain_window`（`L_window`，以**数据点**计，非像素）：默认 **5**（5×5 个 POI）。
- `strain_fit_order`：`LINEAR`（平面拟合，默认）| `QUADRATIC`。
- `weighting`：`UNIFORM` | `GAUSSIAN(σ)`（默认 Gaussian，σ = L_window/4）。
- `tensor`：`ENGINEERING`（Cauchy 小应变）| `GREEN_LAGRANGE`（默认）| `EULER_ALMANSI` | `LOG_HENCKY`。
- `description`：`LAGRANGIAN`（参考构形，默认）| `EULERIAN`（当前构形）。
- 派生量：主应变 `ε1/ε2` + 主方向角、最大剪应变、von Mises 等效应变、Tresca、面内转角、面积变化率 `det(F)−1`。
- 邻点筛选：参与拟合的邻点必须 `ZNCC ≥ zncc_threshold`（默认 0.8）且数量 `≥ neighbor_min`（默认 `0.5·L_window²`），否则该点应变置 `NaN`。这套邻点筛选与 OpenCorr `Strain` 模块的公开设计一致。

**应变随时可重算**：改 `strain_window` 不重跑相关，秒级出结果。这使得 VSG 研究（§1.3 步骤 5）从"跑一晚上"变成"点几下"。

### 1.7 虚拟应变片（VSG）与虚拟引伸计

两个不同的概念，HL3 都要有，且必须在 UI 上区分清楚（这是实践中最常见的误解）：

**(a) VSG 尺寸 `L_VSG`** —— 空间分辨率指标，不是一个可放置的物件。按 iDICs GPG 式 (7.2)：

```
L_VSG = (L_window − 1) · L_step + L_subset      [px]
L_VSG_phys = L_VSG / image_scale                [mm]
```

HL3 在参数面板上**实时显示** `L_VSG`（px 与 mm 双单位），任何一个影响它的参数被改动都立刻更新。这是 iDICs 报告的必填项（GPG §6.2.1 Recommendation 6.1），HL3 直接把它做成一等状态量。

**(b) 虚拟应变片/虚拟引伸计（提取器 Extractor）** —— 用户在场上放置的测量物件，对标 VIC-Gauge 的点测量能力：

- `PointGauge`：单点，输出该点全部标量场随时间的曲线。
- `VirtualExtensometer`：两点/两组点，输出标距变化 `ΔL/L0`（工程应变）与 `ln(L/L0)`（真应变），支持跨 AOI 空洞。
- `LineProbe`：任意折线上的场剖面（线切），支持随时间动画；VSG 研究的线切就用它。
- `AreaGauge`：多边形区域内的均值/极值/标准差/直方图/面积分。
- `RosetteGauge`：三片式虚拟应变花，用于与真实应变片直接对照。

所有提取器输出统一为时间序列表，可与 §1.10 的模拟量通道同图叠加、同轴对比、做交叉相关与相位分析。

### 1.8 刚体运动去除

三档：

1. **`SUBTRACT_POINT`**：减去某个参考点（或一小块区域均值）的位移。最简单，只去平动。
2. **`SUBTRACT_RIGID`**（默认推荐）：在用户指定的"刚性参考区"上做 **2D Procrustes / Kabsch** 拟合，解出最优旋转 `R(θ)` 与平动 `t`，再从全场减去。闭式解：

   设参考区内参考构形点 `X_i`（去质心后 `X̃_i`）、当前构形点 `x_i`（去质心后 `x̃_i`），
   ```
   S   = Σ_i x̃_i X̃_iᵀ            (2×2)
   θ   = atan2( S₁₀ − S₀₁ , S₀₀ + S₁₁ )
   R   = [[cosθ, −sinθ], [sinθ, cosθ]]
   t   = x̄ − R X̄
   u_rigid(X) = R·X + t − X
   u_corrected(X) = u(X) − u_rigid(X)
   ```
   同时输出标量 **面内转角 `θ`**（VIC-2D 公开宣传的"面内转角"）。
3. **`SUBTRACT_AFFINE`**：去掉刚体 + 均匀应变（用于只关心局部化/梯度的场合，须在报告中显式标注，否则会误导读者）。

关键设计：**去除是后处理层的可逆算子，不改动原始位移场**。HDF5 中同时保存 `displacement_raw` 与算子链，任何时候可撤销、可换参考区重算。iDICs 的高速 DIC 综述明确提醒刚体去除会掩盖真实误差，所以 HL3 强制在报告中列出所使用的刚体去除算子及其参考区。

### 1.9 尺度标定与畸变校正（2D）

见 §3.2。用户侧三种模式：

- `NONE`：纯像素单位输出（应变本身无量纲，很多 2D 场合确实不需要标定；VIC-2D 公开材料也强调"应变计算可无标定"）。
- `SCALE_ONLY`：给定图上两点的物理距离，或用标定尺/载物台千分尺，得到 `image_scale [px/mm]`。支持在 AOI 内多处取样求均值与离散度（离散度大 → 提示非垂直或畸变严重）。
- `FULL_INTRINSIC`（**默认推荐**）：用棋盘/圆点标定板做单相机 Zhang 标定，得到 `fx, fy, cx, cy, k1, k2, p1, p2, k3(...)`，在相关之前对整个序列做去畸变重采样（或对 POI 坐标做去畸变映射）。

**iDICs 的立场必须写进 UI**：即使做 2D，也**推荐**做内参标定以校正镜头畸变（GPG 明确指出未校正的镜头畸变是偏差误差来源，且"若不做完整标定，应通过刚体面内平移评估畸变"）。HL3 因此提供 `RIGID_TRANSLATION_DISTORTION_CHECK` 工具：拍一组刚体面内平移图，跑 DIC，把残余的非均匀位移场直接画出来作为畸变代理指标；若峰值残差超过阈值则强烈建议做完整标定。

### 1.10 模拟量同步

对标 VIC-2D 的"模拟量同步采集"。HL3 分两条路径：

**离线导入**（无采集硬件时的主路径）：
- 读 CSV/TDMS（NI）/HDF5/MAT，指定时间列与数据列。
- 时间对齐三法：(a) 硬件触发计数对齐；(b) 共同时间戳对齐；(c) 交叉相关自动对齐（用 DIC 的某个提取器信号与载荷信号做互相关求时延），并显示对齐质量。
- 采样率不同时按用户选择做最近邻/线性/样条重采样到帧时间轴。

**在线采集**（`hl3_sync` + 采集端，与 R1-O3 共享抽象）：
- DAQ 抽象层：NI-DAQmx / Modbus / 串口 / 通用 ADC；每帧记录相机曝光触发时刻。
- 相机与 DAQ 用同一硬件触发源，记录 trigger index，避免软件时间戳漂移。

输出：`analog` 表与 DIC 结果共存于同一个 HDF5，`extractor_series ↔ analog_series` 可直接画应力-应变曲线、做 FFT/FRF（VIC-2D 8 公开提到 FFT/FRF）。

### 1.11 导出

| 类别 | 格式 | 说明 |
|---|---|---|
| 原生 | **HDF5**（开放 schema，§4.4）、Zarr | 全量场 + 参数 + provenance + 模拟量，自描述 |
| 表格 | CSV / TSV / Parquet | 逐点或逐帧；列可选；支持大文件分块 |
| 科学 | VTK / VTU（结构化+非结构化）、Exodus II | 直接进 ParaView / 与 FEA 对照 |
| 网格 | STL / OBJ / PLY | 2D 场贴到平面网格（VIC-2D 8 公开提到工程网格导入 OBJ/STL/PLY） |
| MATLAB | `.mat` (v7.3 = HDF5) | 兼容既有 Ncorr/MATLAB 工作流 |
| 图像 | PNG / TIFF / SVG / PDF | 等值线图、云图、动画帧 |
| 视频 | MP4 / WebM / GIF | 场动画 + 模拟量同步叠加 |
| 曲线 | CSV / JSON | 提取器时间序列 |
| 报告 | Markdown / HTML / PDF | §1.12 |

原则：**任何 GUI 能导出的，Python API 与 CLI 都能导出，且字段完全一致**。

### 1.12 报告（iDICs 合规）

VIC-2D 8 公开提到"模板报告"。HL3 的报告模板**默认就是 iDICs GPG 第 6 章的必填清单**，自动从 provenance 填充：

*硬件参数（GPG §6.1.1 必填）*：相机厂商/型号/分辨率、镜头厂商/型号/焦距、FOV、image scale、SOD、采集帧率、制斑工艺、特征尺寸（含测定方法）；推荐项：光圈、图像噪声。

*分析参数（GPG §6.2.1 必填）*：软件名称与版本（HL3 自动填入 git commit + 版本号）、图像滤波、subset 尺寸（px + mm）、step 尺寸（px + mm）、subset 形函数（仿射/二次）、QOI 的处理与滤波；应变部分：位移预滤波、应变公式（工程/Green-Lagrange/对数）、strain window、**VSG 尺寸（px + mm）**、应变后滤波。

*HL3 额外自动附加*：噪声底板结果、VSG 研究曲线、离面误差估计、畸变检查残差、失败点统计与阈值、DIC Challenge 自检结果（§6.9）、完整参数哈希。

模板可自定义（Jinja2 风格），支持公司 LOGO 与章节裁剪。**这是明确的差异化**：GPG §6.2.1 Note 1 指出非商业代码应使用 DIC Challenge 图像验证并在文档中引用该验证——HL3 把这句话变成产品内置功能。

### 1.13 Python API

Python 是**一等公民**（VIC-2D 8 是"新增 Python 扩展"，HL3 是 Python-first）。pybind11 绑定，同步暴露内核与工程层：

```python
import hl3
from hl3 import dic2d

# 工程级（对标 VIC 工程脚本）
proj = hl3.Project2D.open("test.hl3")
proj.aoi = hl3.AOI.polygon([(100,100),(900,100),(900,700),(100,700)]) \
                  .minus(hl3.AOI.circle((500,400), 60))
proj.params = dic2d.CorrelationParams(subset=21, step=5,
                                      solver=dic2d.Solver.ICGN2,
                                      interp=dic2d.Interp.BICUBIC_BSPLINE,
                                      path=dic2d.Path.RELIABILITY_GUIDED)
res = proj.run(progress=lambda p: print(f"{p:.0%}"))

# 场是零拷贝 numpy 视图
u   = res.field("u")            # (n_frames, ny, nx) float32, NaN = 无效
exx = res.strain("E_xx", window=5, tensor="green_lagrange")

# 自定义变量（对标 VIC 的自定义变量公式，但直接是 Python）
res.add_variable("shear_max", lambda f: 0.5*np.hypot(f.E_xx - f.E_yy, 2*f.E_xy))

# 提取器
ext = res.extensometer((200,400), (800,400))
plt.plot(proj.analog["load_kN"], ext.eng_strain)

# 内核级（不需要工程，可用于自定义流水线/研究）
eng = dic2d.Engine(dic2d.CorrelationParams(subset=21, step=5))
eng.set_reference(ref_img)
poi = eng.make_grid(aoi)
eng.compute(tgt_img, poi)       # 就地更新 poi 的 u,v,zncc,converged,p,cov
```

设计要点：

- **零拷贝**：所有场以 `numpy` 视图返回，底层是 C++ 侧连续内存；不做 Python 循环。
- **GIL 释放**：所有长耗时 C++ 调用释放 GIL，允许 Python 侧并行/进度回调。
- **类型存根**：随包发布 `.pyi`，IDE 有完整补全。
- **纯 Python 可安装**：`pip install hl3`（manylinux / macOS universal2 / Windows wheel），不需要装 GUI。这是相对于"扩展库嵌在桌面软件里"的结构性优势。

### 1.14 批处理 CLI

对标 VIC-2D 8 的命令行批处理，但做成可进 CI/集群的工具：

```bash
# 单工程重跑
hl3-dic2d run project.hl3 --out results.h5 --threads 32 --backend cuda

# 无工程文件的纯参数式调用
hl3-dic2d run \
  --images 'data/frame_*.tif' --ref 0 \
  --aoi aoi.json --subset 21 --step 5 --solver icgn2 \
  --interp bicubic-bspline --path rg \
  --strain green-lagrange --strain-window 5 \
  --out results.h5

# 参数扫描（VSG 研究 / 噪声底板自动化）
hl3-dic2d sweep project.hl3 --subset 15,21,31,41 --step 3,5,7 \
  --strain-window 3,5,7,9 --metric noise-floor,vsg-study --out sweep.h5

# 体检与报告
hl3-dic2d doctor  --images 'static_*.tif' --report doctor.html
hl3-dic2d report  results.h5 --template idics --format pdf -o report.pdf

# 导出与批量转换
hl3-dic2d export results.h5 --format vtu --fields u,v,E_xx,E_yy,E_xy -o out/
```

CLI 契约：

- 退出码语义化（0 成功；2 参数错；3 相关失败率超阈值；4 IO 错）。
- `--json-progress` 输出机器可读进度（供 CI/调度器解析）。
- `--dry-run` 只校验参数与 IO 并打印将要执行的计划。
- 所有 CLI 参数与 Python 参数**同名同义**，由同一份参数定义生成（单一真源，避免三套 UI 漂移）。

### 1.15 实时 2D

VIC-2D 8 公开提到"实时 2D 分析（需许可）"。HL3 的 `hl3_rt2d`：

```
[相机线程] → 环形缓冲(帧+触发号) → [相关线程池] → [应变/提取器] → [输出]
                                                                    ├→ GUI 实时云图
                                                                    ├→ 模拟量输出(DAC/Modbus/EtherCAT)
                                                                    └→ 增量写 HDF5
```

- **延迟预算**：目标端到端 < 1 帧周期。做法：`PATH_INDEPENDENT` + 上一帧结果作初值（收敛通常 2–4 次迭代）；固定 POI 集合，Hessian 与插值系数一次性预计算；无动态内存分配（预分配池）。
- **降级策略**：若某帧算不完，自动跳帧（记录跳帧号），保证不累积延迟；离线可回填。
- **实时输出**：把虚拟引伸计的应变作为模拟量输出回试验机做闭环控制（对标 VIC-Gauge 的闭环能力）。
- **两级精度**：实时用 ICGN-1 + 稀疏 POI；同时把原始图像存盘，事后用 ICGN-2 + 密集 POI 重算高精度结果。UI 上明确区分"实时值"与"复算值"。

---

## 2. 算法规格

### 2.1 记号与坐标约定

- 图像坐标 `x = (x, y)`，`x` 向右、`y` 向下，像素中心为整数坐标。
- 参考图 `f(x)`，目标图 `g(x)`，均为 `float32`。
- POI 中心 `x₀`，subset 局部坐标 `Δx = x − x₀`，`|Δx| ≤ r_x`，`|Δy| ≤ r_y`。
- subset 像素数 `N = (2r_x+1)(2r_y+1)`。
- 形函数（warp）`W(Δx; p)`，参数向量 `p`。
- 灰度统计：
  ```
  f_m = (1/N) Σ f_i
  Δf  = sqrt( Σ (f_i − f_m)² )
  g_m, Δg 同理（在当前 warp 下采样得到）
  ```

### 2.2 相关准则

**ZNCC（零均值归一化互相关）**，取值 `[−1, 1]`，1 为完美匹配：

```
C_ZNCC(p) = Σ_i (f_i − f_m)(g_i − g_m) / (Δf · Δg)
```

**ZNSSD（零均值归一化平方差和）**，取值 `[0, 4]`，0 为完美匹配：

```
C_ZNSSD(p) = Σ_i [ (f_i − f_m)/Δf − (g_i − g_m)/Δg ]²
```

二者严格等价：

```
C_ZNSSD = 2 · (1 − C_ZNCC)
```

**设计决定**：
- **优化目标用 ZNSSD**（它是最小二乘形式，直接接 Gauss-Newton）。
- **对外报告的质量指标用 ZNCC**（直观、与 RG-DIC 排序一致、与文献/商业软件可比）。
- 二者由上式互转，只算一次。

**光照鲁棒性**：零均值项吸收**偏置** `b`，归一化项吸收**增益** `a`，故对 `g = a·f + b`（`a>0`）严格不变。这正是 HL3 选它而不用 SSD/CC 的原因（Pan et al. 2013 用同一准则）。注意：**非均匀**光照（空间变化的 `a(x), b(x)`）不被吸收；对此提供可选的
- 预处理：局部对比度归一化（CLAHE 或局部均值-方差归一化），或
- 扩展准则：把 `(a, b)` 作为额外形函数参数联合求解（可选 `ZNSSD+PHOTOMETRIC`，2 个额外自由度）。

### 2.3 图像预处理

按 iDICs GPG §5.2.2，预滤波要慎用（会引入偏差），故默认关闭，但提供：

- `NONE`（默认）
- `GAUSSIAN(σ)`：低通，对高噪声/无抗混叠滤光片的相机有用；σ 默认 0.8 px。
- `BOX(k)`
- 位深提升：8-bit 图像在插值前不做任何量化补偿（保持可溯源），但噪声模型知道其量化步长。

预滤波是否启用**必须**出现在报告里（GPG §6.2.1 必填项 "Image Filtering, if applied"）。

**梯度**：参考图梯度 `f_x, f_y` 用 **4 阶中心差分**（与 OpenCorr 一致，也是最常用的选择）：

```
f_x(i,j) = [ f(i−2,j) − 8f(i−1,j) + 8f(i+1,j) − f(i+2,j) ] / 12
```

边界 2 像素带用降阶差分。梯度在参考图上算一次并缓存（IC-GN 的核心优势之一）。

### 2.4 整数像素初值：FFT-CC

对 POI 在参考图取 subset `f`，在目标图取同样大小（或放大 `search_factor` 倍，默认 2）的搜索窗 `g`。

```
1. 零均值化：F = f − f_m,  G = g − g_m
2. 频域互相关：R = IFFT( conj(FFT(F₀)) ⊙ FFT(G) )     // F₀ 为零填充到搜索窗尺寸
3. 归一化：ZNCC_map = R / (Δf · Δg_local)
   （Δg_local 用积分图 O(1) 逐位置算局部均值/方差，得到真正的 ZNCC 而非裸 CC）
4. 取峰 (du, dv) = argmax
5. 可选三点抛物/高斯峰拟合 → ~0.1 px 初值
```

复杂度 `O(M² log M)`（`M` = 搜索窗边长），比暴力 `O(M²·N)` 快得多。FFTW（或 cuFFT / pocketfft）后端；每线程独立 plan 与工作缓冲（OpenCorr 的 `FFTW` 辅助类是同样的并行化处理）。

**副产品**：subset 自相关的半高宽 → 平均散斑尺寸估计，直接喂给 §1.3 的向导。

### 2.5 形函数（Shape Function）

**一阶（仿射，6 参数）** `p₁ = (u, u_x, u_y, v, v_x, v_y)`：

```
Δx' = Δx + u + u_x·Δx + u_y·Δy
Δy' = Δy + v + v_x·Δx + v_y·Δy
```

齐次矩阵形式（作用于 `[Δx, Δy, 1]ᵀ`）：

```
W₁(p) = [ 1+u_x    u_y     u  ]
        [ v_x     1+v_y    v  ]
        [  0        0      1  ]
```

- **合成**：`W(p) ← W(p) · W(Δp)⁻¹`，其中 `W(Δp)⁻¹` 是 3×3 精确逆（闭式）。
- **雅可比** `∂W/∂p`（2×6）：
  ```
  ∂W/∂p = [ 1  Δx  Δy  0   0   0  ]
          [ 0   0   0  1   Δx  Δy ]
  ```

**二阶（12 参数）** `p₂ = (u, u_x, u_y, u_xx, u_xy, u_yy, v, v_x, v_y, v_xx, v_xy, v_yy)`：

```
Δx' = Δx + u + u_xΔx + u_yΔy + ½u_xxΔx² + u_xyΔxΔy + ½u_yyΔy²
Δy' = Δy + v + v_xΔx + v_yΔy + ½v_xxΔx² + v_xyΔxΔy + ½v_yyΔy²
```

- **雅可比** `∂W/∂p`（2×12）：
  ```
  行 x: [1, Δx, Δy, ½Δx², ΔxΔy, ½Δy², 0, 0, 0, 0, 0, 0]
  行 y: [0, 0, 0, 0, 0, 0, 1, Δx, Δy, ½Δx², ΔxΔy, ½Δy²]
  ```
- **合成与求逆**：Gao et al. (2015, OLE 65:73-80) 给出等价的 6×6 齐次矩阵形式（作用于 `[Δx², Δy², ΔxΔy, Δx, Δy, 1]ᵀ`）。HL3 的**实现建议**是直接用多项式代换 + 截断，理由是可读、可用符号代数（sympy）在单测中逐系数验证，且不依赖任何一篇论文的排版：

  *合成* `W(p) ∘ W(Δp)`：把 `W(Δp)` 的输出多项式代入 `W(p)`，展开后**丢弃三阶及以上项**，读出新的 12 个系数。

  *求逆* `W(Δp)⁻¹`：记 `W(Δp)(ξ) = ξ + d(ξ)`，则二阶截断的逆为
  ```
  W⁻¹(ξ) = ξ − d(ξ) + (∇d)(ξ)·d(ξ) + O(‖d‖³)
  ```
  展开后同样只保留至二阶项。因为 `Δp` 每次迭代都很小，截断误差在收敛意义下可忽略（这正是 IC 框架成立的前提）。

  单测（§5.12）用 sympy 独立展开，逐系数比对到 `1e-12`，确保这段代数没写错。

**选型建议**：
- `ICGN1` 默认。变形接近均匀应变（拉伸、纯剪、小旋转）时最快最稳。
- `ICGN2` 在**高应变梯度、非线性变形、散斑刚性（speckle rigidity）**场景显著更好，并能抑制 SRI 误差；代价是 12×12 Hessian、约 2–3× 计算量、更需要更大的 subset（推荐 `subset ≥ 31`，否则二阶项病态）。
- HL3 提供 `AUTO`：先跑 ICGN1，若局部应变梯度估计超过阈值（由邻域位移二阶差分估计）则该点自动升级到 ICGN2。

### 2.6 ICGN 求解器

**逆合成（Inverse Compositional）的关键**：把 warp 增量施加在**参考图**上，于是 `∇f`、`∂W/∂p`、Hessian **全部与 `p` 无关，只算一次**。这是 IC-GN 相对 FA-NR 快 3–5 倍的根本原因（Pan, Li & Tong 2013）。

每次迭代求解：

```
min_{Δp}  Σ_i [ (f(W(Δx_i; Δp)) − f_m)/Δf  −  (g(W(Δx_i; p)) − g_m)/Δg ]²
```

线性化 `f(W(Δx; Δp)) ≈ f(Δx) + ∇f · (∂W/∂p) · Δp`，得

**预计算（每 POI 一次）**：

```
J_i = ∇f(Δx_i) · (∂W/∂p)|_{Δx_i, p=0}        // 1×n 行向量，n = 6 或 12
                                              // = [f_x, f_x·Δx, f_x·Δy, f_y, f_y·Δx, f_y·Δy]  (n=6)
H   = (2/Δf²) · Σ_i J_iᵀ J_i                  // n×n，对称正定
H⁻¹ ← Cholesky 分解并缓存（LDLᵀ，带对角加载 λ·tr(H)/n，λ=1e-8，防病态）
```

**每次迭代**：

```
1. 在目标图上按 W(Δx_i; p) 采样 g_i（插值，§2.10）
2. 算 g_m, Δg
3. 残差   e_i = (f_i − f_m) − (Δf/Δg)·(g_i − g_m)
4. 右端项 b = (2/Δf²) · Σ_i J_iᵀ · e_i
5. Δp = −H⁻¹ b            // 注意：Σ J_iᵀ e_i 中 e_i 的符号约定要与上式一致
6. W(p) ← W(p) ∘ W(Δp)⁻¹
7. 收敛判据（下）；否则回 1
```

**收敛判据**（尺度化范数，把梯度分量按 subset 半径换算成"边缘处的位移"）：

```
一阶：s = (1, r, r, 1, r, r)
二阶：s = (1, r, r, r²/2, r², r²/2, 1, r, r, r²/2, r², r²/2)
ζ = sqrt( Σ_k (Δp_k · s_k)² )
收敛 ⟺ ζ < conv_tol          （默认 conv_tol = 1e-3 px）
```

**终止与失败判定**：

| 条件 | 处理 |
|---|---|
| `ζ < conv_tol` | 收敛，`converged = true` |
| 迭代数 `> max_iter`（默认 20） | `NOT_CONVERGED` |
| warp 后 subset 越出图像边界 | `OUT_OF_BOUNDS` |
| `Δf < eps` 或 `Δg < eps`（无纹理/饱和） | `SINGULAR_HESSIAN` |
| `cond(H) > 1e10` | `SINGULAR_HESSIAN`（可回退 ICLM，见下） |
| 收敛但 `ZNCC < zncc_min`（默认 0.8） | `LOW_ZNCC`（结果保留但标记，不参与应变拟合） |
| `‖p_disp‖` 超过 `max_disp` | `DIVERGED` |

**ICLM 可选后备**：把 `H` 换成 `H + λ·diag(H)`（Levenberg-Marquardt 阻尼），`λ` 按经典策略自适应。OpenCorr 的公开评述指出 ICLM 整体不如 ICGN，故 HL3 把它做成**仅在 ICGN 失败时触发的后备**，而不是默认。

**输出（每 POI）**：`x₀, u, v, p[n], ZNCC, iterations, converged, status, cov[n×n]`。

**协方差（内建 UQ，见 §6.2）**：在图像噪声为独立同分布高斯 `σ_n`（两幅图各自独立）的假设下，

```
Cov(p) ≈ 2 σ_n² · H_raw⁻¹ ,   H_raw = Σ_i J_iᵀ J_i
```

对纯位移分量退化为经典结果

```
σ_u ≈ √2 · σ_n / sqrt( Σ_i f_x²(Δx_i) )
```

`σ_n` 由静态帧对（噪声底板）或相机噪声模型估计。**每个点每帧都带 1σ 不确定度**，这是 HL3 相对闭源商业软件最有说服力的差异化输出之一（§6.2）。

### 2.7 大位移 / 大旋转的初值链

```
优先级 1: PREV_FRAME    —— 上一帧同点的 p（序列分析默认，最快）
优先级 2: RG 邻点传递    —— 可靠性引导（§2.8）
优先级 3: FFT-CC        —— 整数搜索（§2.4）
优先级 4: SIFT + RANSAC 仿射 —— 大平移/大旋转/大变形
优先级 5: 用户指定
```

`SIFT_AFFINE`：在参考/目标图提 SIFT 特征并匹配（比值检验 0.75），对每个 POI 取半径 `R`（默认 `3·subset`）内的匹配对（不足则 kNN 补齐，再不足则暴力搜索），用 RANSAC 拟合局部仿射矩阵，直接得到 `(u, v, u_x, u_y, v_x, v_y)` 六个初值。这是 OpenCorr `FeatureAffine` 公开描述的做法，对 ICGN 的收敛半径是数量级的提升。

### 2.8 计算路径策略

**(a) 可靠性引导 RG-DIC**（Pan 2009, Appl Opt 48:1535）：

```
优先队列 Q（按 ZNCC 降序），已算掩膜 M_c，有效掩膜 M_v
1. 对每个 seed 求解 → 入队
2. while Q 非空:
     取出 ZNCC 最高的点 P
     对 P 的 4/8 邻居 P'（M_v=1 且 M_c=0）:
        用 P 的 p 作初值，求解 P'
        M_c[P'] = 1，按 ZNCC 插入 Q
```

优点：计算路径总是沿最可靠方向，天然跳过阴影/去相关/不连续区域，不会传播坏点误差。缺点：**本质串行**。

**(b) 路径无关 Path-Independent**：每个 POI 独立用 FFT-CC 或 SIFT-affine 求初值，完全并行。优点：线性可扩展、可 GPU 批处理、**结果与线程数无关（确定性）**。缺点：初值质量差时失败率高。

**(c) 混合 HYBRID（HL3 默认）**：

```
1. AOI 按连通性分块（默认块 128×128 POI，重叠 1 圈）
2. 每块选 1–3 个块内 seed（用 FFT-CC 或 SIFT-affine 求解并校验）
3. 块内跑 RG-DIC（串行但块小）
4. 块间并行（线程池）
5. 重叠圈做一致性检查；不一致的块用邻块结果重算
6. 全场失败点做第二轮：用已收敛邻点的加权平均作初值重试
```

这样既保留 RG 的鲁棒性，又拿到接近线性的并行加速。OpenCorr 的公开文档指出其 DIC 类被设计成 path-independent 但可组合出 RG；HL3 把这个组合直接做成默认策略。

**确定性保证**：`deterministic = true` 时，块划分、seed 选择、队列 tie-break 全部用固定规则（按 `(y, x)` 字典序），保证任何线程数下逐位相同的结果。

### 2.9 参考图更新（大变形）

固定参考在大变形下会因散斑失真而去相关。三种模式：

- `FIXED`：始终以第 0 帧为参考。最高精度（无误差累积），适用小变形。
- `EVERY_N(n)`：每 n 帧换参考。
- `INCREMENTAL(threshold)`（**推荐**，Pan et al. 2011 OLE 50:586 的增量 RG-DIC 思路）：
  ```
  监控全场 ZNCC 中位数；当中位数 < threshold（默认 0.85）时：
    - 把当前帧设为新参考
    - 记录累积 warp：p_total = p_prev_total ∘ p_current
    - 位移累加：u_total(X) = u_prev_total(X) + u_current(x_deformed)
      （注意需要在变形构形上插值上一段的位移场，用薄板样条或线性三角插值）
    - 变形梯度按链式法则相乘：F_total = F_current · F_prev_total
  ```
  必须在 UI 与报告中标注参考更新发生的帧号，因为它引入误差累积（每次更新累加一次噪声）。HL3 同时输出"累积更新次数"和"估计累积误差上界"。

### 2.10 插值

插值是 DIC **系统偏差的主要来源之一**（iDICs GPG §5.4.3 脚注 24 明确点名 interpolant 与 aliasing 会造成空间周期性偏差）。HL3 提供四档：

| 方法 | 支撑 | 用途 | 相对偏差 |
|---|---|---|---|
| `BILINEAR` | 2×2 | 仅预览/实时降级 | 很大（0.05 px 量级 S 曲线） |
| `KEYS_BICUBIC` | 4×4 | 快速档；Keys (1981) 卷积核，`a = −0.5` | 中 |
| `BICUBIC_BSPLINE` | 4×4（需预解系数） | **默认** | 小 |
| `QUINTIC_BSPLINE` | 6×6（需预解系数） | 高精度档 | 最小 |

选择依据：Pan et al. (TAML 2016, 6(3):126-130) 的公开结论是**双三次 B 样条相对双三次卷积插值在精度与精密度上显著改善，代价很小**；OpenCorr 因此把 `BicubicBspline` 作为其插值实现。五次 B 样条进一步降低偏差，被 Ncorr/DICe 一类实现用于高精度场合。

**实现要点**：

1. **系数预解一次**：B 样条需要先解一个可分离的三对角（或五对角）系统得到系数场 `c(i,j)`，对整幅目标图做一次，`O(WH)`，之后每次采样 `O(k²)`。这一步必须在帧级做，不能在 POI 级重复做。
2. **系数查找表（LUT）**：Pan et al. 2013 提出的插值系数 LUT——把每个像素单元的双三次多项式 16 个系数预存，采样时只做多项式求值，避免重复求核。内存代价 `16×W×H×4 B`（1 MP 图约 64 MB），可按 `--interp-lut` 开关，大图或显存紧张时关闭。
3. **边界**：镜像延拓（`reflect101`），并在 POI 层用 `OUT_OF_BOUNDS` 显式拒绝真正越界的 subset，不让边界外推污染结果。
4. **梯度不用插值器算**：参考图梯度用 §2.3 的 4 阶差分，不用 B 样条解析导数（两者混用会导致 IC-GN 的一致性问题）。这条要在实现里明确注释。

### 2.11 应变计算

**步骤 1：局部位移拟合（PLS，Pointwise Least Squares）**（Pan et al. 2007, Opt Eng 46:033601）

在 POI `x₀` 周围取 `L_window × L_window` 个**数据点**（不是像素）构成拟合邻域，仅保留 `ZNCC ≥ zncc_threshold` 的点。以 `Δx = x − x₀`（单位：像素）拟合

线性（默认）：
```
u(Δx, Δy) = a₀ + a₁Δx + a₂Δy
v(Δx, Δy) = b₀ + b₁Δx + b₂Δy
```
二次（`strain_fit_order = QUADRATIC`，高梯度用）：
```
u = a₀ + a₁Δx + a₂Δy + a₃Δx² + a₄ΔxΔy + a₅Δy²
```

加权最小二乘，权重 `w_i = exp(−(Δx_i²+Δy_i²)/(2σ²))`，`σ = L_window·L_step/4`。解正规方程 `(AᵀWA)c = AᵀWu`（3×3 或 6×6，Cholesky）。

在中心点取导数：
```
u_x = a₁,  u_y = a₂,  v_x = b₁,  v_y = b₂
```

若有效邻点数 `< neighbor_min`，该点应变 `= NaN`（不外推、不用零填充——这是很多软件的隐性坑）。

**步骤 2：变形梯度**

```
F = I + ∇u = [ 1+u_x    u_y  ]
             [  v_x    1+v_y ]
```

**步骤 3：应变张量族**（全部实现，用户选择，报告必须标注）

*工程 / Cauchy 小应变*（拉格朗日描述下的线性化）：
```
ε_xx = u_x
ε_yy = v_y
ε_xy = ½(u_y + v_x)          （张量剪应变）
γ_xy = u_y + v_x             （工程剪应变）
```
⚠️ 对刚体转角 `θ` **不为零**（≈ −θ²/2 的伪压缩），只在 `|θ| ≪ 1` 且应变 ≪ 1 时有效。

*Green-Lagrange*（参考构形，**默认**）`E = ½(FᵀF − I)`：
```
E_xx = u_x + ½(u_x² + v_x²)
E_yy = v_y + ½(u_y² + v_y²)
E_xy = ½(u_y + v_x + u_x·u_y + v_x·v_y)
```
⚠️ 对纯刚体转动**严格为零**——这是关键的正确性测试（§5.9）。

*Euler-Almansi*（当前构形）`e = ½(I − F⁻ᵀF⁻¹)`。

*对数 / Hencky*：由右伸长张量 `U = √(FᵀF)`，`ε_H = ln U`。2×2 情形用解析特征分解：
```
C = FᵀF;  λ₁,₂ = 特征值;  ε_H = Σ_k ½ln(λ_k) · n_k n_kᵀ
```

*主应变与方向*（对任一对称二阶张量 `ε`）：
```
ε₁,₂ = (ε_xx+ε_yy)/2 ± sqrt( ((ε_xx−ε_yy)/2)² + ε_xy² )
θ_p  = ½ · atan2( 2ε_xy , ε_xx − ε_yy )
γ_max = ε₁ − ε₂
```

*等效应变*：
```
von Mises（平面应力 + 不可压近似）: ε_eq = (2/3)·sqrt( ε₁²+ε₂²+ε₁ε₂ ) 的常用形式，
   实现上给出显式公式并在文档中写清所用假设
Tresca: ε₁ − ε₂
面积变化率: det(F) − 1
面内转角: θ = ½(v_x − u_y)（小转角）或从 F 的极分解 F = RU 取 R 的角（大转角，推荐）
```

**步骤 4：可选后滤波**

高斯/中值/多项式滤波，窗口 `L_filter`。启用后 `L_VSG` 用 `L_filter` 代入式 (7.2)。**默认关闭**并在 UI 上警告：后滤波会同时降噪与引入偏差（GPG §5.4.4）。

**VSG 尺寸（始终计算并显示）**：

```
L_VSG = (L_window − 1)·L_step + L_subset        [px]        (iDICs GPG Eq. 7.2)
```

其中 `L_window` 取 strain window 与 filter window 中实际生效的那个。

**替代应变方案**（供高级用户与对照）：
- `FROM_SHAPE_FUNCTION`：直接从 ICGN 的 `p` 中的 `u_x, u_y, v_x, v_y` 取应变。此时 `L_VSG ≈ L_subset`（最小 VSG、最高空间分辨率、最大噪声），对应 GPG §5.3.2.1。
- `FE_SHAPE_FUNCTION`：三角网格 + FE 形函数求应变，对应 GPG §5.3.2.2。
- `GLOBAL_SPLINE`：全场样条拟合，对应 GPG §5.3.2.4。

四种方案全部实现，因为 iDICs 明确指出不同软件用不同方案、VSG 定义因此不同——**HL3 能同时给出四种，这本身就是超越闭源软件的可比性优势**。

### 2.12 后处理算子链

后处理是**有序、可逆、可序列化**的算子链，作用在场上而不改原始数据：

```
PostOp := RigidBodyRemoval(region, mode)
        | Filter(field, kernel, size)
        | CustomVariable(name, expression)     // 表达式引擎，见下
        | Resample(target_grid)
        | Mask(condition)                      // 例如 zncc < 0.8 → NaN
        | TemporalSmooth(window)
```

**自定义变量表达式引擎**（对标 VIC-2D 的"自定义变量公式"）：一个安全的表达式子集（不是任意代码执行），支持

- 变量：`u, v, x, y, X, Y, exx, eyy, exy, e1, e2, F11..F22, zncc, t, frame`
- 模拟量：`analog.load`, `analog.temp`
- 函数：算术、`sqrt, exp, log, sin, cos, atan2, abs, min, max, if(c,a,b)`
- 空间/时间算子：`grad_x(·), grad_y(·), d_dt(·), integral(·)`
- 归约：`mean(·), max(·)`（在 AOI 或指定区域上）

编译为字节码，向量化执行（对整个场一次求值）。Python API 里也可以直接给 numpy 函数（§1.13），二者结果必须一致（测试保证）。

### 2.13 全局 DIC 与 AL-DIC 模式（可选内核）

局部 subset DIC 的两个公开短板：位移场不满足运动学协调性；小 subset 时变形梯度噪声大。HL3 在**同一数据模型下**提供两个额外求解模式：

**(a) `GLOBAL_FE`**：有限元全局 DIC（muDIC / 2D_FE_Global_DIC 一类）。以 Q4/Q8 单元或 B 样条单元离散位移场，最小化

```
Φ(U) = Σ_{x∈ROI} [ f(x) − g(x + N(x)·U) ]²  +  α·R(U)
```

`N` 是形函数矩阵，`R` 是正则项（Tikhonov 或机械正则）。Gauss-Newton 求解，稀疏 Hessian（Eigen SimplicialLDLT / CHOLMOD）。天然给出协调位移场与直接可用的 FE 网格结果。

**(b) `ALDIC`**：增广拉格朗日 DIC（Yang & Bhattacharya 2019, Exp Mech 59:187–205）。用 ADMM 把"局部逐 subset IC-GN"和"全局 FE 协调性"解耦：

```
重复直到收敛:
  子问题 1（局部，完全并行）: 对每个 subset 用 IC-GN 更新 {u_i, F_i}
                              （目标里加入 μ/2‖u_i − û_i + v_i‖² + β/2‖F_i − D û + W_i‖²）
  子问题 2（全局，稀疏线性）: 解 FE/有限差分问题得到协调的 û
  乘子更新:                   v ← v + (u − û),   W ← W + (F − Dû)
```

优点（其公开论文与 DIC Challenge 2.0 评测所主张）：兼具局部方法的速度/并行性与全局方法的协调性，抑制噪声与孤立坏点，对位移不连续更稳。

**HL3 的定位**：`LOCAL` 是默认与计量基准；`GLOBAL_FE` / `ALDIC` 是同一 GUI/CLI/Python 下的可切换模式，结果写入同一 HDF5 schema，可与 `LOCAL` 逐点对比。**这是 VIC-2D 公开产品形态中没有的能力**，也是 EikoSim/MatchID 一类竞品的叙事重点（见 `research/oss_dic_landscape.md`）。

### 2.14 GPU 后端

`hl3_gpu` 用 CUDA（首选）+ Vulkan compute（跨厂商后备）：

- **批量 ICGN**：一个 warp（32 线程）处理一个 POI 的 subset 求和归约；`H` 与 `H⁻¹` 在 POI 私有的共享内存里；插值系数走纹理内存/`__ldg`。路径无关模式下可一次跑数万 POI。
- **插值系数预解**：可分离三对角求解在 GPU 上做行/列并行。
- **FFT-CC**：cuFFT 批量。
- **精度**：ICGN 内部残差与 Hessian 累加用 `double`（或 Kahan 补偿的 `float`），最终位移用 `double`；否则大 subset 累加会吃掉亚像素精度。GPU/CPU 一致性测试见 §5.15。
- **回退**：GPU 上不收敛的点自动回 CPU 用 ICGN2/ICLM 重试。

---

## 3. 二维特有的误差与陷阱

### 3.1 离面运动（Out-of-Plane Motion）—— 2D-DIC 的头号系统误差

iDICs GPG **Caution 2.1** 写得很直白：2D-DIC 假设试样是平面的、测试中保持平面、垂直于光轴、且工作距离 SOD 恒定。任何非预期离面运动（试样减薄、屈曲、夹具不对中引起的旋转/平移）都会造成误差。GPG 甚至给出 **Recommendation：只要条件允许就应优先用立体 DIC，2D-DIC 只在两台相机物理装不下时才推荐**。

**量化模型（针孔相机）**：放大率 `M = f/(L − f) ≈ f/L`（`L` = SOD）。SOD 变化 `Δz` 导致

```
ΔM/M ≈ −Δz / L
```

即产生一个**均匀的伪膨胀/伪压缩应变**：

```
ε_伪 ≈ −Δz / L        （各向同性，同时出现在 ε_xx 和 ε_yy）
```

数值感受：`L = 500 mm`，`Δz = 0.5 mm` → `ε_伪 ≈ −1000 µε`。这足以完全淹没弹性段的真实应变。

**离面转动** `α`（绕面内某轴）产生**非均匀的伪单轴应变与伪应变梯度**，且**即使用双远心镜头也无法消除**（iDICs DIC101 Ch.2 的明确警告，Arrington et al. 2025 综述亦重申）。

**HL3 的应对（工具化，而不是只写在手册里）**：

1. **设计期计算器**：向导中输入 `L`、预估 `Δz`、预估真实应变量级，直接算出信噪比并给红/黄/绿判定；若伪应变 > 真实应变的 10%，明确建议改用 HL3-3D（立体）。
2. **镜头建议**：GPG **Recommendation 2.6** —— 若必须用 2D-DIC，推荐**双远心镜头**以抑制离面平移误差；无远心镜头时用长焦距、加大 SOD。同时明确提示：远心镜头不能修正离面转动，且**不得用于立体 DIC**（GPG Caution 2.5）。
3. **在线检测**：DIC 结果中若出现"全场近似均匀的等值双轴应变"且与载荷不成物理关系，自动弹出离面运动告警（一个简单但极实用的启发式：`|ε_xx − ε_yy|` 很小而 `(ε_xx+ε_yy)/2` 显著非零，且与载荷曲线相关性差）。
4. **补偿选项**（文献方法，标注为高级功能并要求用户确认前提）：
   - **补偿板法**（Pan 等提出，Wittevrongel 等验证，Xu 等改进）：在试样上刚性附加一块不变形的补偿板，用其上的伪应变反推并扣除离面/畸变误差。前提是补偿板确实不变形且随试样同步运动。
   - **图像矫正法**（Lava 等提出，Wittevrongel、Hijazi 等改进）：数值变换图像使其等效于垂直拍摄，可同时修正相机不垂直与镜头畸变，但**修不了测试过程中发生的离面运动**。
   - **单相机内外参标定法**：GPG 脚注指出，若对 2D 单相机做完整内外参标定，则试样的离面倾斜可被测定并修正（GPG 自己把它列为超出该版范围的高级话题）。HL3 实现它并明确标注为高级功能。
5. **报告强制项**：报告中必须出现"离面运动评估"章节，即使结论是"未评估"也要显式写出——这直接呼应 GPG Recommendation 2.3。

### 3.2 镜头畸变与标定

**iDICs 的立场**：镜头畸变未校正是**偏差误差**的明确来源（GPG §5.4.3）；若不做完整标定，应通过**刚体面内平移图像**评估畸变量级。GPG 同时建议使用中等光圈（典型 f/5.6–f/11）以避免极端光圈下的畸变放大与衍射极限，并优先选择可锁定焦距/光圈的镜头。

**HL3 的畸变模型**（与 OpenCV / OpenCorr `Calibration` 对象兼容，便于交叉验证）：

```
径向:   x_d = x(1 + k₁r² + k₂r⁴ + k₃r⁶) / (1 + k₄r² + k₅r⁴ + k₆r⁶)
切向:   + [ 2p₁xy + p₂(r² + 2x²) ,  p₁(r² + 2y²) + 2p₂xy ]
（可选薄棱镜 s₁..s₄；内参 fx, fy, fs(斜切), cx, cy）
```

标定流程：Zhang (2000) 平面标定板（棋盘或圆点），≥ 15 张不同姿态，Levenberg-Marquardt 光束法平差，输出重投影残差（**标定分数**，GPG 术语 Calibration Score）与参数协方差。

去畸变两种实现：
- **图像级**：预先对整个序列重采样到无畸变图像。优点简单；缺点重采样引入一次额外插值偏差。
- **坐标级**（推荐）：只对 POI 与 subset 采样坐标做去畸变映射，图像本身不动。避免二次插值。OpenCorr 的 `Calibration::undistort` 用预建的畸变映射表 + 线性插值做同样的事。

**畸变自检工具 `distortion-check`**：拍 ≥ 5 组已知的刚体面内平移图，跑 DIC，把"测得位移 − 全场刚体拟合"的残差画成矢量场与热图。若残差峰值 > `0.02 px` 则提示需要标定。这把 GPG 的建议做成一条命令。

### 3.3 尺度：SEM 与光学显微镜

VIC-2D 8 公开提到"显微镜/SEM 模块"。HL3 的 `hl3_calib2d` 对应提供：

**SEM 特有误差**（Sutton et al. 2007, Exp Mech 47:775 与 47:789 两篇公开论文系统给出）：

1. **空间畸变（spatial distortion）**：扫描电子束的几何畸变，随放大倍率变化。校正法：在无载荷状态下平移试样台采一组图，用 DIC 测出的"应有为刚体"的残差场拟合畸变多项式（通常 2 阶或 3 阶二维多项式），作为该放大倍率的畸变修正表。
2. **时间漂移（drift distortion）**：SEM 是逐行扫描，图像不是同一时刻的快照；束流漂移、样品充电、热漂移在一帧内就会累积。校正法：在同一位置连续采 N 帧（无载荷），用 DIC 测出的时间演化拟合漂移模型（通常线性 + 逐行项），逐帧扣除。
3. **充电/对比度漂移**：ZNSSD 的零均值归一化能吸收全局增益/偏置，但吸收不了局部充电。需要局部对比度归一化预处理。
4. **HL3 实现**：`SemCorrection { spatial_poly_order, drift_model, calib_images }`，在相关之前作为坐标级修正应用，与镜头畸变走同一条修正管线。

**光学显微镜特有问题**：

1. **景深极浅**：微米级离面运动就可能失焦。HL3 提供**焦点质量指标**（Tenengrad / 拉普拉斯方差）逐帧监控，失焦帧自动标记。
2. **放大倍率标定**：用载物台千分尺 / 标准光栅（如 10 µm 栅距）在同一光路条件下标定 `px/µm`；支持多点标定与场内均匀性检查。
3. **远心/近远心**：显微物镜通常是像方远心，仍需评估离面敏感度。
4. **照明不均与漂白**：荧光/偏光成像下灰度随时间整体下降。ZNSSD 的归一化吸收一阶效应；提供 flat-field 校正（`(I − dark)/(flat − dark)`）作为可选预处理。
5. **散斑制备**：微观尺度上散斑通常是纳米颗粒沉积、光刻图案或材料自然纹理。HL3 的图案体检（§1.3）在微观图像上同样适用，且要额外报告"自然纹理"情形下的 MIG 与各向异性（自然纹理常有强方向性，导致 `σ_u ≠ σ_v`）。

### 3.4 其他 2D 陷阱清单（在 UI 中做成检查项）

| 陷阱 | 检测方式 | 提示 |
|---|---|---|
| 相机不垂直 | 标定外参的倾角；或刚体平移的残差呈线性梯度 | 建议图像矫正或重新对中 |
| 相机热漂移 | 静态帧序列的位移均值随时间单调变化（GPG §5.4.3） | 预热 30 min 以上 |
| 热浪/气流 | 静态帧位移标准差的低频抖动 | 加隔离罩 |
| 像素饱和 | 直方图右端堆积 | 降曝光/降增益 |
| 混叠（aliasing） | 散斑特征 < 3 px；插值偏差 S 曲线幅值大 | 降放大或加低通 |
| 卷帘快门 | 相机元数据 | GPG Recommendation 2.5 推荐全局快门 |
| 图像有损压缩 | 文件格式检测（JPEG） | 拒绝或强警告 |
| 位深不足 | 8-bit + 低动态范围 | 建议 ≥ 10-bit 或改善照明 |
| 散斑与试样一起变形失效 | 高应变时 ZNCC 系统性下降 | 提示增量参考更新或换制斑工艺 |
| step 过小导致伪空间分辨率 | `step < subset/3` | 提示邻点不独立（GPG §5.2.6） |

---

## 4. 模块与文件布局提案

### 4.1 顶层

```
src/
├── hl3_core/        # 共享基础：类型、图像、ROI、POI、场、线程池、日志、错误、配置
├── hl3_imgio/       # 图像/序列 IO、元数据、内存映射、缓存
├── hl3_interp/      # 插值：Keys 双三次 / 双三次 B 样条 / 五次 B 样条 + 系数 LUT
├── hl3_calib2d/     # 尺度标定、Zhang 标定、畸变、图像矫正、SEM/显微校正
├── hl3_corr2d/      # ★ 2D 局部相关内核（本文重点）
├── hl3_global2d/    # 全局 FE-DIC + AL-DIC(ADMM)
├── hl3_strain/      # PLS / FE / 样条应变 + 张量族 + VSG
├── hl3_postproc/    # 刚体去除、滤波、自定义变量表达式引擎、提取器
├── hl3_uq/          # 噪声底板、VSG 研究、协方差传播、Monte Carlo
├── hl3_sync/        # 模拟量通道、时间对齐、DAQ 抽象
├── hl3_io/          # HDF5 schema、CSV/Parquet、VTK/VTU、STL/OBJ/PLY、MAT、Exodus
├── hl3_rt2d/        # 实时 2D 流水线
├── hl3_gpu/         # CUDA / Vulkan 后端
├── hl3_project/     # 工程对象、状态机、provenance
├── hl3_py/          # pybind11 绑定
├── hl3_cli/         # hl3-dic2d 可执行文件
├── hl3_gui/         # Qt6 前端（AOI 编辑器、向导、绘图）
└── hl3_report/      # iDICs 报告模板生成
```

与 R1-O2（HL3-3D）与 R1-O3（共享内核）的边界：`hl3_core / hl3_imgio / hl3_interp / hl3_strain / hl3_postproc / hl3_uq / hl3_io / hl3_sync / hl3_gpu / hl3_py / hl3_gui / hl3_report` **完全共享**；`hl3_corr2d` 与 `hl3_calib2d` 是 2D 专属；3D 增加 `hl3_stereo / hl3_calib3d / hl3_corr3d`。3D 的立体匹配复用 `hl3_corr2d` 的 ICGN 内核（只是初值来自极线约束），因此 `hl3_corr2d` 的 API 必须设计成**不假设"参考图与目标图是同一相机的不同时刻"**。

### 4.2 `hl3_corr2d` 内部

```
hl3_corr2d/
├── include/hl3/corr2d/
│   ├── types.hpp            # POI2D, Status, CorrelationParams, RunConfig
│   ├── criterion.hpp        # ZNCC / ZNSSD 及互转、subset 统计
│   ├── shape_function.hpp   # SF1/SF2 的 warp/compose/invert/jacobian（★ 见 4.3）
│   ├── gradient.hpp         # 4 阶中心差分梯度场
│   ├── fftcc.hpp            # FFT 加速整数搜索
│   ├── feature_affine.hpp   # SIFT + RANSAC 局部仿射初值
│   ├── icgn.hpp             # ICGN1 / ICGN2 求解器
│   ├── iclm.hpp             # LM 阻尼后备
│   ├── seed.hpp             # 起点检测与校验
│   ├── path.hpp             # RG / PathIndependent / Hybrid 调度
│   ├── incremental.hpp      # 参考更新与位移累加
│   └── engine.hpp           # Engine 门面
├── src/                     # 对应 .cpp
├── cuda/                    # icgn_kernel.cu, fftcc_cuda.cu（由 hl3_gpu 编译开关控制）
└── tests/                   # 见 §5
```

### 4.3 关键接口头文件草案

以下是**唯一**建议在 Round 2 优先落地的接口（其余按上表展开）。它刻意做到与 3D 复用、可 GPU 批处理、无隐藏全局状态。

```cpp
// hl3/corr2d/types.hpp
#pragma once
#include <array>
#include <cstdint>
#include <vector>
#include "hl3/core/image.hpp"     // hl3::Image2D (float32, row-major, 可切片)
#include "hl3/core/roi.hpp"       // hl3::Mask2D

namespace hl3::corr2d {

enum class Criterion  : uint8_t { ZNSSD, ZNCC_EQUIV };
enum class ShapeOrder : uint8_t { FIRST = 1, SECOND = 2, AUTO = 255 };
enum class Interp     : uint8_t { BILINEAR, KEYS_BICUBIC, BICUBIC_BSPLINE, QUINTIC_BSPLINE };
enum class Path       : uint8_t { RELIABILITY_GUIDED, PATH_INDEPENDENT, HYBRID };
enum class InitGuess  : uint8_t { PREV_FRAME, FFTCC, SIFT_AFFINE, USER };
enum class RefUpdate  : uint8_t { FIXED, EVERY_N, INCREMENTAL };
enum class BoundaryMode : uint8_t { STRICT, PARTIAL, SPLIT };

enum class Status : uint8_t {
  UNCOMPUTED, CONVERGED, LOW_ZNCC, NOT_CONVERGED,
  OUT_OF_BOUNDS, SINGULAR_HESSIAN, NO_INITIAL_GUESS, DIVERGED, MASKED
};

// n = 6 (FIRST) 或 12 (SECOND)；固定容量避免堆分配，便于 GPU 传输。
inline constexpr int kMaxParams = 12;

struct alignas(64) POI2D {
  float  x0, y0;                              // 参考构形坐标（去畸变后）
  std::array<float, kMaxParams> p{};          // 形函数参数
  float  zncc     = -1.0f;
  uint16_t iters  = 0;
  Status status   = Status::UNCOMPUTED;
  ShapeOrder order = ShapeOrder::FIRST;
  // 可选：Cov(p) 的上三角（UQ 打开时填充），长度 n(n+1)/2
  int32_t cov_offset = -1;                    // 指向外部协方差池的偏移，-1 = 无

  float u() const noexcept { return p[0]; }
  float v() const noexcept { return p[(order == ShapeOrder::SECOND) ? 6 : 3]; }
};

struct CorrelationParams {
  int   subset_radius_x = 10;    // subset 21x21
  int   subset_radius_y = 10;
  int   step            = 5;
  ShapeOrder shape      = ShapeOrder::FIRST;
  Interp interp         = Interp::BICUBIC_BSPLINE;
  Criterion criterion   = Criterion::ZNSSD;
  BoundaryMode boundary = BoundaryMode::STRICT;

  float conv_tol   = 1e-3f;      // px，尺度化 ||Δp||
  int   max_iter   = 20;
  float zncc_min   = 0.80f;      // 低于此值标记 LOW_ZNCC
  float max_disp   = 1e6f;       // px
  float hessian_reg = 1e-8f;     // 对角加载系数

  bool  compute_covariance = false;
  float image_noise_sigma  = 0.0f;  // 归一化灰度单位；0 = 自动从静态帧估计
};

// 单帧、单参考的相关求解门面。线程安全：compute() 可并发调用不同 POI 子集。
class Engine {
public:
  Engine(CorrelationParams params, int threads = 0);
  ~Engine();

  // 设置参考图：内部计算梯度场与（对 SECOND 阶）必要的缓存。
  void set_reference(const core::Image2D& ref, const core::Mask2D* mask = nullptr);
  // 设置目标图：内部预解插值系数（B 样条）与可选 LUT。
  void set_target(const core::Image2D& tgt);

  // 在 AOI 内按 step 生成 POI 网格（对齐到参考帧像素栅格）。
  std::vector<POI2D> make_grid(const core::Mask2D& aoi) const;

  // 就地求解。initial 决定初值来源；poi 中已有的 p 在 PREV_FRAME/USER 下被沿用。
  void compute(std::vector<POI2D>& poi, InitGuess initial, Path path);

  // 单点求解（供 3D 立体匹配等外部调度器复用）。
  void compute_one(POI2D& poi) const;

  const CorrelationParams& params() const noexcept;
  // 协方差池（compute_covariance = true 时有效）
  const std::vector<float>& covariance_pool() const noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace hl3::corr2d
```

设计约束说明：

- `POI2D` 是 POD 且 64 B 对齐 → 可直接 `cudaMemcpy`，也便于 SoA/AoS 转换。
- `compute_one` 单独暴露，是为了让 `hl3_corr3d` 的极线搜索能复用同一个 ICGN 内核（OpenCorr 的 `EpipolarSearch` 就是这样调用 `ICGN2D1` 的）。
- `Engine` 不持有图像所有权（只持引用），避免大序列下的隐式拷贝。
- 协方差用外部池 + 偏移，而不是每个 POI 内嵌 78 个 float，避免默认路径下 POI 结构体膨胀 6 倍。

### 4.4 HDF5 开放 schema（草案，与 R1-O3 对齐）

```
/                                   attrs: hl3_version, schema_version=1, created, uuid
├── /images/                        attrs: n_frames, width, height, dtype, scale_px_per_mm
│   ├── paths        [n_frames] str
│   ├── hashes       [n_frames] str (blake3)
│   └── timestamps   [n_frames] f64
├── /aoi/
│   ├── mask         [ny_img, nx_img] u8      （或逐帧 [n_frames, ny, nx] 稀疏）
│   └── shapes       json
├── /calibration/    intrinsics, distortion, scale, calib_score, sem_correction
├── /grid/
│   ├── x0           [n_poi] f32   参考构形坐标
│   ├── y0           [n_poi] f32
│   └── shape        [2] i32       （规则网格时的 ny, nx，便于 reshape）
├── /results/
│   ├── p            [n_frames, n_poi, n_params] f32   ★ 全部形函数参数，不只是 u,v
│   ├── zncc         [n_frames, n_poi] f32
│   ├── status       [n_frames, n_poi] u8
│   ├── iters        [n_frames, n_poi] u16
│   ├── cov          [n_frames, n_poi, n(n+1)/2] f32   （可选）
│   └── ref_frame    [n_frames] i32                    （增量参考时记录每帧的参考）
├── /strain/         按 (tensor, window) 组织的多组结果，每组带自己的 L_VSG 属性
├── /postproc/       算子链 json + 派生场
├── /analog/         [n_channels] 时间序列 + 对齐信息
├── /extractors/     提取器定义 + 时间序列
└── /provenance/     完整参数 json、git commit、环境指纹、向导结论、噪声底板、VSG 研究
```

关键决定：

1. **保存完整的 `p`，不只是 `u, v`**。形函数参数里的位移梯度是免费的应变估计，丢掉它等于丢掉信息。
2. **`status` 与 `zncc` 与场同维保存**，任何下游分析都能重建"哪些点可信"。
3. **schema 单独发布规范文档 + 参考 Python/MATLAB 读取器**，不依赖 HL3 二进制。这是相对闭源软件的结构性优势（§6.4）。
4. 压缩：`gzip` 或 `blosc:zstd`，chunk 按 `(1, n_poi, ·)` 切分以适配"按帧流式写入 + 按点读时间序列"两种访问模式。

---

## 5. 单元测试计划

测试哲学：**合成数据必须有解析真值，且生成器与求解器不能共用同一个插值器**——否则测的是"自洽性"而非"正确性"。这是 DIC 代码最容易骗过自己的地方。

### 5.0 合成散斑生成器（测试基础设施）

```
I(x, y) = I_bg + Σ_k A_k · exp( −((x−x_k)² + (y−y_k)²) / R_k² )
```

参数：散斑数密度（控制覆盖率 ≈ 50%）、半径 `R`（默认对应 3–5 px 特征）、位置泊松盘采样（避免过度重叠）、幅值抖动。

**变形图生成的两条路径（关键设计）**：

- **纯平移** → 用**傅里叶移位定理**生成，`g = IFFT( FFT(f) · exp(−2πi(u·ξ + v·η)) )`。对带限图像是**解析精确**的，完全不引入插值误差。这是检验插值偏差的唯一干净方式。
- **一般变形（旋转/应变/梯度）** → 用**解析散斑函数直接在变形坐标上求值**：对目标图每个像素 `x`，解 `X = W⁻¹(x)`（对仿射是闭式），把 `X` 代入上面的高斯和解析式，并做 `8×8` 子像素积分模拟像素积分效应。**不对参考图做重采样**，因此不引入求解器同款插值误差。

噪声与光照按下面各测试项叠加。

### 5.1 T1 亚像素平移扫描（插值偏差 / S 曲线）

- 输入：`u ∈ {0, 0.05, 0.10, …, 1.00}`，`v = 0`；傅里叶移位生成；无噪声。
- 断言（`subset=21`, `ICGN1`）：

| 插值 | 平均偏差 \|bias\| | 周期性偏差峰峰值 |
|---|---|---|
| `BILINEAR` | — | 仅记录基线，不设门槛 |
| `KEYS_BICUBIC` | < 0.01 px | < 0.02 px |
| `BICUBIC_BSPLINE` | < 0.005 px | < 0.008 px |
| `QUINTIC_BSPLINE` | < 0.002 px | < 0.004 px |
- 同时画出偏差-亚像素相位曲线并作为**基线快照回归**（数值存进 golden 文件，退化即失败）。
- 变体：散斑半径 `R ∈ {1.5, 2, 3, 5} px`，验证 `R < 3 px` 时混叠导致偏差骤增（对应 §3.4 的混叠陷阱）。

### 5.2 T2 亚像素平移 + 各向异性（`u` 与 `v` 同时非零）

`(u, v)` 取 21×21 网格覆盖 `[0,1]²`，断言二维偏差场无系统方向性偏置（`|mean(bias_u)| , |mean(bias_v)| < 0.003 px`）。

### 5.3 T3 刚体旋转

- `θ ∈ {0.1°, 0.5°, 1°, 2°, 5°, 10°, 20°, 30°, 45°}`，绕图像中心。
- `ICGN1`：`θ ≤ 5°` 时位移误差 `< 0.01 px`；`θ ≤ 30°` 时（配 `SIFT_AFFINE` 初值）`< 0.02 px`。
- **`GREEN_LAGRANGE` 应变必须 ≈ 0**：`max|E| < 5e-5`（这条是刚体不变性的硬性检验）。
- **`ENGINEERING` 应变必须 ≈ −θ²/2**（记录并断言符合理论，用于文档化"工程应变对大转角不适用"）。

### 5.4 T4 单向均匀应变

- `ε_xx ∈ {0.001, 0.01, 0.05, 0.10, 0.20, 0.50}`，`ε_yy = −ν·ε_xx`（`ν = 0.3`）。
- `ICGN1`：`ε ≤ 0.10` 时 `|Δε| < 1e-4`；`ε ≤ 0.50` 时配 `INCREMENTAL` 参考更新，`|Δε|/ε < 1%`。
- 断言 `ε_yy/ε_xx` 反算的泊松比误差 `< 0.01`。

### 5.5 T5 应变梯度 / 空间分辨率传递函数

- 位移场 `u(x) = A·sin(2πx/λ)`，`A = 0.5 px`，`λ ∈ {10, 20, 40, 80, 160, 320} px`。
- 测量幅值衰减 `Â/A` 对 `λ/L_VSG` 作图 → **空间分辨率传递函数**。
- 断言：`λ > 2·L_VSG` 时 `Â/A > 0.9`；`ICGN2` 在 `λ ∈ [20, 40]` 区间的 `Â/A` 显著优于 `ICGN1`（这是二阶形函数存在的理由，也对应文献中 ICGN-2 在非线性变形场更好的公开结论）。
- 该曲线也是 §6.2 UQ 报告里的标准输出。

### 5.6 T6 噪声

- 加性高斯噪声 `σ_n ∈ {0, 0.5, 1, 2, 5, 10} /255`（8-bit 灰度级 0.5–10）。
- 每个 `σ_n` 跑 100 次独立实现（不同噪声种子），统计位移标准差。
- **断言**：实测 `σ_u` 与理论 `σ_u = √2·σ_n / sqrt(Σ f_x²)` 的比值落在 `[0.8, 1.25]`。
- **断言**：`compute_covariance = true` 时，引擎报告的 `sqrt(Cov[0,0])` 与实测 `σ_u` 的比值落在 `[0.8, 1.25]`（验证内建 UQ 是可信的，不是装饰）。
- **断言**：`σ_u ∝ 1/subset_size`（近似），扫描 `subset ∈ {11,21,31,41}` 验证趋势。
- 泊松（散粒）噪声与量化噪声各一组。

### 5.7 T7 光照增益 / 偏置

| 变换 | 断言 |
|---|---|
| `g = a·f`，`a ∈ {0.5, 0.8, 1.25, 2.0}` | 位移误差变化 `< 1e-3 px` |
| `g = f + b`，`b ∈ {−50, −20, +20, +50}/255` | 位移误差变化 `< 1e-3 px` |
| `g = a·f + b` 组合 | 位移误差变化 `< 1e-3 px` |
| 线性空间梯度增益 `a(x) = 1 + 0.5·x/W` | **记录**误差（预期非零），断言 < 0.02 px；启用局部对比度归一化后 < 0.005 px |
| 局部高光斑（模拟反光） | 该区域 `ZNCC` 下降且被 `LOW_ZNCC` 正确标记 |
| 饱和裁剪 `min(g, 1.0)` | 饱和区被检测并告警 |

这组测试直接验证 ZNSSD 的零均值+归一化设计目标（§2.2）。

### 5.8 T8 组合工况与鲁棒性

- 平移 + 旋转 + 应变 + 噪声 + 增益偏置的全组合抽样（拉丁超立方，200 组）。
- 断言全局收敛率 `> 99%`，位移 RMSE `< 0.02 px`。
- 不连续场：中间插入一条 `NaN` 裂纹带 + 两侧刚体分离位移。断言 `RELIABILITY_GUIDED` 不跨裂纹传播错误初值，`SPLIT` 边界模式在裂纹两侧都能算出正确位移。
- 遮挡：随机遮挡 10% 面积，断言遮挡区标记为 `LOW_ZNCC` 而非给出错误位移。

### 5.9 T9 应变张量代数（纯代数，不用图像）

给定解析 `F`，直接检验张量实现：

| 输入 `F` | 断言 |
|---|---|
| `F = R(θ)`（纯旋转） | `E_GL = 0`（`< 1e-12`）、`e_EA = 0`、`ε_Hencky = 0`；`ε_eng ≠ 0` 且等于理论值 |
| `F = diag(1+ε, 1)` | `E_xx = ε + ε²/2`；`ε_log_xx = ln(1+ε)` |
| `F = R(θ)·diag(λ₁, λ₂)` | 主应变 = `f(λ₁), f(λ₂)`（与 θ 无关）；主方向 = θ |
| 随机 `F`（det > 0，1000 个） | `E` 与 `e` 满足 `e = F⁻ᵀ E F⁻¹`；`det(F)` 与面积变化率一致 |
| 极分解 `F = RU` | `R` 正交（`‖RᵀR − I‖ < 1e-12`）、`U` 对称正定 |

这组测试成本极低但能挡住绝大多数张量公式笔误。

### 5.10 T10 VSG 与参数一致性

- 对 `(L_subset, L_step, L_window)` 的 100 组组合，断言引擎报告的 `L_VSG` 严格等于 `(L_window−1)·L_step + L_subset`。
- 断言物理单位 `L_VSG_phys = L_VSG / image_scale`。
- 断言 `FROM_SHAPE_FUNCTION` 模式下 `L_VSG == L_subset`。
- 断言改变 `L_window` 后重算应变**不触发**相关重算（性能契约测试，用计数器验证）。

### 5.11 T11 刚体运动去除

- 施加已知 `R(θ), t`，断言 Procrustes 解出的 `θ, t` 误差 `< 1e-6`，去除后残余位移 `< 1e-6 px`。
- 施加 `刚体 + 真实应变`，断言去除刚体后应变场不变（`< 1e-9`）——刚体去除不能污染应变。
- 断言算子可逆：`remove → restore` 后与原始场逐位相同。

### 5.12 T12 形函数代数（符号验证）

用 sympy 独立实现 `compose` 与 `invert`（完整展开后截断），与 C++ 实现逐系数比对：

- `ICGN1`：`W(p)·W(Δp)⁻¹` 与 3×3 矩阵运算严格一致（`< 1e-14`）。
- `ICGN2`：随机 `p`（`‖p‖` 小）与 `Δp`，比对 12 个系数（`< 1e-12`）。
- 恒等性质：`compose(p, invert(p)) ≈ identity`（二阶截断意义下，残差随 `‖p‖³` 缩放——断言这个缩放律成立，这比断言"接近零"更有信息量）。
- 雅可比 `∂W/∂p` 与数值差分比对（`< 1e-6`）。

### 5.13 T13 FFT-CC

- 整数平移 `(du, dv) ∈ [−30, 30]²` 全覆盖，断言峰位**精确**命中。
- 带噪声（`σ_n = 5/255`）时命中率 `> 99%`。
- 峰值抛物拟合后的亚像素初值误差 `< 0.15 px`。
- 断言 FFT 路径与暴力 ZNCC 路径给出相同的 ZNCC map（`< 1e-5`）。

### 5.14 T14 回归基准（golden）

- **DIC Challenge 1.0/2.0** 公开样本（SEM/iDICs 提供）：跑标准配置，与已发表的参考解比对，结果写入 golden 文件；CI 中任何超过容差的偏移即失败。iDICs GPG §6.2.1 Note 1 明确建议非商业代码用 DIC Challenge 验证并在文档中引用该验证——HL3 把这条做成 CI 的一部分。
- **OpenCorr / Ncorr 交叉验证**（在其许可证允许的范围内，只做**结果对比**，不复制代码）：同一组合成图，比较位移场差异的 RMS，作为"我们没有算错"的旁证。差异应在噪声底板量级。
- **性能基准**：`POI/s` 随 `subset / shape order / backend / threads` 的表格；CI 中回归超过 10% 即告警。

### 5.15 T15 GPU / CPU 一致性

- 同一输入，`backend = CPU` 与 `CUDA` 的位移差 `< 1e-4 px`，ZNCC 差 `< 1e-5`，收敛状态完全一致。
- 大规模（1e6 POI）下的内存与吞吐测试。

### 5.16 T16 确定性与并发

- `deterministic = true` 时，`threads ∈ {1, 2, 4, 8, 16, 32}` 的结果**逐位相同**（`memcmp`）。
- `deterministic = false` 时，允许差异但断言在 `1e-6 px` 内。
- TSAN 跑一遍全测试；ASAN/UBSAN 跑一遍全测试。

### 5.17 T17 IO 与 schema 往返

- 写 → 读 → 写，两次 HDF5 内容语义等价。
- 用**独立的 Python h5py 读取器**（不调用 HL3 C++）解析并复现 GUI 中显示的数值——验证 schema 真的是自描述的（§6.4 的可信度依赖这条测试）。
- 所有导出格式（CSV/VTU/MAT/…）的字段与 HDF5 逐一比对。

### 5.18 覆盖率与门槛

| 模块 | 行覆盖门槛 |
|---|---|
| `hl3_corr2d`（ICGN/形函数/准则） | ≥ 95% |
| `hl3_strain`、`hl3_interp` | ≥ 95% |
| `hl3_postproc`、`hl3_uq`、`hl3_calib2d` | ≥ 90% |
| `hl3_io`、`hl3_project` | ≥ 85% |
| 其余 | ≥ 75% |

另加：所有公开 API 的 doctest 示例必须可执行且断言通过（文档即测试）。

---

## 6. 如何超过 VIC-2D 8

以下每条都对应 `research/vic_public_feature_baseline.md` §"公开短板"中识别出的攻击点。

### 6.1 跨平台与部署自由度

VIC-2D 的分析软件是 **Windows-only**（公开事实），许可流程是 PC 专属密钥 + 销售跟进。

HL3：
- Linux / macOS（Intel + Apple Silicon）/ Windows 全平台原生。
- `pip install hl3` 即可拿到完整内核 + CLI（不含 GUI），无需图形环境 → 直接进 CI、HPC、云、容器。
- Docker / Apptainer 官方镜像；在 SLURM 集群上按帧并行是一条 `sbatch --array`。
- GUI 与内核完全解耦，服务器上跑批量、笔记本上看结果。
- 许可：**开放核心**（内核 + Python + CLI 开源；GUI/实时/采集/企业支持商业化）。研究组零摩擦上手，是最有效的生态获取手段。

### 6.2 内建不确定度量化（UQ）—— 最有说服力的差异化

商业 DIC 里 UQ 通常是"用户自己按 GPG 做"的手工流程。HL3 把它做成**默认输出**：

1. **逐点逐帧 1σ**：由 ICGN 的 Hessian 直接给出 `Cov(p) ≈ 2σ_n²·H⁻¹`（§2.6），成本几乎为零（`H⁻¹` 本来就要算）。UI 上可以直接画"位移不确定度场"和"应变不确定度场"。
2. **自动噪声底板**：静态帧对分析，输出 `σ_u, σ_v, σ_ε` 的全场分布与统计（GPG §5.4.2 全流程）。
3. **自动 VSG 研究**：扫描 VSG，输出"最大应变幅值 vs VSG"与"应变噪声 vs VSG"双曲线，自动给出收敛点建议（GPG §5.4.5 全流程）。
4. **偏差探测**：静态帧序列的均值漂移检测（相机热漂移/热浪）；刚体平移残差（畸变）；离面运动启发式（§3.1）。
5. **空间分辨率传递函数**：正弦位移场标定（§5.5 的 T5），输出该参数组合的实际空间分辨率——这是比"VSG 尺寸"更本质的指标。
6. **Monte Carlo 传播**：把标定不确定度、噪声、参数选择的不确定度蒙特卡洛传播到最终 QOI（Reu 2013 对标定不确定度做 MC 的公开方法）。
7. **结果带单位与不确定度地导出**：CSV 里每个量后面跟一列 `±`。

**这条是 HL3 最硬的护城河**：它不是"多一个功能"，而是让 HL3 的数据可以直接进入需要计量溯源的场合（认证、审查、标准试验）。

### 6.3 全局 / AL-DIC 模式并存

VIC-2D 公开叙事是局部 subset DIC。HL3 在同一 GUI/CLI/Python/HDF5 下提供 `LOCAL` / `GLOBAL_FE` / `ALDIC` 三种求解器（§2.13），并支持**逐点对比**。

价值：
- 需要协调位移场（直接给 FEA 做边界条件、做 FEMU/VFM 反演）时用全局。
- 需要处理不连续（裂纹）时局部更好，或用 AL-DIC 的掩膜感知分裂。
- **学术可比性**：同一份数据、同一套预处理、三种算法的结果并排 —— 这在闭源软件里做不到。

### 6.4 开放 HDF5 schema

- schema 有独立的**规范文档**（版本化、带 JSON Schema 校验）与**参考读取器**（Python / MATLAB / Julia），MIT 许可。
- 用户的数据永远不被锁在某个厂商的私有格式里。
- 学术出版可以把 `.h5` 作为补充材料直接发布，审稿人用 h5py 就能复现所有图。
- 第三方可以写插件读写 HL3 的结果（后处理、FEA 耦合、ML 训练集）。
- CI 中用独立读取器验证 schema 自洽（§5.17）——保证"开放"不是口号。

### 6.5 良好实践向导（Good-Practices Wizard）

把 iDICs GPG 从"一本 100 页的 PDF"变成"软件里的交互流程"（§1.3、§1.12）：图案体检 → 参数推荐 → 噪声底板 → VSG 研究 → 离面/畸变评估 → 自动生成合规报告。

这解决的是 DIC 行业最真实的痛点：**大多数误用不是软件算错了，而是用户参数选错了却不知道**。谁先把 GPG 产品化，谁就拿到教学市场与新用户的默认选择。

### 6.6 GPU 与吞吐

- 批量 ICGN CUDA 内核（§2.14），路径无关模式下可把数万 POI 一次性压进 GPU。
- 目标：单卡（消费级）在 `subset=21, ICGN1` 下达到 `10⁷ POI/s` 量级，把 VIC-3D 公开宣传的"单 32 核 CPU 100 万点/秒"作为需要跨越的参照线（注意这是 3D 的公开数字，2D 应更高；HL3 的基准要在自己的合成集上诚实公布，不做营销式对比）。
- 多 GPU / 多节点按帧切分。
- 全部性能数字都由 `§5.14` 的 CI 基准自动产出并公开发布，任何人可复现。

### 6.7 附加超越点（不在题目列举内但同等重要）

- **可复现性**：每份结果携带完整参数哈希 + git commit + 环境指纹；`hl3-dic2d reproduce results.h5` 一条命令重跑并逐位比对。
- **实验-仿真闭环**：直接导出 Exodus/VTU 给 FEA，内置 DIC↔FEA 场比对（插值到共同网格、残差场、FEMU 目标函数），对标 EikoSim 的叙事。
- **深度学习作为初值/兜底**：用 DL 光流网络（U_DICNet、Stereo-DICNet 一类公开工作）提供大变形初值，**但最终位移永远由 ICGN 精化**，保证计量级精度可追溯。DL 只在初值链中作为优先级 4.5 插入，绝不单独出结果。
- **插件生态**：Python 入口点插件（自定义导出器、自定义变量库、相机驱动、后处理算法），配一个公开的插件索引。

---

## 7. 参数默认值总表

| 参数 | 默认 | 依据 |
|---|---|---|
| `subset_size` | 21 px | iDICs GPG Recommendation 5.2 |
| `step_size` | 5 px | GPG §5.2.6（subset 的 1/4~1/3） |
| `shape` | `FIRST`（`AUTO` 可选） | 平衡精度/速度；高梯度自动升 2 阶 |
| `interp` | `BICUBIC_BSPLINE` | Pan et al. TAML 2016；OpenCorr 同选 |
| `criterion` | `ZNSSD`（报 ZNCC） | 光照鲁棒 + 最小二乘可解 |
| `path` | `HYBRID` | RG 鲁棒性 + 并行度 |
| `initial_guess` | `PREV_FRAME → FFTCC → SIFT_AFFINE` | 初值链，§2.7 |
| `conv_tol` | 1e-3 px | 常用值；亚像素精度目标 0.01 px 的 1/10 |
| `max_iter` | 20 | ICGN 典型 3–8 次收敛 |
| `zncc_min` | 0.80 | 保守；向导可按噪声底板自动调 |
| `reference` | `INCREMENTAL(0.85)` | 兼顾小变形精度与大变形鲁棒 |
| `boundary` | `STRICT` | 保守；边缘应变需求时改 `PARTIAL` |
| `strain_window` | 5 数据点 | 与 step=5, subset=21 配合 → `L_VSG = 41 px` |
| `strain_fit_order` | `LINEAR` | 高梯度改 `QUADRATIC` |
| `weighting` | `GAUSSIAN(L_window/4)` | 减少窗口边缘突变 |
| `tensor` | `GREEN_LAGRANGE` | 对刚体转动不变，通用性最好 |
| `neighbor_min` | `0.5·L_window²` | 避免边缘点用过少邻点外推 |
| `prefilter` | `NONE` | GPG §5.2.2 慎用预滤波 |
| `postfilter` | `NONE` | GPG §5.4.4 避免隐性偏差 |
| `compute_covariance` | `true` | UQ 是默认能力，不是选配（§6.2） |
| `deterministic` | `true` | 可复现优先；追求极限性能时关闭 |

---

## 8. 风险与开放问题（交给 Round 2 / Round 3）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | ICGN2 的 12 参数在小 subset 下病态 | 收敛率下降、结果抖动 | `subset ≥ 31` 硬约束 + Hessian 条件数检查 + 自动降阶到 ICGN1 |
| R2 | 二阶形函数合成/求逆的截断误差 | 缓慢发散或收敛到偏移解 | §5.12 符号验证 + 断言 `‖p‖³` 缩放律；必要时改用 Gao et al. 6×6 闭式并交叉验证 |
| R3 | B 样条系数 LUT 的内存（1 MP 图 ~64 MB） | 大图/多线程下 OOM | LUT 可关；分块预解；GPU 上走纹理内存 |
| R4 | RG-DIC 本质串行 | 大 AOI 下并行度不足 | `HYBRID` 分块（§2.8）；块间一致性检查是新引入的复杂度，需要专门测试 |
| R5 | 增量参考更新的误差累积 | 长序列大变形下漂移 | 记录更新次数与误差上界；提供"回溯到初始参考"的二次精化选项 |
| R6 | 离面运动无法在 2D 中根治 | 用户误信 2D 结果 | 向导强制评估 + 报告强制章节 + 超阈值时明确建议改用 HL3-3D |
| R7 | DIC Challenge 数据集的许可与分发 | CI 无法直接内置 | 交给 R1-G1/R1-G3 核实；必要时 CI 从官方源下载而非仓库内置 |
| R8 | 开源许可兼容性（FFTW GPL / OpenCV / Eigen / nanoflann） | 开放核心策略受限 | 交给 R1-G1；FFTW 的 GPL 需评估，备选 pocketfft(BSD)/PFFFT(BSD)/MKL |
| R9 | GPU `float` 累加吃掉亚像素精度 | GPU 结果比 CPU 差 | 内部累加用 `double` 或 Kahan；§5.15 强制一致性门槛 |
| R10 | 与 R1-O2/R1-O3 的接口边界未定 | 重复实现或接口摩擦 | §4.1 已标注共享/专属边界；由父调度器在 Round 1 收敛时定稿 |

---

## 9. 引用（全部为公开文献 / 开源项目；无任何 VIC 逆向内容）

**标准与良好实践**

1. iDICs, *A Good Practices Guide for Digital Image Correlation* (Edition 1, 2018). https://idics.org/guide/ — 本文引用其 Caution 2.1、Recommendation 2.3/2.6、Caution 2.5、Recommendation 5.2、§5.2.6、§5.3.1–5.3.2、§5.4.2–5.4.5、§6.1–6.2、式 (7.2)。
2. iDICs, *DIC 101 Course, Chapter 2: Design of DIC Measurements*. https://idics.org/courses/dic101/
3. Reu, P.L. et al. (2018) *DIC Challenge: Developing Images and Guidelines for Evaluating Accuracy and Resolution of 2D Analyses.* Exp Mech 58:1067–1099. doi:10.1007/s11340-017-0349-0
4. Arrington, C. et al. (2025) *Review of High-Speed Digital Image Correlation: Advancements and Good Practices.* Strain. doi:10.1111/str.70018

**相关算法（ICGN / 准则 / 路径 / 插值 / 应变）**

5. Bruck, H.A., McNeill, S.R., Sutton, M.A., Peters, W.H. (1989) *Digital image correlation using Newton-Raphson method of partial differential correction.* Exp Mech 29(3):261–267.
6. Baker, S., Matthews, I. (2004) *Lucas-Kanade 20 Years On: A Unifying Framework.* IJCV 56(3):221–255.（逆合成框架的来源）
7. **Pan, B., Li, K., Tong, W. (2013)** *Fast, Robust and Accurate Digital Image Correlation Calculation Without Redundant Computations.* Exp Mech 53:1277–1289. — IC-GN + ZNSSD + 可靠性引导 + 插值系数 LUT，本文 §2.6/§2.10 的主要依据。
8. **Pan, B. (2009)** *Reliability-guided digital image correlation for image deformation measurement.* Appl Opt 48(8):1535–1542. — RG-DIC，本文 §2.8(a)。
9. Pan, B., Wu, D., Xia, Y. (2012) *Incremental calculation for large deformation measurement using reliability-guided digital image correlation.* Opt Lasers Eng 50:586–592. — 本文 §2.9。
10. Pan, B., Wang, Z., Lu, Z. (2010) *Genuine full-field deformation measurement of an object with complex shape using reliability-guided digital image correlation.* Opt Express 18:1011–1023.
11. **Pan, B., Asundi, A., Xie, H., Gao, J. (2009)** *Digital image correlation using iterative least squares and pointwise least squares for displacement field and strain field measurements.* Opt Lasers Eng 47:865–874.
12. **Pan, B., Xie, H., Guo, Z., Hua, T. (2007)** *Full-field strain measurement using a two-dimensional Savitzky-Golay digital differentiator in digital image correlation.* Opt Eng 46:033601. — PLS 应变，本文 §2.11（OpenCorr `Strain` 模块亦引此文）。
13. Pan, B., Lu, Z., Xie, H. (2010) *Mean intensity gradient: an effective global parameter for quality assessment of the speckle patterns used in digital image correlation.* Opt Lasers Eng 48(4):469–477. — MIG，本文 §1.1/§1.3。
14. Pan, B. et al. (2016) *Bicubic B-spline interpolation ...* Theor Appl Mech Lett 6(3):126–130. — B 样条插值优于双三次卷积，本文 §2.10（OpenCorr 文档引此文作为其插值选型依据）。
15. Keys, R.G. (1981) *Cubic convolution interpolation for digital image processing.* IEEE TASSP 29(6):1153–1160.
16. **Gao, Y., Cheng, T., Su, Y., Xu, X., Zhang, Y., Zhang, Q. (2015)** *High-efficiency and high-accuracy digital image correlation for three-dimensional measurement.* Opt Lasers Eng 65:73–80. — ICGN 二阶形函数（ICGN2D2）的公开出处。
17. **Jiang, Z. et al. (2015)** Opt Lasers Eng 65:93–102；**Wang, T. et al. (2016)** Exp Mech 56(2):297–309. — FFT-CC 与 ICGN2D1 的原理与实现（OpenCorr 引用）。
18. Chen, B., Jungstedt, E. (2022) *Inverse compositional Levenberg-Marquardt ...* Opt Lasers Eng 151:106930.
19. Chen, Z. et al. (2017) *A comparison between NR and ICGN ...* Exp Mech 57(6):979–996.
20. Lu, H., Cary, P.D. (2000) *Deformation Measurements by Digital Image Correlation: Implementation of a Second-order Displacement Gradient.* Exp Mech 40:393–400.
21. *Impact of Speckle Deformability on Digital Imaging Correlation.* IEEE Access (2024). doi:10.1109/ACCESS.2024.3398786 — ICGN-1 vs ICGN-2 的适用边界与 SRI 误差的公开对比结论，本文 §2.5 选型依据。

**全局 DIC / AL-DIC**

22. **Yang, J., Bhattacharya, K. (2019)** *Augmented Lagrangian Digital Image Correlation.* Exp Mech 59(2):187–205. doi:10.1007/s11340-018-00457-0 — 本文 §2.13(b)。
23. Yang, J. (2019) *Fast Adaptive Augmented Lagrangian Digital Image Correlation.* PhD Thesis, Caltech. https://thesis.caltech.edu/11233/
24. *pyALDIC: A Python Implementation of Augmented Lagrangian Digital Image Correlation with a GUI, Adaptive Meshing, and Mask-Aware Subset Splitting.* arXiv:2607.22755 — 掩膜感知 subset 分裂（本文 §1.2 `SPLIT` 模式）与 ADMM 算法流程。
25. Besnard, G., Hild, F., Roux, S. (2006) *"Finite-element" displacement fields analysis from digital images.* Exp Mech 46:789–803.（全局 FE-DIC）

**2D 特有误差：离面 / 畸变 / SEM / 显微**

26. **Sutton, M.A., Yan, J.H., Tiwari, V., Schreier, H.W., Orteu, J.J. (2008)** *The effect of out-of-plane motion on 2D and 3D digital image correlation measurements.* Opt Lasers Eng 46(10):746–757. — 本文 §3.1 的量化基础。
27. Pan, B., Yu, L., Wu, D. (2014) *High-Accuracy 2D Digital Image Correlation Measurements using Low-Cost Imaging Lenses: Implementation of a Generalized Compensation Method.* Meas Sci Technol 25(2):025001. — 补偿板法（iDICs GPG 参考文献 [13]）。
28. Lava, P. et al. — 图像矫正法（image rectification）；Wittevrongel 等、Hijazi 等的后续改进。综述见 *A Strain-Gauge-Based Method for the Compensation of Out-of-Plane Motions in 2D Digital Image Correlation*, Math Comput Appl 28(2):40 (2023). doi:10.3390/mca28020040
29. **Sutton, M.A. et al. (2007)** *Scanning Electron Microscopy for Quantitative Small and Large Deformation Measurements Part I: SEM Imaging at Magnifications from 200 to 10,000.* Exp Mech 47:775–787；**Part II: Experimental Validation for Magnifications from 200 to 10,000.* Exp Mech 47:789–804. — 本文 §3.3 的 SEM 空间畸变与漂移校正。
30. Zhang, Z. (2000) *A Flexible New Technique for Camera Calibration.* IEEE TPAMI 22(11):1330–1334.
31. Reu, P.L. (2013) *A Study of the Influence of Calibration Uncertainty on the Global Uncertainty for Digital Image Correlation Using a Monte Carlo Approach.* Exp Mech 53:1661–1680. — 本文 §6.2(6)。
32. Blaysat, B., Grédiac, M., Sur, F. (2016) *On the Propagation of Camera Sensor Noise to Displacement Maps obtained by DIC.* Exp Mech 56(6):919–944. — 本文 §2.6 噪声传播与 §5.6。
33. Bossuyt, S. (2013) *Optimized Patterns for Digital Image Correlation.* SEM Conf Proc Vol 3:239–248.

**开源实现（作为算法类别的公开参考，不复制其代码；许可证核查交 R1-G1）**

34. **OpenCorr** — vincentjzy/OpenCorr（MPL-2.0）。https://opencorr.org/ 的 "Processing methods" 页详细公开了其模块划分（`Gradient` 用 4 阶中心差分、`BicubicBspline`、`FFTCC`、`FeatureAffine`、`ICGN2D1/ICGN2D2`、`NR`、`ICLM`、`Strain`、`NearestNeighbor`/nanoflann、`Calibration`、`Stereovision`、`IO`）。本文 §4.2 的模块划分参考了这一公开设计的合理性，但接口与实现是独立设计。
35. **Ncorr** — justinblaber/ncorr_2D_matlab；Blaber, J., Adair, B., Antoniou, A. (2015) *Ncorr: Open-Source 2D Digital Image Correlation Matlab Software.* Exp Mech 55:1105–1122. doi:10.1007/s11340-015-0009-1；算法说明见 https://www.ncorr.com/index.php/dic-algorithms
36. **muDIC** — PolymerGuy/muDIC（有限元全局 DIC，Python）。
37. **AL-DIC / pyALDIC / STAQ-DIC** — jyang526843/2D_ALDIC（MATLAB）、zachtong/pyALDIC。
38. **DICe** — dicengine/dice（Sandia；局部 + 正则全局；MPI + 线程）。
39. **2D_FE_Global_DIC** — YangMechanicsGroupUTAustin。
40. nanoflann（FLANN 近邻）、Eigen、FFTW / pocketfft、OpenCV（SIFT）、HDF5、pybind11。

**竞品公开信息（仅公开营销/规格页，无逆向）**

41. Correlated Solutions 官方产品页与 downloads 页（VIC-2D 8 / VIC-3D 11.4 的公开功能与评估流程）。见 `research/vic_public_feature_baseline.md` 与 `LEGAL.md`。

---

## 10. 交付物清单（供 Round 2 直接认领）

| # | 交付物 | 依赖 | 验收 |
|---|---|---|---|
| D1 | `hl3_core` 类型 + `hl3_imgio` | — | T17 部分 |
| D2 | `hl3_interp` 四种插值 + LUT | D1 | T1, T2 |
| D3 | `hl3_corr2d::shape_function`（SF1/SF2 合成/求逆/雅可比） | D1 | **T12（先行，代数必须先对）** |
| D4 | `criterion` + `gradient` + `fftcc` | D1, D2 | T13 |
| D5 | `icgn`（1 阶 + 2 阶 + 协方差） | D2, D3, D4 | T1–T8 |
| D6 | `seed` + `path`（RG / PI / Hybrid） | D5 | T8, T16 |
| D7 | `incremental` 参考更新 | D5 | T4 大应变部分 |
| D8 | `hl3_strain`（PLS + 张量族 + VSG） | D6 | **T9（纯代数，可与 D5 并行）**, T10 |
| D9 | `hl3_postproc`（刚体去除 + 表达式引擎 + 提取器） | D8 | T11 |
| D10 | `hl3_uq`（噪声底板 + VSG 研究 + MC） | D8 | T6 协方差部分 |
| D11 | `hl3_calib2d`（尺度 + Zhang + 畸变 + SEM/显微） | D1 | 独立测试集 |
| D12 | `hl3_io` HDF5 schema + 参考读取器 | D8 | T17 |
| D13 | `hl3_py` 绑定 | D5–D12 | doctest |
| D14 | `hl3_cli` | D13 | CLI 契约测试 |
| D15 | `hl3_report`（iDICs 模板） | D10, D12 | 报告字段完整性测试 |
| D16 | `hl3_gpu` CUDA ICGN | D5 | T15 |
| D17 | `hl3_global2d`（FE + AL-DIC） | D5, D8 | 与 LOCAL 交叉验证 |
| D18 | `hl3_rt2d` | D5 | 延迟预算测试 |
| D19 | `hl3_gui`（AOI 编辑器 + 向导 + 绘图） | D13 | 手工走查 |
| D20 | CI：DIC Challenge 回归 + 性能基准 | D5, D8 | T14 |

**建议的关键路径**：D1 → D2 → **D3（先做 T12）** → D4 → D5 → D8（T9 可并行提前做）→ D6 → D12 → D13 → D14。GUI（D19）最后做，因为内核 + Python + CLI 已经能构成一个可用且可发布的产品。
