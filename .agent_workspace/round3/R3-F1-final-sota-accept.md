ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# R3-F1 最终 SOTA 验收报告（双轴评分 + E 门判定）

- **子代理**：R3-F1（fable，云端）｜Round 3 / 10 代理（4 fable + 3 opus-fast + 3 gpt-sol）
- **日期**：2026-08-28
- **量表与门**：完全按 `round2/R2-F4-r3-gates.md`（E 系列存在性门、§3 双轴 0–5 整数量表、§3.4 防作弊条款、§3.5 放行判据）执行；效力顺序按 RUL-08。
- **复核方法**：在本工作区实测，非转抄——① `python3 -m pytest tests src/tests -q` 本人复跑；② `noise_floor_stub.py` 按 R2-G2 §2 文档命令本人复跑并与其报告数字逐位比对；③ 全部 E 门工件逐一打开核对最小内容契约；④ `src/`、`tests/` 做显微镜零实现与许可证头抽查。
- **评审时点**：git HEAD `3a70fcf`（R3-F3 统一计划已合入）；`benchmarks/metrology/metrics.json` 与 `round3/R3-G2-metrics-run.md` 在本次评审进行中由 R3-G2 落入工作区（暂存态），本报告的 E-8 判定基于该工件的实际内容核验，并在 §1 注明时点契约。

---

## 0. 结论（先说分数）

> **轴 A（规划完备度）= 4 / 5**
> **轴 B（实现完备度）= 2 / 5**
> 硬门 E-1/E-2/E-3/E-4 PASS；E-8 于评审时点 PASS（条件注记见 §1）。按 R2-F4 §3.5 放行判据（硬门全过 + A ≥ 4 + B ≥ 2），**Round 2 → Round 3 放行成立**；B=2 的附加义务（B=3 缺口逐条进派工单）已由 `round3/DISPATCH.md` 实际承接（R3-O1/O2 硬化、R3-G2 metrics、R3-G3 CI）。
>
> **诚实声明（不可省略）**：本项目**没有 VIC 级 GUI**，没有采集（VIC-Snap 对标）、没有实时（VIC-Gauge 对标）、没有 GPU 实测吞吐、从未与 VIC 同机对比。R2-F1 §2 的超越判定公式（A 组 6/6 + B 组 ≥4/6 + C 组 3/3）**当前没有任何一项进入可判定状态**——A1–A6 需要 Challenge 数据实测（尚未缓存，见 R2-F1 §4 G10），B/C 组需要全链工程。现有成果是**可审计的测量链地基**，不是可对外宣称"超越 VIC"的产品。两轴分数按 R2-F4 §3.1 禁止折算、并列上报。

---

## 1. E 系列存在性门判定（逐项证据路径）

