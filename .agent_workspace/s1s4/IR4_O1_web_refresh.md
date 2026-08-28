ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# IR4-O1 · VIC-2D 8 / VIC-3D 11 公开功能刷新（2024–2026）与差距重排

- **子代理**：IR4-O1（opus-fast，云端）｜独占路径：本文件
- **调研日期**：2026-08-28（所有 URL 于当日访问）
- **方法**：仅 WebSearch / WebFetch 公开网页与公开文献。**未下载、未安装、未运行任何 VIC 软件**；未访问 `github.com/Correlated-Solutions`。厂商 GitHub 社区组织的存在与内容一律**只引厂商官网公告与 LinkedIn 公告**，不作为一手来源。
- **效力**：低于 `LEGAL.md` → RUL/ADR-LIC-001 → `R2-F1` 冻结门槛。本文**不新设也不放宽任何门槛**，只更新竞品公开事实、指出 round 1 的错漏、并给出优先级建议。
- **表述纪律**：下文所有 VIC / MatchID / EikoSim / ZEISS 能力均为**厂商公开宣传值，未独立验证**（RUL-03）；不出现"比 VIC 快/准"；`iris` 一词只出现在引用与"不追 iris 级"的否定句式中（RUL-06）。

---

## 0. 一句话结论

Round 1 的竞品基线（`research/vic_public_feature_baseline.md`）在**版本时间线**和**开放性判断**两处已经过时：VIC 在 2026-03 至 2026-07 之间连发 11.2 / 11.4 与 VIC-2D 8，把 Python 扩展从"应用内脚本菜单"扩成了 **PyPI 模块 + 开放社区扩展索引 + 免许可只读查看器**的生态，我们 round 1 列为"可攻击点"的三条里有两条（许可摩擦、无开源插件生态）**已被显著削弱**；同时 VIC 公开文档一直在宣传**逐点不确定度 sigma / Sigma_X,Y,Z**，round 1 完全漏掉，导致"UQ 是我们的差异化"这一说法**必须收窄**才成立。仍然坚硬的差异是三条：**分析端 Windows-only、相关器与容器格式不可独立复核、逐位确定性与端到端 UQ 传播未被宣传**。

---

## 1. Round 1 漏掉的公开事实（按重要性排序）

### 1.1 版本时间线：round 1 只有 v11 GA 的功能表，漏掉 11.2 / 11.4 全部内容

| 日期 | 事件 | 我们 round 1 的状态 |
|------|------|---------------------|
| 2025-11-03 | VIC-3D 11 发布（iDICs 2025 首发 VIC-Py→vicpyx） | 有，但功能表不全 |
| 2025-11-24 | iDICs GPG **第 2 版**发布（新增全局 DIC 章节） | 只写了"Edition 2 含全局 DIC"，未挂 DOI |
| 2026-01-27 | 官网专文 *Python + DIC: Introducing vicpyx* | **漏** |
| 2026-03-31 | **VIC-3D 11.2**：vicpyx 高阶 API、FLC/FEA 系列扩展 | **漏** |
| 2026-04-21 | **VIC-2D 8** 正式公告（功能表 17 条） | 有，压缩成一行，漏掉 CLI 批处理等关键项 |
| 2026-06-23 | FLC ISO 12004 / Annex F 扩展专文 | **漏** |
| 2026-06-24 | **VIC Extensions & vicpyx Community**（开放社区枢纽）上线 | **漏（最关键）** |
| 2026-07-10 | **VIC-3D 11.4**（免许可查看器 / 标定离群剔除 / 热应变 / 变换管理器…）；同日 `vicpyx 0.9.1` 上 PyPI | **漏** |
| 进行中 | 新一轮 **Stereo DIC Challenge** 已启动；iDICs 2026 会议 11 月于胡志明市 | **漏** |

### 1.2 最关键的一条：vicpyx 已经是"可 pip 安装的官方 Python 模块 + 开放扩展生态"

Round 1 把 vicpyx 记成"项目内脚本、派生量、导出"，把"开源插件市场"列为 VIC 的非主叙事。公开事实比这强得多：

