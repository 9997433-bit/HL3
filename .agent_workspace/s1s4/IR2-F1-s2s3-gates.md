ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR2-F1 · S2/S3 阶段 pass/fail 门禁清单（立体全链 + UQ/确定性/validate）

- **子代理**：IR2-F1（fable，云端）｜Impl-R2 / 10 代理（4 fable + 3 opus-fast + 3 gpt-sol）
- **日期**：2026-08-28
- **输入**：`s1s4/IR1_BRIEF.md`、`s1s4/IR2_DISPATCH.md`、`round3/R3-F4-beyond-vic-roadmap.md` §3-S2/S3、`round2/R2-F1-sota-reconciliation.md` §2 A/C 组表、`src/hl3/stereo/`（calibrate/triangulate 现状）、`src/hl3/pipeline/dic2d.py`、`src/hl3/io/hdf5_schema.py`、`benchmarks/metrology/metrics.json` s2/s3 占位段、`tests/test_s2_s3_smoke.py`
- **效力**：低于 `LEGAL.md` → RUL/ADR-LIC-001 → R2-F1 Gate 表 → G2 协议（RUL-08 顺序）。本文不新设阈值，只把已冻结的 A5/A6/A4(3D)/C1/C2/C3 门槛落到 Impl-R2 的独占路径与责任代理上。
- **判定纪律**：每个门二元 pass/fail，fail-closed；证据 = 仓库内工件 + 可复跑命令，不接受口头宣称。不达标按 RUL-07 登记 xfail 与实测数值，**禁止放宽阈值**。全程零显微镜实现（RUL-04/L-7/GAP-5）、零 VIC 逆向（LEGAL.md 红线）、无"比 VIC 快/准"表述（RUL-03）。

---

## 0. 诚实基线：S1 收口后立体/UQ 侧已有什么、没有什么

本 checkout（`42d0432` + 本轮已暂存文件）实测 `pytest tests src/tests -q`：**460 passed, 4 skipped**——4 个 skip 恰好是 `tests/test_s2_s3_smoke.py` 对 S2/S3 四个未实现表面（`hl3.stereo.match`、`hl3.pipeline.dic3d`、`hl3.uq`、`hl3.cli.validate`）的 importorskip。这就是 S2/S3 的起跑线。

### 0.1 已经存在（S2/S3 不得重做，只做复用与回归保护）

| 能力 | 证据 |
|------|------|
| 一阶 + 二阶（12 参数）ICGN、B 样条插值、FFT-CC 初值、9 态 `Status`、逐点位移协方差选项（`compute_covariance` + `image_noise_sigma`）——C2 位移协方差的现成源头 | `src/hl3/correlate/icgn.py`、`tests/test_icgn_second.py` |
| 应变引擎：切窗 PLS、engineering/green_lagrange 张量族、VSG 记账同一公式 | `src/hl3/strain/`（pls/tensors/vsg/field） |
| 2D pipeline：确定性单线程、参数快照 `_provenance`、失败传播保真、schema 合规产物 | `src/hl3/pipeline/dic2d.py`、`tests/test_pipeline_2d.py` |
| 三角化：四档法（中点/DLT/Sampson/非线性）、解析基本矩阵、极线度量、**匹配项一阶 3×3 位置协方差 + 手性/协方差质量门**（合成针孔 0.02 px 噪声下 RMS ≈ 4.9 µm） | `src/hl3/stereo/triangulate.py`、metrics.json `stereo_synthetic_triangulation` |
| 标定**合成测试床**：已知真值装配 + 线性 DLT 后方交会 + 误差归因（其 docstring 自认"Not Zhang's method"） | `src/hl3/stereo/calibrate.py` |
| schema `1.0.0-draft.2`：`uncertainty` 组（u_std/v_std 必填）、`covariance`、`config_hash`/`input_hash`/`content_hash`、provenance 组；`validate_file` 已含"无标定协方差不得声明 `uncertainty/@method='propagated'`"检查 | `src/hl3/io/hdf5_schema.py`、`docs/schema-hdf5.md` |
| metrics.json 已由 IR2-G3 建好 s2/s3 段（键：`a5_stereo_3d_accuracy`、`a6_calibration_accuracy`、`a4_3d_strain_noise_floor`、`c1_deterministic_reproduction`、`c2_uncertainty_propagation`、`c3_schema_validation`），当前全部 `not-evaluated` | `benchmarks/metrology/metrics.json` |

### 0.2 尚不存在或本环境闭合不了（S2/S3 门禁的全部对象与诚实边界）