| 门 | 判定 | 证据路径与实测 | 注记 |
|----|------|----------------|------|
| E-1 冲突裁决 | **PASS** | `round2/R2-F1-sota-reconciliation.md`（RUL-01…08 索引在 §0）；`MASTER_PLAN.md` L25 起"ADR 裁决"节；吞吐统一至 G2 协议（RUL-03 冻结目标表） | 硬门 |
| E-2 许可证 ADR | **PASS** | `round2/R2-G1-license-adr.md`（ADR-LIC-001）：Apache-2.0 内核 + open-core 边界 + OpenCorr 零复用 + GPU 闭源库禁用；§5 显微镜 FTO 检索清单（含 US7133570B1 状态记录、零实现声明） | 硬门 |
| E-3 核心代码 | **PASS** | `src/hl3/correlate/icgn.py`：CPU float64 一阶 IC-GN，ZNSSD + 预滤波三次 B 样条插值，模块 docstring 明确"Only NumPy is required. No GPU, no external DIC code"；`pyproject.toml` L13 声明 Apache-2.0；87 项测试通过即证明可 import | 硬门。整改项：`correlate/stereo/capture` 源文件缺 `SPDX-License-Identifier` 头（仅 `src/hl3/io/*` 有），违 M2，见 §5 |
| E-4 单元测试 | **PASS** | 本人复跑 `python3 -m pytest tests src/tests -q` → **87 passed, 0 failed, 0 skipped（7.37 s，本机 4 vCPU）**；契约覆盖齐：ICGN 收敛（`tests/test_icgn_synth.py` L204 `test_subpixel_translation_recovered`、L224 `test_subpixel_phase_sweep`）、ZNSSD 增益/偏置不变性（L259 `test_invariant_to_gain_and_offset`）、合成平移已知真值（L345 `test_matches_round1_generator`） | 硬门。h5py 3.16.0 已装，HDF5 测试实跑非 skip |
| E-5 立体轻量实现 | **PASS（实现档）** | `src/hl3/stereo/calibrate.py` + `triangulate.py`（合成针孔立体台 + 线性重投影标定 + 最优三角化，闭环实测入 metrics.json：0.02 px 匹配噪声下 3D RMS ≈ 4.90 µm）；`tests/test_stereo_synth.py` 32 项测试在 87 项内全绿；档位在 `round2/R2-O2-stereo-impl.md` 声明 | `src/` 中显微镜仅出现于"明确不做"声明注释与 schema 枚举槽位（`hdf5_schema.py` L298/L310 `stereo_microscope` → None），零实现，符合 RUL-04 与 E-5 禁令 |
| E-6 HDF5 schema | **PASS（带注记）** | `docs/schema-hdf5.md`：版本 `1.0.0-draft.2`（L5）、状态与冻结条件声明（L8、§12.1 L512–521）、组/数据集/属性表全量、GPG 报告字段落位（`@subset_px` L327、`@vsg_px` 必填 L376–386、形函数/插值/图像哈希各节）；CC-BY-4.0 头 L1 | 注记：**1.0 尚未冻结**（draft.2），冻结评审按 R2-F1 §4 G6 排 Round 3/后续；这是 B=3 未达的条款之一，不是 E-6 缺失 |
| E-7 仓库骨架 | **PASS** | `pyproject.toml` + `src/hl3/{correlate,stereo,io,capture}` 目录树与 `round2/R2-O3-schema-tree.md` 一致；无 GUI 目录占位 | — |
| E-8 基准 metrics.json | **PASS（时点注记）** | `benchmarks/metrology/metrics.json`（schema `hl3.metrology.metrics.v1`）：ICGN 合成平移 `mean_absolute_error_px = 8.08e-4`、bias(u/v) = +4.38e-4 / −2.09e-4 px，`status: "pass"` 由脚本按 `regression_limits`（<0.005 px、有效率 1.0）判定非手填；噪声底 σ_u 全表（`noise_floor_stub.results`）；立体三角化 4.897 µm RMS；每条记录带 subset/step/插值/形函数/seed 与源码 blob 哈希 | 硬门。**三条注记**：① 本评审开始时该文件不存在（R2-G2 数字只写 `/tmp` 与 markdown），属 Round 3 补硬门动作，恰为 R2-F4 §1"硬门 FAIL → Round 3 先补再评分"的规定路径；② 若 R3-G2 的提交最终未落 git，本项按 fail-closed 回退 FAIL、轴 B 降为 1；③ 插值 S 曲线峰峰值未以数值入 JSON（仅骨架脚本哈希 + R2-G2 报告表格），建议补录，见 §5 |
| E-9 基准脚本 | **PASS** | `round1/scripts/synth_speckle.py` + `round2/scripts/{interpolation_scurve,noise_floor_stub}.py`；**本人复跑验证**：`noise_floor_stub.py`（文档命令、seed 20260828）σ=1 档 u pooled std = 0.0017820801… px，与 R2-G2 报告 0.00178208 逐位一致，确定性差异 = 0，满足"确定性模式应为 0" | — |
| E-10 CI / 边界探针 | **FAIL（整改项，非硬门）** | 已有部分：`.github/workflows/ci.yml` CPU-only（`CUDA_VISIBLE_DEVICES=""`）、装 h5py、双测试路径 `pytest -q tests src/tests`（commit `d967d40` 已修 Round 2 的收集漏洞）、全套 <10 s 远低于 5 min；`round2/R2-G3-ci-mock.md` 存在 | **未达条款**：R2-F4 §2 法务扫描未作为 CI 步骤声明（ci.yml 无扫描 step，R2-G3 报告亦无）；`legal/scan-allowlist.txt` 不存在。按 fail-closed 记 FAIL 入整改清单，移交 R3-F2 / R3-G3 |
| E-11 统一 PRD | **PASS** | `round2/R2-F3-prd-surpass.md`：楔子→Gate 编号映射表（L91–127，G2D-*/G3D-*/GP-* 列齐）；§6"MVP 明确不做"清单，L176–177 明文"采集层 MVP 仅文件序列导入 + Mock""实时 MVP 无任何实时路径" | — |
| E-12 交叉审计 | **PASS** | `round2/R2-F2-cross-audit.md`：R1 十份报告不一致/缺口/无证据论断分类台账（P0/P1/P2 严重度 + Owner），与 R2-F1 裁决对读一致 | — |