- **PyPI 上有官方包**：`pip install vicpyx`（截至 2026-07-10 为 `0.9.1`，Python ≥3.10，依赖 `numpy>=2.0` / `h5py` / `lxml` / `pillow`，License 字段 `LicenseRef-Proprietary`）。另有 `pip install vicpy-extension-requirements` 一键装齐官方扩展依赖。厂商知识库明说：该模块**可在 Python 中加载与保存 VIC-3D 数据文件**，且能以 VIC 原生输出格式写回，供 VIC 内可视化。
- **官方社区枢纽**（2026-06-24 公告）：策展式扩展索引（按产品与版本浏览，各自可下载）、**扩展起步模板 + 编写指南**（含打包与 vicpyx 框架的实践细节）、Show & Tell / Q&A 讨论板（"不需要懂 Git，浏览器里贴脚本即可"）。提交走讨论帖 / 表单 / PR，少量维护者审核后入索引。公告原文强调"**everything is openly licensed and community-contributed**"，同时声明这些是社区工具、非官方支持产品。
- 公开检索摘要显示扩展的打包形态为 `config.json`（声明扩展类型、参数控件、输入、预览变量）+ 一个处理器子类 + `help.html` + 多语言 `locale/`（含 ja / ru / **zh**）+ `requirements.txt`，安装目录下以 `.zve` 包形式分发；官方随装扩展中至少有一个以 ISC 许可公开作为参考样例。*（来源：厂商社区仓库 README 的公开检索摘要，未访问该仓库，按二手证据对待。）*

**对我们的影响**：`research/vic_public_feature_baseline.md` §"公开短板"第 6 条（"深度学习匹配、自适应网格、**开源插件市场**不是其主叙事"）中的插件市场一项**已不成立**；"Python 接口后加、二等公民"的叙事也需要改写——VIC 的 Python 层现在是 pip 可装、有官方 API 文档、有社区索引的。**仍成立的是**：相关器内核与工程文件格式本身不公开，vicpyx 是**专有许可**的官方通道，不是"任何人都能写兼容读写器"的公开规范。

### 1.3 VIC-3D 11.4（2026-07-10）完整公开功能表

分四组抄录（厂商公开宣传值，未独立验证）：

**许可与协作**
- **License-Free Viewer Mode**：以只读查看器打开并检视工程，无需许可证；宣传语是"交付给评审/经理/客户，他们能看遍所有结果但改不动分析"。

**标定与坐标系**（对我们 A6 最相关）
- 标定重大升级：**可配置的离群剔除阈值**，支持**自动与手动剔除单个靶点**（而不是整张图像作废）；宣传点是"一个手指/污渍/高光不该毁掉整次标定"，且"阈值可配置使标定标准在不同操作者与任务间保持一致"。
- **Project Transformations Manager**：集中列出工程上施加过的所有坐标系变换，可复核、可移除、**已施加的变换可撤销**。
- **柱坐标变换**：实时预览、变量复用选项、可将结果设为坐标系。
- 自动靶点检测改进。
- **触针（touch probe）增强**：由触针测量直接计算并施加坐标系（新的对齐与拟合算法）、工作区内三角化、探针位置增删切换、滚轮 3D 缩放。

**分析与后处理**
- **热应变**：输出热应变，并扣除热膨胀以得到纯机械应变（以完全集成的扩展形式提供）。
- **分析对话框预览页签**：运行中新增 Extraction 页（跟踪所选变量在序列上的均值）与 Summary 页（**逐图像结果表，随工程保存**）；总进度与单图进度双进度条 + 剩余时间估计。
- 提取曲线可用**时间轴**作为 x 轴。
- 三角化、应变、曲率、局部旋转、平滑、施加变换六个对话框**统一实时预览**；图像与数据加载加速。
- **2D 等值云图上直接显示坐标原点与虚拟应变片（VSG）**，配置 VSG 时有实时预览。
- **引伸计高级布置**：一次布置整列引伸计；按精确全局/像素坐标、长度、方向数值编辑；可数值化定义以在不同试样与试验间**复现同一套量规布局**。

**扩展系统运行时**
- 三个新扩展：Image Histogram（曝光/对比即时诊断）、Subtract Thermal Expansion、Align Rotary Motion。
- 自动运行 / 自动接受、收藏与最近使用、**具名参数预设**（右键菜单施加与编辑）。
- 扩展内置获得 **AOI 掩膜、参考数据、子区尺寸、分析起点、工程标定**的控制权。
- （中文经销商页转述的 11.4 扩展能力，与官网一致或更细）：扩展可将 AOI、检查器与变换**写回工程**；可访问**相邻帧**做时序分析、速度计算与降噪；扩展参数可持久化为默认值；标准工具集原生含 **ISO 12004 (FLC)**、极坐标/柱坐标、**噪声基底分析**，并可完全访问全部 3D 变量。