| 空白 | 诚实说明 |
|------|----------|
| 立体匹配 | `hl3.stereo.match` 不存在；任何阶次的极线约束匹配都没有 |
| 3D pipeline | `hl3.pipeline.dic3d` 不存在：无时序匹配、无 U/V/W、无切平面曲面应变 |
| Zhang 标定 + 光束法平差 + bootstrap Σ_cal + 逐图残差落盘 | 不存在，且 `src/hl3/stereo/calibrate.py` **不在任何 IR2 独占路径内**——A6 正式门与 C2 的标定协方差项本轮结构性无法关闭，只能诚实登记 |
| UQ 包 | `hl3.uq` 不存在：无蒙特卡洛引擎、无覆盖率测试、无端到端链 |
| validate CLI 与纯 h5py 读取器 | `hl3.cli` 不存在；pyproject 无任何 console script；`validate_file` 只在 `hl3.io` 内部 |
| Stereo Challenge 数据 | 未下载（IR1_BRIEF）：A5 官方流程成绩本轮在仓库内不可产生，合成孪生先行 |
| schema 1.0 | 仍 `1.0.0-draft.2`（S1 遗留 G6）：C3 一致性测试针对 draft.2 编写，不得假装已冻结 |
| 异机复算 | 本环境单机：C1 的 <1e-4 px 异机差只能交付脚本 + 同机双跑证据，异机实测移交 |

---

## 1. 门禁总表

责任代理与独占路径按 `IR2_DISPATCH.md`；规格输入为并行产出的 `IR2-F2-stereo-match-spec.md`（匹配）、`IR2-F3-uq-contract.md`（UQ）、`IR2-F4-validate-cli.md`（validate），门槛数值以本文（即 R2-F1 冻结表）为准，规格与本文冲突时本文优先。复跑命令以仓库根为工作目录。

### A 组 · 立体匹配（责任：IR2-O1，路径 `src/hl3/stereo/match.py`、`tests/test_stereo_match.py`）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S2-MAT-1 极线约束匹配存在** | `hl3.stereo.match` 提供极线约束 ICGN 立体匹配：消费标定装配/基本矩阵，**二阶形函数为默认**（R3-F4 §3-S2）；逐子集求解调用 `hl3.correlate` 规范内核而非重实现；`Status` 枚举数值不变，不新增未文档化状态码 | `tests/test_stereo_match.py` 单元测试 + 模块 docstring |
| **G-S2-MAT-2 合成精度锁定** | 已知视差场的合成立体散斑对上：匹配点极线残差与视差误差上界写死在测试内（实测后锁定具体数，禁止"足够小"式断言）；有效点率下界同样写死 | `tests/test_stereo_match.py` 对照测试 |
| **G-S2-MAT-3 失败语义** | 遮挡/出视场/极线约束违背/退化纹理 → 状态码 + 无效标记，不得输出貌似合理的数；极线残差超限点必须被标出而非静默保留 | 注入失败点的单元测试 |
| **G-S2-MAT-4 协方差直通** | 匹配输出的逐点协方差（或可推导的噪声项）能被 `triangulation_covariance` 消费——这是 C2 立体链传播的接口前提；接口在测试中实际行使一次 | `tests/test_stereo_match.py` 接口测试 |

