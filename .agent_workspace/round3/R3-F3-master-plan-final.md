ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# R3-F3 · HL3 最终统一计划（Round 3 冻结稿）

- **子代理**：R3-F3（fable，云端）｜Round 3 / 10 代理（4 fable + 3 opus-fast + 3 gpt-sol）
- **日期**：2026-08-28
- **文档性质**：本文是三轮调度的**最终统一计划**——把 Round 1 规格、Round 2 裁决（RUL-01…08）与实现现状、Round 3 收尾任务汇编成单一入口，并宣布冻结清单（§9，FRZ-01…14）。
- **效力声明**：本文为**汇编与冻结记录**，不创设高于既有裁决的新效力。任何表述与既有文件冲突时，一律按 RUL-08 的效力顺序解释：`LEGAL.md` → `round2/R2-F1-sota-reconciliation.md` + ADR-LIC-001（`round2/R2-G1-license-adr.md`）→ R1-F2 Gate 表 → R1-G2 基准协议 → R1-O1/O2/O3 规格 → 其余文件。推翻任何冻结项需新的书面 ADR 并留痕。
- **输入**：`ROUND1_BRIEF.md`、`ROUND2_BRIEF.md`、`round2/R2-F1-sota-reconciliation.md`（RUL-01…08）、`round2/R2-G1-license-adr.md`、`round2/R2-F4-r3-gates.md`、`round2/R2-F2/F3/O1/O2/O3/G2/G3` 各报告、`round3/DISPATCH.md`、已落地的 `round3/R3-G1-sbom-legal.md` 与 `round3/R3-G3-ci-final.md`、仓库现状（`src/`、`tests/`、`docs/`、CI）。

---

## 0. 一页总览

**产品**：HL3-2D（对标 VIC-2D 8）与 HL3-3D（对标 VIC-3D 11.4），共享 Apache-2.0 开源内核 `hl3-core`，Python-first，公开 HDF5 schema，CPU float64 参考实现为计量规范，GPU 为可选加速后端。

**超越策略**（Round 1 冻结、Round 2 收敛为可判定 KPI）：跨平台与自助评估、Python-first、UQ 默认输出、GPU 相关器 + 公开可复现基准、open-core 可审计内核、局部+全局双内核与 FEA 原生闭环、公开 HDF5 schema。

**三轮结束时的诚实状态**（按 R2-F4 双轴量表）：**规划完备度 A ≈ 4，实现完备度 B ≈ 2.5**。已有 CPU ICGN 内核 + 立体标定/三角化原型 + 可执行 schema + CPU-only CI；没有 GUI、实时、采集硬件、GPU 后端、Challenge 实测——这是任务边界的设计事实，不是执行失败（R2-F4 §0）。对外任何"超越 VIC"的表述必须附带 §7 的残余差距台账。

---

## 1. 产品定义（冻结）

| 项 | 定义 |
|----|------|
| HL3-2D | 单相机平面 DIC。对标并计划最终超过 VIC-2D 8 的**公开**能力面 |
| HL3-3D | 双目/多目立体 DIC。对标并计划最终超过 VIC-3D 11.4 的**公开**能力面 |
| `hl3-core` | 两产品共享内核：相关器（ICGN）、标定、三角化、应变、UQ、HDF5 IO、CLI、Python 绑定 |
| 计量规范 | CPU float64 参考实现（RUL-02）；一切精度 Gate、golden 文件、UQ 验证以其定义正确性 |
| 商业形态 | open-core：内核 Apache-2.0 开源；schema 文档 CC-BY-4.0；商业 GUI/采集/实时/许可管理层为 `LicenseRef-HL3-Commercial`（RUL-01，ADR-LIC-001） |
| 对标口径 | 仅使用公开产品页、公开宣传材料、已发表文献与公开数据集；从未接触任何 VIC 二进制或专有实现细节 |

**要超越的是整条测量链**（采集–标定–相关–应变–可视化–Python–报告–实时），不是一个相关器 demo（`PROGRESS.md` 关键发现 3）。

## 2. 约束性裁决汇编（RUL-01…08，全文见 `round2/R2-F1-sota-reconciliation.md`）