### 1.4 VIC-2D 8（2026-04-21）中 round 1 压缩掉的关键项

除 round 1 已记的 Python 扩展 / 实时 2D / HDF5 / VSG / 暗色主题外，公开功能表还含：

- **命令行批处理分析**（VIC-2D 侧首次支持）。
- **文档模板报告生成**，含 2D 专用标签（比例因子、单位、纵横比）。
- **FRF（频响函数）测量**：把力输入并进 FFT 模块；全新 FFT 工作区。
- **图像文件与输出数据都可存进 HDF5**（不只是结果）。
- 单工程内多个 `iris` 文档；视频文件可当图像序列用。
- **分析摘要 CSV 存进工程文件内**；一次性把某文件夹全部数据文件加入工程；从模板新建工程。
- 全变量**单位管理**、数据探针、数据提取改进；线图独立次坐标轴；用户级全局偏好。
- VSG 工具明确挂靠 **DIC Good Practices**（"streamline application of DIC Good Practices"）。

### 1.5 VIC 公开文档里一直存在、而 round 1 完全没记的两块

**(a) 逐点不确定度是公开变量**（这条推翻了我们的一个隐含假设）

| 变量 | 公开定义 |
|------|----------|
| `Sigma [pixel]` | 匹配的 1 标准差置信度；0 为完美匹配，越大表示噪声、过大梯度或匹配失败 |
| `Sigma_X / Sigma_Y / Sigma_Z [mm]` | 各轴 **1 标准差（67%）不确定度**，由"计算置信区间"选项在分析对话框后处理页开启 |

厂商知识库同时公开了**诚实边界**：sigma "是准确的噪声估计，但**不反映偏差**（例如标定不好不会体现在这里）"，并建议用静态图/刚体平移 + 去刚体运动来测更保守的位移噪声。标定培训材料亦公开"可给出所有估计参数的置信区间"（Zhang 式标定的常规说法）。

**(b) 相关器与后处理的可调项是公开的**（这对"独立实现"的边界很重要：这些是公开信息，不是逆向所得）

- 准则：Squared differences / **Normalized SSD（默认）** / Zero-normalized SSD；
- 插值：4 / 6 / 8 抽头样条（高阶更准、低阶更快）；
- 子区权重：Uniform / **Gaussian 中心加权**（宣传为空间分辨率与位移分辨率的最佳折中）；
- 图像**低通滤波**（抑制过细散斑的混叠/摩尔纹）；
- **增量相关**（对前一帧而非参考帧，用于图案退化或 >100% 应变，代价是噪声逐帧累积）；
- 阈值族：**一致性/预测裕度**（反向预测与邻点不符则丢弃，"限制误匹配最有用的阈值"）、**投影误差**、**置信区间阈值**（丢弃裂纹周边等高不确定点）、**立体裕度**、**可匹配性**（低对比子区）；
- **时间轴滤波链**：中值去离群 + 平滑，可串联；
- 应变：Lagrange 张量、滤波窗口以**数据点**计（非像素）、box 与**中心加权高斯衰减**滤波、Tresca / von Mises 等效应变。

### 1.6 生态与标准（影响 A5 / B5 / B6 的可执行性）

- **iDICs GPG 第 2 版**（2025-11）已含全局 DIC，DOI `10.58720/idics/gpg.ed2`，免费下载。→ B5 的报告 lint 有了明确对标文本。
- **Stereo-DIC Challenge 1.0** 论文已在 *Experimental Mechanics*（`10.1007/s11340-024-01077-7`）：13 家受邀，最终 **5 家提交**——Dantec、LaVision、**DICe**、**MatchID**、**Correlated Solutions**（匿名为 Group 1–5）；**五家全是 subset-based**，受邀的两家全局 DIC 代码**未提交**。标定与平移图像集在 `idics.org/challenge` **免费可取**，随附 MATLAB 分析脚本。→ **A5 从"预算问题"变成"下载 + 派工问题"**，且"全局 DIC 无人交卷"是一个可诚实引用的生态事实。
- 新一轮 **Stereo DIC Challenge 进行中**；Challenge 董事会另设 DVC、SEM、不连续性（裂纹）、超大应变分项负责人。
- **iDICs 2026**：11 月 2–5 日，胡志明市。
- 一项 2025 年的跨平台对照研究（*Results in Engineering*, `10.1016/j.rineng.2025.108174`）报告 **Vic-3D 与 Ncorr 的互软件偏差 <1%**，并做了虚拟引伸计位置敏感性分析。→ 这类文献是我们"公开可引用的第三方对照"的现成锚点，也说明**"算得准"本身已不构成差异化**。