**硬门判决**：E-1/E-2/E-3/E-4/E-8 = 5/5 PASS（E-8 带 §1 时点注记）。E-10 的 FAIL 为非硬门整改项，按 R2-F4 §1 压低实现分处理（已体现在 B=2 而非 3）。

**L 系列（法务扫描）**：属 R3-F2 独占职责，本报告不越权出全量判定；本人抽查所见——`src/`、`tests/` 无显微镜实现（L-7 实质合规）、无 VIC 二进制迹象、无 OpenCorr 拷贝迹象、metrics 与各报告吞吐表述均挂协议（L-6 抽查合规）；但 **allowlist 基建缺失**（上表 E-10 注记）须由 R3-F2 落地后 L-2 才能按 fail-closed 走通。

---

## 2. 轴 A：规划完备度 = **4**（逐档核对，就低不就高）

| 档 | 条款 | 判定 | 证据路径 |
|----|------|------|----------|
| 2 | 7 条 R1 冲突唯一裁决；MASTER_PLAN 单一有效；许可证 ADR 存在 | 满足 | `round2/R2-F1-sota-reconciliation.md` §0 RUL-01…08；`MASTER_PLAN.md` L25 ADR 节；`round2/R2-G1-license-adr.md` |
| 3 | 每条楔子映射编号 Gate；数字全部带协议/口径；基准协议与 Gate 台账打通 | 满足 | `round2/R2-F3-prd-surpass.md` L91–127 映射表；RUL-03 冻结吞吐目标表 + 禁止清单（R2-F1 §1/§2）；`round1/R1-G2` 协议被 RUL-03 定为唯一口径 |
| 4 | Challenge 回归协议、UQ 校准、GPG 映射、法务红线互引无矛盾；交叉审计无遗留高危冲突；**每个不可本地验证项都有后续验证窗口与责任方** | 满足 | Challenge：G2 §5 + R2-F1 §4 G10（下载预算与 SHA-256 manifest 计划）；UQ：C2 KPI（R2-F1 §2）；GPG：R2-F3 §3 映射 + B5；法务：LEGAL.md + L 系列 + FRZ-06；交叉审计：`round2/R2-F2-cross-audit.md`；不可验证项闭合路径：`round2/R2-F4-r3-gates.md` §4 GAP-1…6 每条列"后续合法闭合路径"（用户持证 Windows 走查、外部 GPU 基准机、下届 Challenge 公开排名、法务 FTO 通道）；`MASTER_PLAN.md` L44–55 FRZ-01…14 冻结清单（R3-F3）再度互引 |
| 5 | 每 Gate 有 claims-to-evidence 追踪表 + 最小复现命令；风险登记逐条缓解状态；第三方干净克隆走查通过 | **不满足 → 取 4** | 缺失明细：无逐 Gate 的 claims→evidence 追踪表工件（metrics.json 覆盖 3 个 Gate 的雏形，不是全量表）；R1 风险登记 R1–R10 无逐条缓解状态跟踪文档；无第三方（或独立子代理扮演的第三方）干净克隆走查记录 |

---

## 3. 轴 B：实现完备度 = **2**（逐档核对，就低不就高）