| 编号 | 裁决要点（冻结） |
|------|------------------|
| RUL-01 | 许可证：独立重实现 + **Apache-2.0 开源内核** + open-core 专业模块闭源 + schema 文档 CC-BY-4.0；驳回 MPL 内核；禁止任何 OpenCorr 文件级复用；OpenCorr GPU 闭源二进制永久禁用（追认 ADR-LIC-001） |
| RUL-02 | **CPU float64 参考实现是计量规范**；GPU 是可选加速后端，parity 双档：通用合入门位移差 ≤1e-4 px，`--metrology-mode` 认证门 ≤1e-6 px；本环境 CI 只跑 CPU；"GPU-first、CPU 回退"表述作废 |
| RUL-03 | **R1-G2 §7 是唯一合法吞吐口径**；全部吞吐数字为协议绑定**目标**而非宣称（2D：32 核 CPU ≥1×10⁶ / 单消费级 GPU ≥5×10⁶ POI/s；3D GPU ≥3×10⁶ 3D-POI/s @ICGN1 / ≥1×10⁶ @ICGN2）；同机四条件满足前禁止"比 VIC 快 X 倍"；2D 点与 3D 点永久分账 |
| RUL-04 | 显微镜/SEM 畸变：**书面 FTO 结论前零实现代码**（即使 US7133570B1 显示 Expired-Fee-Related）；仅交付法务检索清单（ADR-LIC-001 §5）；参数化标准畸变模型 L1–L5 不受限；schema 枚举槽位可存在但无实现绑定 |
| RUL-05 | 全局/AL-DIC：**接口与数据模型随 v1 冻结**（`mode: LOCAL\|GLOBAL_FE\|ALDIC`、`GridKind::FeMesh`、统一 HDF5 schema）；实现分期——v1 仅 LOCAL，GLOBAL_FE 为 v1.x 官方 beta，ALDIC 为 v2；均为官方内核模块（同仓、Apache-2.0），不外包第三方插件 |
| RUL-06 | VIC UI/iris/vicpyx 认知强制挂"公开资料推断 + 置信度"标签，永不进"已对齐"清单；实测仅限用户自有合法 Windows 工作站；本环境不做任何 VIC 安装或评估 |
| RUL-07 | Round 2 代码落地令：CPU 一阶 2D ICGN 最小内核 + `synth_speckle.py` 可重复测试（G2 §2.3 门槛，未达标 xfail 登记，禁止放宽门槛）——**已履行**（R2-O1，见 §4） |
| RUL-08 | 文档效力顺序（见本文效力声明）；GPU/CPU parity 双档并存；空间分辨率 L10%（内部主口径）/L20% 双口径并报、对榜单用其官方口径；"点/秒"定义分账 |

## 3. "超越 VIC"判定公式与 KPI（冻结，全文见 R2-F1 §2）

> **超越成立 ⇔ A 组（精度平权，6 项）全部 PASS ＋ B 组（显著优势，6 项）≥ 4/6 PASS ＋ C 组（独有能力，3 项）全部 PASS**，且每项 PASS 均有第三方可复算的证据包（公开数据集或开源生成器 + `metrics.json` + `benchmark-manifest.json` + 一键复跑命令）。

- **A 组**：2D 位移噪声底 σ_u（A1）、插值 S 曲线峰峰值（A2）、Star 图 MEI（A3）、应变噪声底（A4）、立体 3D 误差包线（A5）、标定分数/极线误差（A6）。
- **B 组**：吞吐（B1，按 RUL-03 目标表）、实时（B2）、首结果时间 TTFR（B3）、跨平台与集群（B4）、GPG 内建（B5）、FEA 闭环（B6）。
- **C 组**：可复现性（C1）、UQ 默认化（C2）、开放 schema（C3）。
- **禁止宣称清单**（随 KPI 冻结）：无同机四条件不比快慢；厂商宣传值必标"未独立验证"；UI/工作流不做"优于 VIC"表述；显微镜能力冻结期内零宣称；精度数字须 ≥3 套散斑图案平均。

所有 KPI 只锚定公开可验证对象（iDICs Challenge、GPG 条款、我方开源生成器、厂商公开宣传值）。

## 4. 实现现状基线（截至 Round 3 进行中）

### 4.1 已落地（可运行、有测试）