### 1.7 竞品侧（用于校准"超越"的坐标系）

| 厂商 | 2025–2026 公开要点 | 与 HL3 的关系 |
|------|--------------------|---------------|
| **MatchID** | UQ 与性能分析（子区尺寸/形函数/应变滤波的最优选择、收敛研究）内置于基础包；FEA 合成图像生成"已知真值"；**FE 模型校验采用 levelling 方法——把 FEA 数据过与实测同样的滤波链（子区、形函数、插值）**；VFM 材料识别；批处理。**Windows 10+、.NET、dongle 需年度续期** | **B6 的"同滤波链对比"与 MatchID 的 levelling 是同一思想**，我们不是首创，表述上必须承认 |
| **EikoSim EikoTwin 2026.1**（2026-02-27） | 全新 **Python API**（自定义传感器/场、脚本直连数据库）、**批处理命令行**、LS-Dyna / MSC Nastran 等 CAE 格式、可选实验模态分析插件；原生 FE 网格全局 DIC，"数据直接表达在仿真网格节点上，无投影步骤" | 我们的 `hl3.fea` 走的是**投影**路线，属于局部 DIC 的常规做法；不得暗示投影等价于全局 FE-DIC（`fea/__init__` docstring 已写明，保持） |
| **ZEISS CORRELATE** | 6DoF、轨迹、虚拟引伸计、CAD/FEM 导入与对齐、Python 接口（录制操作再复用）、**免费许可层 + pro 层 + 100+ apps + 30 天全功能试用** | "免费层"这件事说明**零许可摩擦不是 HL3 独有**，只是程度不同 |
| **OpenCorr** | 2024-02 GPU ICGN 重构（含 DVC）；2024-06/07 GUI 1.0→2.0（2D/立体/DVC）；2024-12 新增 **ICLM**（逆合成 Levenberg–Marquardt）；2025-02 健壮性更新；2025-05 macOS/OpenMP 兼容；**2026-05-19 GUI 3.0**（多形式结果可视化） | 开源侧的 GPU 与 DVC 已经走在前面；MPL-2.0，`LEGAL.md` 禁止 vendor 其源码 |
| **DICe** | Windows/macOS 安装包，**Linux 从源码构建**；MPI + 线程并行；GUI 覆盖基础 2D/立体，正则化全局方法等高级项走 CLI | 跨平台 + HPC 的既有开源标杆 |

---

## 2. VIC 有、HL3 S4 仍然没有的能力（P0 / P1 / P2）

**HL3 S4 实测基线**（本 checkout 工作树，`b141aad` + 本轮在飞文件）：`correlate/icgn`（一阶、ZNSSD/ZNCC、B 样条、FFT-CC 初值、参数协方差）、`strain`（engineering / green_lagrange / euler_almansi / hencky、principal、von Mises、Tresca、PLS 窗口、VSG 记账）、`stereo`（线性 DLT 原型 + 匹配 + 三角化，**无畸变**）、`pipeline`（dic2d / dic3d、**含增量参考更新**、provenance 与哈希）、`uq/propagate`、`io/hdf5_schema`（`1.0.0-draft.2`）、`cli`（`validate` + 在飞 `run`）、`viz`（PNG/PDF/SVG，matplotlib 可缺席时走内置 PNG/Netpbm）、`fea`（`TriMesh` 双向投影，**纯数组、无文件 IO**）、`gui`（`PolygonAOI` + 查看器骨架，本环境无 GUI 工具链）。

**优先级判据**：**P0** = 缺了它 HL3 连"可信测量链"都不成立，或直接卡住已冻结锚点（B3 / B6 / A5 / A6）；**P1** = 用户第一周就会撞上、且**不需要新硬件依赖**即可实现；**P2** = 长尾、需硬件/新依赖、或明确属于 S5–S8 与 GAP 红线。