### B 组 · 3D pipeline 与 S2 计量锚点（责任：IR2-O2，路径 `src/hl3/pipeline/dic3d.py`、`tests/test_pipeline_3d.py`）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S2-P3D-1 端到端可跑** | 单一入口：双目图像序列 + 标定 → 立体匹配 + 时序匹配 → 三角化 → U/V/W 场 → schema 合规 HDF5；`validate_file` 零 error（无 h5py 按既有 skip 纪律） | `tests/test_pipeline_3d.py` 端到端测试 |
| **G-S2-P3D-2 四路闭环自检** | 参考左→参考右、参考左→当前左、参考右→当前右、当前左→当前右四路匹配组合闭合，闭合残差阈值实测后写死；超限点置无效并计数进产物 | 测试 + 产物 flags 断言 |
| **G-S2-P3D-3 曲面应变复用** | 切平面局部坐标系上复用 `hl3.strain` PLS（不 fork 应变代码）；张量命名与 `hdf5_schema.STRAIN_TENSORS` 严格一致；VSG 记账沿用同一公式并随结果输出 | `tests/test_pipeline_3d.py` + docstring |
| **G-S2-P3D-4 确定性** | 同输入同参数双跑逐位一致；参数快照 + 输入图像哈希（`input_hash`）写入产物——C1 在 3D 链的埋桩，口径与 `dic2d` 的 `_provenance`/schema `config_hash` 一致 | 测试内双跑 + 产物读回断言 |
| **G-S2-A5 3D 位移精度（锚点 A5）** | **合成孪生刚体协议**：±20 mm 行程合成平移下 3D 误差 ≤80 µm（R2-F1 冻结值）。Stereo Challenge Sample 1 官方流程成绩需要数据下载，数据缺席时 metrics.json 记 `formal_gate_evaluable: false` + 原因（沿 A1 先例），合成孪生数字**不得冒充官方成绩** | metrics.json `s2.gates.a5_stereo_3d_accuracy` + 复跑命令 |
| **G-S2-A6 标定分数（锚点 A6）** | 正式门 = Zhang/光束法平差标定 RMS ≤0.03 px 且极线误差 ≤2× 标定分数。**本轮无人持有 `calibrate.py` 独占路径**：本门只允许两种登记——(a) 现有合成测试床的重投影/极线数字带 `formal_gate_evaluable: false` + "标定升级未派工"原因；(b) 保持 `not-evaluated`。任何把 DLT 合成床数字写成 A6 正式 pass 的行为记 fail | metrics.json `s2.gates.a6_calibration_accuracy` |
| **G-S2-A4-3D 应变噪声底（锚点 A4(3D)）** | 带噪静态立体对经全链：σ_ε ≤100 µε，成绩必须与所声明 VSG 成对出现；**离面平移伪应变 ≤50 µε**（合成孪生离面平移，R3-F4 §3-S2 冻结值）。不达标 → xfail 登记 (σ_ε, VSG) 或伪应变实测值 | metrics.json `s2.gates.a4_3d_strain_noise_floor` + 测试 |

### C 组 · UQ 传播链（责任：IR2-O3，路径 `src/hl3/uq/**`、`tests/test_uq.py`）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S3-UQ-1 链条存在** | `hl3.uq` 提供图像噪声 σ → 位移协方差（复用 `ICGNResult.covariance`，不重实现）→ 应变 CI 的端到端传播 API；每个输出量带逐点 σ 与 CI | `tests/test_uq.py` + API docstring |
| **G-S3-UQ-2 蒙特卡洛交叉验证** | 合成真值上解析协方差 vs ≥1000 次蒙特卡洛：比值上下界写死在判定内。全量 ≥1000 次跑一次并入 metrics.json（带复跑命令与耗时）；CI 内允许文档化的缩减规模冒烟，但 pass/fail 以全量成绩为准 | metrics.json `s3.gates.c2_uncertainty_propagation` + 测试 |
| **G-S3-UQ-3 覆盖率实证** | 95% CI 实证覆盖率 ∈ [90%, 98%]（R2-F1 C2 冻结带），位移与应变两级各自达标；覆盖率数字与试验次数、seed 一并入档 | 同上 |
| **G-S3-UQ-4 标定协方差项诚实** | Σ_cal 接口槽位存在；bootstrap Σ_cal 本轮未派工 → 缺席时输出**不得**声明 `uncertainty/@method='propagated'` 全链（`validate_file` 既有检查即为此门的执法器），缺席事实显式登记 | `tests/test_uq.py` + validate 断言 |

### D 组 · 确定性/可复现（C1；责任：IR2-O2 产物侧 + IR2-O3 报告侧） 

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S3-C1-1 快照与哈希强制** | dic2d 与 dic3d 产物均含完整参数快照 + 输入图像哈希（schema `config_hash`/`input_hash` 路径），缺任一项 `validate_file` 报 error | 产物往返测试 |
| **G-S3-C1-2 复算差异报告** | 差异报告脚本存在：对两份产物输出逐点位移差统计的机读报告；同机双跑差异恒为 0 的测试常绿；**异机 <1e-4 px 是移交项不是本轮成绩**，metrics.json 只登记同机证据 + `formal_gate_evaluable: false`（异机） | 脚本 + metrics.json `s3.gates.c1_deterministic_reproduction` |

### E 组 · validate 与开放读取（C3；责任：IR2-O3，路径 `src/hl3/cli/validate.py`、`tests/test_validate.py`）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S3-VAL-1 CLI 存在** | `python3 -m hl3.cli.validate <file>` 可用：退出码 0=合规、非 0=违规，输出机读；对 dic2d 与 dic3d 真实产物各行使一次（console-script 注册涉及 pyproject，不在本轮独占路径，不作门槛） | `tests/test_validate.py` |
| **G-S3-VAL-2 一致性测试套件** | 变异测试：删必填数据集、改坏 schema 版本、删 uncertainty 必填项等 ≥5 种注入违规逐一被检出；合规产物零误报 | 同上 |
| **G-S3-VAL-3 纯 h5py 参考读取** | 存在仅依赖 h5py + 标准库的参考读取路径，读回全部结果量；测试以子进程方式验证读取过程未 import `hl3`（"无 HL3 亦可读"从口号变成断言）；针对 `1.0.0-draft.2` 编写并注明——schema 冻结（G6）仍是 S1 遗留，不在本轮假装完成 | `tests/test_validate.py` 子进程测试 |