| 模块 | 内容 | 状态与实测（本机数字，非对 VIC 宣称） |
|------|------|------|
| `src/hl3/correlate/icgn.py` | CPU 一阶 IC-GN（ZNSSD + 双三次 B 样条 + FFT-CC 初值 + 路径无关） | 参考实现；合成平移 mean\|err\| ≈ 8×10⁻⁴ px（R2-O1） |
| `src/hl3/stereo/calibrate.py` + `triangulate.py` | 针孔投影、基础矩阵、四档三角化、合成标定 | 原型；0.02 px 匹配噪声下 ~4.9 µm RMS（R2-O2 合成台架） |
| `src/hl3/io/hdf5_schema.py` | `.hl3` 容器常量 + 参考读写器 + 结构验证器 | schema `1.0.0-draft.2`（R2-O3）；1.0 冻结按 §6 的 G6 门 |
| `src/hl3/capture/mock.py` | 确定性无硬件采集 | 可用；CPU-only CI 基座（R2-G3） |
| `tests/` + `src/tests/` | 单测 | **87 passed**（R3-G3 已统一双路径发现并在 CI 安装 h5py） |
| `.github/workflows/ci.yml` | CPU-only CI，`HL3_CI_CPU_ONLY=1`、禁 GPU、禁 Windows | R3-G3 定稿 |
| 依赖与法务 | 直接依赖全部宽松许可；无 OpenCorr vendor；无 Windows 安装包/二进制 | R3-G1 声明级清查 PASS（发行前仍需锁定版全量 SBOM） |

### 4.2 尚未实现（如实列出）

标定求解器产品化、应变算子、UQ 传播链端到端、全局 FE-DIC/ALDIC 求解器本体（接口已冻结）、GPU 后端、命令总线、GUI、实时、采集硬件对接、Challenge 数据实测、Windows/macOS CI。吞吐一律**未经测量**。

### 4.3 已知技术债（Round 2 边界记录，Round 3 处置）

1. Keys 双三次插值（a=−0.5，无预滤波）S 曲线 P-P ~0.03 px 未过 0.02 px 暂定门（R2-G2）；内核默认 B 样条，该结果留作"必须实测最终插值器"的证据。
2. 双测试路径曾致漏收集——R3-G3 已在 `pyproject.toml` 与 CI 双侧修复。
3. HDF5 测试在无 h5py 环境 skip——R3-G3 已把 h5py 纳入 CI。
4. Stereo Challenge 标定主导误差尚未在原型上复现（R2-O2 已诚实记录），归入 §7 的 G2。

## 5. Round 3 收尾任务与验收门

### 5.1 任务 → 代理映射（`round3/DISPATCH.md`）

| ROUND2_BRIEF §4 任务 | 责任代理 | 状态（本文写作时） |
|------|------|------|
| 1. 交叉核验 RUL 与代码一致（无显微镜代码、无 OpenCorr vendor、无吞吐吹牛） | R3-F2（claims/legal 扫描）+ R3-G1（SBOM） | R3-G1 已 PASS；R3-F2 进行中 |
| 2. `benchmarks/metrology/metrics.json`（ICGN bias、噪声底、立体重建误差） | R3-G2 | 进行中（E-8 硬门） |
| 3. CI 装 h5py；统一测试发现路径；补边界测试 | R3-G3 + R3-O1/O2 | R3-G3 已定稿；O1/O2 加固进行中 |
| 4. 冻结最终 `MASTER_PLAN.md` + 用户可读路线图 | **R3-F3（本文）** + R3-F4 | 本文即冻结稿；路线图归 R3-F4 |
| 5. README/文档与代码对齐 | R3-O3 | 进行中 |
| 6. 最终 SOTA 验收（E/L/双轴打分） | R3-F1 | 进行中 |

### 5.2 验收框架（采 R2-F4，冻结）

- **E 系列存在性 Gate**：E-1/E-2/E-3/E-4/E-8 为硬门，缺失即 FAIL；改道必须在 `MASTER_PLAN.md` 留痕，否则按缺失处理（fail-closed）。
- **L 系列法务扫描**：默认拒绝；L-1（VIC 二进制）、L-2（未白名单专有字符串）、L-4（OpenCorr 拷贝）、L-6（声明造假）、L-7（显微镜代码）一票否决；豁免必须登记 `legal/scan-allowlist.txt`。
- **双轴打分**：A（规划）与 B（实现）分开报，禁止折算；证据先行、就低不就高、双人独立。Round 2→3 放行线：A ≥ 4 且 B ≥ 2，硬门全 PASS——**已满足**（ROUND2_BRIEF：A ≈ 4，B ≈ 2.5）。
- **Round 3 终审**由 R3-F1 按上述框架出具，任何自评 B ≥ 4 先查 L-6。