### P0（卡门；建议进 S5 首批）

| # | 缺口 | VIC 公开侧 | HL3 现状 | 卡住什么 |
|---|------|-----------|----------|----------|
| P0-1 | **镜头畸变模型 + Zhang 平面标定 + 标定不确定度** | 标定报告、逐参数置信区间、11.4 起**可配置离群阈值 + 单靶点剔除** | 只有已知三维靶点的线性 DLT；畸变为零 | **A6**；没有它任何真实相机数据不可用，A5 无法参赛 |
| P0-2 | **真实图像入口**（16-bit TIFF / PNG / 相机文件夹序列） | 图像与结果均可入 HDF5；视频可作图像序列 | 仅 `.npy/.npz` + Netpbm，PNG/TIFF 依赖可选 Pillow | CLI 全链在真实数据上跑不起来；**B3 的秒表只能用合成散斑** |
| P0-3 | **可安装的分发物**（PyPI + Windows/macOS） | `.msi` 安装包；**`pip install vicpyx` 已在 PyPI** | 无发布，只能源码树 `PYTHONPATH=src` | **B3 正式门**（`pip install hl3` → 首图 <15 min）结构性 evaluable=false |
| P0-4 | **FE 网格文件 IO + 真实 FE 输出对照** | OBJ / STL / PLY 等网格导入 + 对齐工作区（11 起）；材料模型估计用 L-M | `fea` 只吃两个 numpy 数组；FE 侧只有解析/合成场 | **B6 正式门**；`fe_source: synthetic` 摘不掉 |
| P0-5 | **有效性阈值族**（一致性/预测裕度、投影误差、置信区间阈值、立体裕度、可匹配性） | 五类阈值全部公开、可调，语义为"留洞" | 有 `Status` 位域，但阈值族不完整 | 输出场的"洞"语义与任何商业/开源实现不可比 → B6 残差与 A5 成绩都失去意义 |

### P1（第一周即撞上；无需新硬件）

| # | 缺口 | 说明 |
|---|------|------|
| P1-1 | **CSV / ASCII 导出**（含单位与坐标系声明） | 全仓库目前**零 CSV**。VIC 公开导出为 CSV/STL/ASCII/MATLAB，且 VIC-2D 8 把分析摘要 CSV 存进工程。`G-S4-FEA-5` 只做了边界条件导出，需泛化为通用场导出 |
| P1-2 | **虚拟引伸计 / 虚拟应变片对象** | VIC-3D 11.4 支持阵列布置 + 按数值坐标/长度/方向编辑 + **跨试样可复现布局**；HL3 只有 VSG 尺寸记账，没有"引伸计"这个可序列化对象 |
| P1-3 | **去刚体运动** | VIC 的公开噪声评估流程直接依赖它；HL3 已有 Umeyama 配准，缺的只是面向场数据的 API |
| P1-4 | **相关准则与插值阶数可选** | 公开侧为 SSD / NSSD（默认）/ ZNSSD + 4/6/8 抽头样条；HL3 有 ZNSSD/ZNCC + B 样条，缺 NSSD 与阶数旋钮（并应在 provenance 里记录选择） |
| P1-5 | **子区权重 Uniform / Gaussian** | 公开宣传为空间分辨率与位移分辨率的最佳折中；HL3 只有均匀权重 |
| P1-6 | **图像低通预滤波** | 抗混叠（摩尔纹）；纯 numpy 即可 |
| P1-7 | **时间轴滤波链**（中值去离群 → 平滑） | 公开的可串联滤波器对话框；HL3 无任何时间维处理 |
| P1-8 | **应变滤波口径对齐** | 公开侧：窗口以**数据点**计、box vs **中心加权高斯**；HL3 的 PLS 需明确对齐这两点并继续随图输出等效 VSG |
| P1-9 | **逐帧结果表 + 进度/剩余时间** | 11.4 的 Summary 页逐图像结果表随工程保存；HL3 CLI 只有整体 summary JSON |
| P1-10 | **模板化报告生成** | VIC-2D 8 / VIC-3D 均有；这是 **B5（GPG 报告 lint）**的载体，本轮 not-evaluated |
| P1-11 | **工程/会话概念** | AOI、变换、检查器、摘要随工程文件保存；HL3 目前是"命令 + 文件"，没有可复用的工程对象 |
| P1-12 | **二阶形函数** | ⚠️ VIC 公开页**未明示**，此项对标的是 MatchID（higher-order shape functions）与 OpenCorr（2nd order ICGN/ICLM），按 SOTA 追平项而非 VIC 追平项登记 |
| P1-13 | **并行化（在保持逐位确定性的前提下）** | VIC 宣传单 32 核 CPU 可达 1,000,000 点/秒（厂商公开宣传值，未独立验证）；HL3 是确定性单线程。**不得以此写任何速度对比**（RUL-03），只作能力缺口登记 |