### F 组 · 汇总判定（责任：IR2-G2 冒烟 / IR2-G3 metrics.json）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S23-SUM-1 机器可判** | metrics.json s2/s3 段由脚本重生成：每门带 `status`、实测值、阈值、复跑命令、源码 blob 哈希；pass/fail 由脚本比较判定，人手不改 status；键名沿用 0.1 表所列既有键 | metrics.json + 生成脚本 |
| **G-S23-SUM-2 套件常绿** | Linux CPU、无网络、无 GPU 下全量 pytest 通过或按纪律 xfail/skip；**460 项基线不改一行断言全绿**；`test_s2_s3_smoke.py` 的 4 个 skip 随模块落地逐个翻绿；S2/S3 新增测试总时长 ≤5 min（沿 S1 门） | pytest 输出 / CI 日志 |
| **G-S23-SUM-3 S2/S3 出口** | 出口 = MAT-1…4、P3D-1…4、UQ-1…4、C1-1…2、VAL-1…3、SUM-1…2 全 pass，**且** A5/A6/A4(3D) 三锚点各自为 pass、"数据/派工缺席的 `formal_gate_evaluable: false` 登记"或 RUL-07 xfail。存在未登记 fail → S2/S3 不出口，冻结 Impl-R3（S4）派工（R3-F4 §7 熔断第 1 条） | 本表全量核对 + `PROGRESS.md` |

---

## 2. 全局约束（随门禁生效，违反任一即该代理产出整体 fail）

1. **独占路径纪律**：`git add` 只用各自独占路径，禁止 `git add .`；`src/hl3/stereo/calibrate.py`、`pyproject.toml` 本轮无人持有，任何代理不得改动。
2. **零显微镜**：新增 `match.py`/`dic3d.py` 必须沿用 calibrate/triangulate docstring 的范围排除句式——L6 非参数畸变场/立体显微镜层零实现零绑定（GAP-5 fail-closed）。
3. **零 VIC 逆向**；对比表述只引公开资料并标"厂商公开宣传值，未独立验证"。
4. **阈值不可议**：A5 ≤80 µm、A6 RMS ≤0.03 px 且极线 ≤2×、A4(3D) ≤100 µε、离面伪应变 ≤50 µε、C2 覆盖率 ∈ [90%, 98%]、C1 异机 <1e-4 px，全部来自 R2-F1/R3-F4 冻结表；差距只能 xfail 或 evaluability 登记。
5. **数据纪律**：Challenge 数据不入 git（N5）；若预算内下载 Sample 1（35 mm 组）必须建 SHA-256 manifest；禁止下载 Sample5/Tensile-S6 大包。
6. **合成数字不冒充官方成绩**：一切合成孪生成绩在 metrics.json 与报告中显式标注 dataset 来源，混淆记 fail。
7. **报告首行**：每个 IR2 代理报告第一行 `ACTUAL_MODEL_SLUG: <slug>`，禁止静默降级。

---

## 3. 与 R3-F4 §3-S2/S3 出口证据的对账与移交

R3-F4 出口项 → 门禁覆盖：**A6** → G-S2-A6（本轮因标定升级未派工只能 evaluability 登记，Zhang + 光束法平差 + bootstrap Σ_cal + 逐图残差落盘**整体移交 Impl-R3**）；**A5** → G-S2-A5（官方流程成绩随数据下载移交）；**A4(3D) 与离面伪应变** → G-S2-A4-3D；**C1** → G-S2-P3D-4 + G-S3-C1-1…2（异机实测移交）；**C2** → G-S3-UQ-1…4（Σ_cal 接入随标定升级移交）；**C3** → G-S3-VAL-1…3（schema 1.0 冻结即 G6 仍为 S1 遗留，随 Impl-R3 收口）；**UQ 白皮书初稿** → 未派工，登记为 Impl-R3 交付候选（IR2-F3 契约文档为其种子）。

*IR2-F1 完。本文只写入独占路径 `.agent_workspace/s1s4/IR2-F1-s2s3-gates.md`；引用键沿用 A4/A5/A6、C1–C3、G6、RUL-03/04/07/08、GAP-5、S1–S8。*