### 5.3 Round 3 红线（重申）

禁止假装已有 iris/VIC-Snap 级能力；禁止下载/安装/逆向任何 VIC 二进制；禁止把本机数字写成对 VIC 的实测对比；禁止修改他人独占路径；`git add` 不用 `.`。

## 6. Round 3 之后的路线图（计划级冻结；用户可读详版归 R3-F4）

**阶段门**（技术依赖顺序，非日历承诺）：

> P0 研究冻结与法务 ✅ → P1 共享内核（ICGN+应变+HDF5）**部分完成** → P2 HL3-2D MVP → P3 立体标定 + HL3-3D MVP → P4 GPU 路径无关 + 实时 Gauge 对标 → P5 GenICam 采集 → P6 可视化 + FEA + Python 工作流 → P7 UQ 校准 + Challenge 公证 → P8 多相机/FFT/IR（显微镜过 FTO 门后才入）→ P9 产品化（三平台、安装器、商业 GUI）。

**版本切分**（RUL-05 冻结）：v1 = LOCAL 内核 + 2D/3D 全链 headless + 开放 schema 1.0 + UQ 默认开；v1.x = GLOBAL_FE beta + GPU 后端过 parity 门；v2 = ALDIC + 实时/采集生态。

**测量链补齐顺序的裁决理由**（冻结）：精度地基（P1–P3）先于吞吐（P4），因为计量信誉由 CPU 规范实现建立（RUL-02）；采集与实时（P4–P5）先于 GUI 打磨（P9），因为它们决定数据契约；Challenge 公证（P7）是对外宣称"超越"的唯一合法证据入口（§3）。

## 7. 残余差距与移交台账（对外表述必须附带）

### 7.1 任务边界差距（R2-F4 GAP 表，Round 3 结束仍存在）

| # | 差距 | 后续合法闭合路径 |
|---|------|------|
| GAP-1 | VIC 级 GUI 与 iris 级可视化 | P9 产品化 + 持证用户 Windows 走查协议 |
| GAP-2 | 实时（Gauge 对标）与相机生态（Snap 对标） | P4/P5 + 硬件在环台架 |
| GAP-3 | GPU 吞吐验证 | 固定基准机 + G2 §7 全量披露 |
| GAP-4 | 与 VIC 11.4 直接精度对比 | 下届公开 Challenge 排名；持证实验室合作评测 |
| GAP-5 | 显微镜畸变模块 | FTO 检索清单已交（ADR-LIC-001 §5），书面 FTO 后进 P8 |
| GAP-6 | Windows/macOS 平台一致性 | 三平台 CI 在 P9 前接入 |

### 7.2 工程移交清单（R2-F1 §4 G1–G10 的 Round 3 末态归置）

- **Round 3 内闭合或收窄**：G1（2D 内核收紧，R3-O1）、G2 部分（立体加固，R3-O2）、G5 部分（UQ 最小闭环随内核加固）、（CI/测试路径）R3-G3 已闭合。
- **移交后续版本**：G3（GPU parity 测试床 → v1.x）、G4（GLOBAL_FE/ALDIC 实现 → v1.x/v2）、G6（schema 1.0 冻结评审，前置 = 首次跑通 Challenge 数据）、G10（Challenge 精选子集下载 + SHA-256 manifest，预算内执行）。
- **移交用户侧**：G7（FTO 法务通道）、G8（VIC UI 持证走查，按 R1-G3 §6 清单）。

## 8. 法律与合规红线（汇总，全文见 `LEGAL.md` 与 ADR-LIC-001）

1. `LEGAL.md` 效力最高。禁止破解/盗版/逆向/密钥生成/虚假评估申请；本 Linux 环境不做任何 VIC 安装。
2. 全部算法从公开文献独立实现；OpenCorr 零复用；无许可证仓库只读论文；"仅研究"许可不进商业 HL3。
3. 显微镜/SEM 畸变零实现直至书面 FTO（L-7 永久 fail-closed）。
4. 每次发行过 ADR-LIC-001 §7 的五条发行 Gate（LICENSE 一致、SBOM 完整、来源声明、扫描干净、显微镜冻结确认）。
5. 生产运行时依赖 allowlist：NumPy、SciPy、h5py（Qt/PySide6 条件允许、当前不引入）；新增依赖须过 SBOM 与审计。