### P2（长尾 / 需硬件 / S5–S8 / 红线内）

| 缺口 | 备注 |
|------|------|
| 坐标系变换族：极 / 柱坐标、变换管理器与撤销 | 11.4 新增；HL3 无 |
| 热应变输出与热膨胀扣除 | 11.4 新增扩展 |
| FFT / FRF / 模态、疲劳与振动相位触发 | VIC-2D 8 与 VIC-3D 模块；EikoTwin 2026.1 也加了模态插件 |
| 实时 / 在线测量、DAQ ±10 V 输出、采集同步 | **GAP-5 硬件红线**（零相机 SDK），本项目明令不做 |
| DVC（VIC-Volume） | S7/S8；OpenCorr 已有 GPU DVC |
| 多相机拼接（最多 16 相机、无重叠亦可合并坐标系） | S6+ |
| 标记点跟踪（DMT）/ 触针工作流 | S6+ |
| 显微 / SEM 模块 | **GAP-5 明令排除** |
| 出版级可视化（4K 视频、动画、运动模糊、等值线、散斑贴图、模板） | **RUL-06：明令不追，不得出现"iris 级"表述** |
| 扩展打包与索引生态（`config.json` 式插件包 + 策展索引） | HL3 本身就是 Python 库，优先级低；但"社区索引"这件事值得在 S6+ 考虑 |
| FLC ISO 12004 / 材料模型估计（L-M）/ VFM | 应用层；MatchID 的 VFM 是另一条赛道 |
| 暗色主题、模板、全局偏好等 UX 长尾 | 与 GUI 一起移交 GAP-1 |

---

## 3. HL3 有、而 VIC 公开页面**不宣传**的能力

⚠️ 使用纪律：下表左列是**我们仓库内可复跑的事实**，右列是**"VIC 公开材料中未见"**——这不等于 VIC 做不到，只等于**没有公开承诺**。任何对外表述必须用"未在公开材料中宣传"而不是"没有"。