| 档 | 条款 | 判定 | 证据路径 |
|----|------|------|----------|
| 2 | 内核干净克隆可装可跑；单测全绿（E-3/E-4）；合成平移 bias 落盘 metrics.json 且量级达 0.01 px 级（E-8） | **满足** | pytest 87 passed（本人复跑，7.37 s）；`benchmarks/metrology/metrics.json` → `icgn_synthetic_translation.metrics.mean_absolute_error_px = 8.08e-4 px`（优于 0.01 px 量级一个数量级，脚本判 pass）；`pyproject.toml` 可装 |
| 3 | 立体标定+三角化闭环（满足，E-5）；**HDF5 schema 冻结**且内核输出遵循之；噪声底 + S 曲线基准**入 CI** 且可复跑 | **不满足 → 取 2** | 未达条款明细：① schema 停在 `1.0.0-draft.2` 未冻结（`docs/schema-hdf5.md` L8、§12.1，冻结评审按 G6 后置——设计决定而非事故，但条款就是条款）；② 噪声底/S 曲线基准脚本未作为 CI 步骤（ci.yml 仅 pytest；S 曲线仅由 `test_subpixel_phase_sweep` 部分覆盖）；③ S 曲线峰峰值数值未入 metrics.json（§1 E-8 注记③） |
| 4–5 | 全链 headless / GUI+实时+相机 | 不适用 | 超出三轮任务范围（R2-F4 §0 结构性论证 + §3.3 明文"不得因未达成而追责"）；若有任何报告自评 B ≥ 4，应触发 L-6 声明造假审查——本轮未发现此类自评 |

与 `ROUND2_BRIEF.md` §3 自评"B ≈ 2.5"的关系：量表只有整数档且就低不就高（R2-F4 §3.4 第 2 条），故正式记 **2**；2→3 的三条缺口已在上表列明，且 `round3/DISPATCH.md` 已把它们分派给 R3-G2（metrics 扩充）、R3-G3（CI）、R3-O3（docs 对齐），满足 §3.5 "B=2 附加义务"。

---

## 4. 诚实边界（对外表述必须附带）

1. **无 VIC 级 GUI**——不是"还差一点"，是零：无交互式可视化、无向导工作流、无 iris 级动画（GAP-1）。我们也从未合法见过 VIC 的 UI，因此连"对齐"的基准都不存在（RUL-06）。
2. 无采集与实时链路（GAP-2）；GPU 吞吐目标全部是协议绑定的纸面目标，无一实测（GAP-3，RUL-03 禁止任何"比 VIC 快"表述）。
3. 精度成绩全部来自**自产合成数据**（合成平移、合成立体台、合成噪声底）；iDICs Challenge 实测为零（G10 未缓存），故 A1–A6 无一进入判定状态。
4. 显微镜/SEM 畸变维持零实现直至书面 FTO（FRZ-06）；Windows/macOS 一致性未验证（GAP-6）。
5. 立体闭环数字（4.90 µm RMS）是**已知精确标定的针孔几何**结果，metrics.json 自带 scope_note 声明"不是端到端 Stereo-DIC 或 Challenge 成绩"——引用时不得去掉该限定。

## 5. 整改清单（不阻塞放行，进 Round 3 收口）

| # | 项 | 建议 Owner |
|---|----|-----------|
| R3FIX-1 | 法务扫描步骤入 CI + 建 `legal/scan-allowlist.txt`（E-10 未达条款；L-2 白名单基建） | R3-F2 / R3-G3 |
| R3FIX-2 | `src/hl3/correlate/*`、`stereo/*`、`capture/*`、`__init__.py` 补 `SPDX-License-Identifier: Apache-2.0` 头（M2） | R3-O1/O2 |
| R3FIX-3 | 插值 S 曲线峰峰值以数值 + pass/xfail 判定入 metrics.json（Keys 双三次 P-P 0.0289–0.0386 px 未过 0.02 px 门须按 RUL-07 以 xfail 登记，不得删记录） | R3-G2 |
| R3FIX-4 | E-8 工件确认随 R3-G2 提交落 git（本报告 §1 时点契约：未落地则 E-8 回退 FAIL、B 降 1） | R3-G2 / 父调度器 |
| R3FIX-5 | schema 0.x→1.0 冻结评审排期留痕（G6） | R3-O3 / 后续 |

## 6. 程序性声明

按 R2-F4 §3.4 第 3 条，本报告是**单人评分**；协议要求父调度器另指一名互不通气的评审独立打分，两者分差 ≥ 2 档须书面对质。本人自查合规：每个分值判定均附工件路径与实测记录（§3.4 第 1 条）；无内插分（第 2 条）；自评未越过预期区间 A ∈ [4,5]、B ∈ [2,3]（第 4 条）。

**最终上报：A = 4，B = 2。**