## 9. Round 3 冻结清单（FRZ-01…14）

以下条目自本文合入起冻结；推翻任何一条需新的书面 ADR 并在 `MASTER_PLAN.md` 留痕。

| 编号 | 冻结项 | 权威出处 |
|------|--------|----------|
| FRZ-01 | 产品定义：HL3-2D / HL3-3D + 共享 `hl3-core`，对标 VIC-2D 8 / VIC-3D 11.4 的公开能力面 | 本文 §1；`MASTER_PLAN.md` |
| FRZ-02 | 裁决体系 RUL-01…08 整体具约束力 | `round2/R2-F1-sota-reconciliation.md` |
| FRZ-03 | 许可证三层：Apache-2.0 内核 + CC-BY-4.0 schema 文档 + `LicenseRef-HL3-Commercial` GUI；OpenCorr 零复用、GPU 闭源库永久禁用 | RUL-01；ADR-LIC-001 |
| FRZ-04 | CPU float64 参考实现 = 计量规范；GPU parity 双档（≤1e-4 px 合入门 / ≤1e-6 px 计量门） | RUL-02、RUL-08 |
| FRZ-05 | 吞吐唯一口径 = R1-G2 §7 协议；目标表（CPU ≥1e6 / GPU ≥5e6 POI/s；3D ≥3e6@ICGN1、≥1e6@ICGN2）；2D/3D 点分账；同机四条件前禁比较宣称 | RUL-03 |
| FRZ-06 | 显微镜/SEM 畸变零实现直至书面 FTO；检索清单为唯一工程交付 | RUL-04；ADR-LIC-001 §5 |
| FRZ-07 | 求解器分期：v1 仅 LOCAL；GLOBAL_FE = v1.x 官方 beta；ALDIC = v2；接口与 schema 槽位随 v1 冻结 | RUL-05 |
| FRZ-08 | 超越判定公式：A 组 6/6 + B 组 ≥4/6 + C 组 3/3 + 可复算证据包；禁止宣称清单 5 条 | R2-F1 §2 |
| FRZ-09 | 文档效力顺序（LEGAL → R2-F1+ADR → F2 Gate → G2 协议 → O1/O2/O3 → 其余）；本文与 R3 文件为汇编性质、不越位 | RUL-08 |
| FRZ-10 | HDF5 schema `1.0.0-draft.2` 为当前冻结草案；1.0 冻结前置条件 = 首次跑通 Challenge 数据（G6 门） | R2-O3；R2-F1 §4 |
| FRZ-11 | 验收框架：E 系列存在性硬门 + L 系列 fail-closed 法务扫描 + A/B 双轴分离打分；诚实末态 A ≈ 4、B ≈ 2.5 | R2-F4；ROUND2_BRIEF |
| FRZ-12 | 残余差距台账 GAP-1…6 与移交清单 G1…G10：对外"超越"表述必须附带 | R2-F4 §4；R2-F1 §4 |
| FRZ-13 | 法律红线全集（禁破解/逆向；独立实现；VIC UI 仅用户侧持证走查；空间分辨率 L10%/L20% 双口径） | `LEGAL.md`；RUL-06/08 |
| FRZ-14 | 路线图阶段门 P0–P9 与 v1/v1.x/v2 版本切分及测量链补齐顺序 | 本文 §6；R1-F4；RUL-05 |

## 10. 变更控制

1. 冻结项只能由**新的书面 ADR** 推翻：写明被推翻条目编号、理由、影响面，落盘 `.agent_workspace/`（或后续 `docs/adr/`），并在 `MASTER_PLAN.md` 追加记录。
2. 数字口径变更（容差、门槛、目标）额外要求：给出复跑证据或协议引用；禁止为迁就未达标结果而放宽门槛（RUL-07 纪律推广到全部 Gate）。
3. 本文与 `MASTER_PLAN.md` 的"Round 3 冻结"节同步生效；两处不一致时以本文为准（并视为需要立即修复的文档缺陷）。

---

*R3-F3 完。本文未修改 `src/` 与其他代理独占路径；仅新增本文件并向 `MASTER_PLAN.md` 追加"Round 3 冻结"节。*