| # | HL3 侧（仓库内可复跑） | VIC 公开材料中未见 | 强度 |
|---|------------------------|---------------------|------|
| 1 | **内核 Apache-2.0 + 文件格式规范 CC-BY-4.0 分开授权 + 纯 h5py 参考读取器 + 结构验证器**（`hl3.cli.validate`，退出码语义 + 变异测试 + 子进程读回）——目标是**第三方可独立实现兼容读写器** | 官方 Python 通道 `vicpyx` 是 **`LicenseRef-Proprietary`**；社区扩展开放许可，但**扩展的开放 ≠ 格式与内核的开放**；未见公开的容器格式规范或一致性套件 | **强**（但必须精确到"内核许可 + 格式规范"，不能笼统说"我们更开放"——他们已有 PyPI 模块与开放社区索引） |
| 2 | **端到端不确定度传播**：图像噪声 σ → 位移协方差 → 应变 CI，蒙特卡洛交叉验证 + **覆盖率实证**；协方差与位移场同生命周期存储（`u_std / v_std / w_std / cov_uvw`）；一阶协方差 / MC 实测标准差比值 0.994–0.998 | 公开的是**逐点匹配与三角化 sigma**（`Sigma`、`Sigma_X/Y/Z`，1σ 67%），并**明确声明不含 bias**；未见公开的"噪声→应变 CI"传播链、覆盖率验证或 MC 交叉验证 | **中强**（收窄后成立：差异在**传播链与覆盖率证据**，不在"有没有不确定度变量"。Round 1 的"多数实现只给一个相关系数"是**错的**，README 该句需修） |
| 3 | **Linux / 无头 / CI 一等公民**：全链在 Linux CPU、无 DISPLAY、无 GPU 下跑；`viz` 在 matplotlib 缺席时用内置 PNG/Netpbm 编码器出图；`test_env_guards.py` 断言 CI 不在 Windows、不存在 `VIC_*_HOME` | VIC 分析端公开为 **Windows**（浮动/网络许可、Windows PC）；VIC-2D 8 的"命令行批处理"是 Windows 上的批处理。MatchID 同为 Windows 10+ 且 dongle 年度续期 | **强**（DICe / OpenCorr 已跨平台，所以这是"对 VIC 的差异"，不是"对生态的差异"） |
| 4 | **逐位确定性 + 输入溯源**：同输入同配置逐位一致（与线程数/后端无关）、`config_hash` / `input_hash`、参数快照并入产物 provenance | 公开叙事是"Python 脚本带来可重复结果"（repeatable / standardized processing），未见**逐位确定性**或**输入哈希/溯源指纹**的承诺 | **中强** |
| 5 | **全链零许可证**：分析、出图、验证、校验全程无许可服务器、无 dongle | 11.4 的免许可是**只读查看器**；ZEISS 有免费层但功能受限；MatchID 需年度 dongle | **中**（程度差异，不是有无差异——11.4 已经拿走了一部分） |
| 6 | **失败语义与诚实台账**：退出码语义、fail-closed 门禁、xfail 登记实测数值、`evaluable=false` 公开登记、"合成不冒充"纪律 | 商业营销页面天然不会有此类负面登记（这不是他们的缺陷，是文体差异） | **弱-中**（对科研用户真实有效，但不宜作为主打卖点） |
| 7 | **格式一致性样例集**（`spec/conformance/`）与外部独立读取器 | 未见对应物 | **承诺，非事实**——尚未落地，禁止作为已有能力宣传 |

**必须同时登记的反面事实**（防止本节变成营销）：HL3 **无镜头畸变模型、无 Zhang 标定、无真实相机数据、无任何公开挑战集成绩、GUI 交互未验证、吞吐未测量、schema 仍 `1.0.0-draft.2`、B 组 0/6 正式 PASS**。上表第 1–5 条全部建立在一个**预 alpha 内核**上，而 VIC 的每一条都建立在 25+ 年的交钥匙产品上。

---

## 4. 对既有文档与裁决的修订建议（不改门槛，只改事实）

1. **`research/vic_public_feature_baseline.md` 必须改三处**：
   (a) 版本时间线补 11.2 / 11.4 / VIC-2D 8 公告；
   (b) "公开短板"删除/改写「开源插件市场不是其主叙事」与「许可与评估流程重」——前者已被社区枢纽推翻，后者被免许可查看器部分削弱；
   (c) 新增「VIC 公开逐点 sigma 与 Sigma_X/Y/Z，并公开声明其不含 bias」一行。
2. **`README.md` §"为什么再做一个 DIC"第 2 行需修**："多数实现只给一个相关系数"与公开事实不符，应改为"多数实现给的是**匹配层面的逐点 σ**，且明确不含偏差；HL3 做的是**从图像噪声到应变置信区间的端到端传播 + 覆盖率验证**"。这是 RUL-03 意义上的准确性问题，不是措辞问题。
3. **A5 的性质变了**：Stereo-DIC Challenge 1.0 的标定与平移图像集在 `idics.org/challenge` **免费可取**，且随附 MATLAB 分析脚本。A5 应从"预算/数据不可得"改登记为"**未派工**"。同时可诚实引用"5 家提交、全为 subset-based、受邀全局 DIC 代码未提交"这一生态事实。
4. **B6 的表述要让位**：MatchID 公开的 **levelling**（把 FEA 数据过与实测同样的滤波链）与我们的"同滤波链对比"是同一思想，**我们不是首创**；`IR3-O3` 报告与后续 PRD 中不得暗示原创性，应引用 MatchID 公开材料作为方法学先例。
5. **B5 有了对标文本**：GPG 第 2 版（DOI `10.58720/idics/gpg.ed2`）含全局 DIC 章节，可直接作为报告 lint 的条目来源。
6. **RUL-03 / RUL-06 不变**，新增一条提醒：不得因 VIC 上线社区扩展枢纽就反向宣称"我们比它开放"——**开放性的准确边界是"内核许可 + 文件格式规范 + 一致性套件"，不是"有没有 Python 和社区"**。

---

## 5. 来源清单（全部 2026-08-28 访问）

**厂商官网（一手）**
- `correlatedsolutions.com/vic-2d`、`/vic-3d`、`/iris`、`/vic-gauge`、`/vic-volume`、`/systems`
- `/recent-news`（存档索引）、`/recent-news/announcing-vic-3d-114`（2026-07-10）、`/recent-news/introducing-vic-hub-a-github-community-for-sharing-extensions-and-more`（2026-06-24）、`/recent-news/major-update-to-forming-limit-curve-testing-with-vic-3d-112`（2026-06-23）、`/recent-news/announcing-vic-2d-8`（2026-04-21）、`/recent-news/vic-3d-112-development-continues`（2026-03-31）、`/recent-news/python-dic-introducing-vicpyx`（2026-01-27）、`/recent-news/introducing-vic-3d-11`（2025-11-03）、`/recent-news/good-practices-guide-edition-2`（2025-11-24）

**厂商知识库 / 分发（一手）**
- `correlated.kayako.com/article/28-output-variables-in-vic-2d-and-vic-3d`（sigma / Sigma_X,Y,Z 定义）
- `correlated.kayako.com/article/32-resolution-and-accuracy`（置信区间开关与"不含 bias"声明、去刚体运动噪声评估流程）
- `correlated.kayako.com/article/118-installing-vicpyx`（`pip install vicpyx`、与旧 VIC-Py 不兼容）
- `correlated.kayako.com/section/8-software-information`、CSI Application Note AN-722 与 VIC-2D/VIC-3D/VIC-EDU 手册公开附件（相关准则、样条阶数、子区权重、低通、增量相关、五类阈值、时间滤波链、应变滤波与 Tresca/von Mises）
- `pypi.org/project/vicpyx/`（0.9.1 / 2026-07-10；`LicenseRef-Proprietary`；Python ≥3.10；numpy≥2.0, h5py, lxml, pillow）

**经销商 / 二手转述（标注为二手）**
- `acqtec.com/index/detection/detail/id/72.html`（中文，11.4 扩展能力细节、系统规格表、2026 新硬件 BLUE HAWK / BLUE FALCON）
- `luchsinger.it` VIC-3D 11 flyer（FE 对齐工作区、L-M 材料模型估计、OBJ/STL/PLY）
- LinkedIn 官方号 2026-07-22（免许可查看器）与 2026-06-25（社区枢纽）公告

**学会 / 文献**
- `idics.org`、`idics.org/guide/`（GPG Ed.2，DOI `10.58720/idics/gpg.ed2`）、`idics.org/challenge/`（Challenge 董事会与数据集）
- Stereo-DIC Challenge 1.0, *Experimental Mechanics*, DOI `10.1007/s11340-024-01077-7`
- 跨平台对照（Vic-3D vs Ncorr，偏差 <1%），*Results in Engineering* (2025), DOI `10.1016/j.rineng.2025.108174`
- Blaber, Adair, Antoniou, *Ncorr*, **Exp. Mech.** 55(6):1105–1122 (2015), DOI `10.1007/s11340-015-0009-1`

**竞品公开文档**
- `matchid.eu`、`matchid.eu/software`、`matchidservices.com/Wiki`（Windows 10+ / .NET / dongle 年度续期）
- `eikosim.com/en/release-notes/eikotwin-v2026-1-release-notes-2/`（2026-02-27）、`/release-notes/release-notes-eikotwin-2025-1/`、`/technical-articles/local-vs-global-dic/`
- `zeiss.com/metrology/us/software/zeiss-correlate.html`
- `opencorr.org` 与 OpenCorr 公开更新日志（GPU ICGN 2024-02、GUI 1.0/2.0 2024、ICLM 2024-12、GUI 3.0 2026-05-19）
- `github.com/dicengine/dice` 公开 README（跨平台、MPI + 线程、全局正则化走 CLI）

**未使用**：`github.com/Correlated-Solutions`（按任务约束排除）；厂商 GitHub 社区组织仓库（仅经厂商公告与检索摘要间接引用，标注为二手）。

---

*IR4-O1 完。本文只写入独占路径 `.agent_workspace/s1s4/IR4_O1_web_refresh.md`。引用键沿用 B1–B6、A5/A6、G6、RUL-03/06、GAP-1/5、S1–S8。*
