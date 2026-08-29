ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR4-F4 · 超越公式 A/B/C 复评：对照 S4 实际代码与测试逐项判分

- **子代理**：IR4-F4（fable，`claude-fable-5-thinking-xhigh`）
- **日期**：2026-08-28
- **任务**：把 `round3/R3-F4-beyond-vic-roadmap.md` §1 引用的超越公式（R2-F1 冻结：A 组 6 项全 PASS ＋ B 组 ≥4/6 ＋ C 组全 PASS），按派工给定的 15 项清单，对照**当前工作树里的真实代码与真实测试**逐项复评。
- **效力**：低于 `LEGAL.md` → RUL/ADR-LIC-001 → R2-F1 Gate 表 → G2 协议。本文不新设阈值、不改判据，只做证据核对。
- **判定纪律**：fail-closed。证据 = 仓库内文件 + 具体测试名 + 可复跑命令；没有证据的项一律不给 PASS。一切 VIC 能力表述均为"厂商公开宣传值，未独立验证"（RUL-03/06）。

---

## 0. 本次实测基线（判分依据，全部今日复跑）

| 项 | 实测值 |
|----|--------|
| 复跑命令 | `PYTHONPATH=src python3 -m pytest -q tests src/tests` |
| 结果 | **700 passed in 46.37 s**（0 failed / 0 skipped / 0 xfail） |
| 环境 | Python 3.12.3，Linux 6.12.94+ x86_64，CPU-only；numpy / h5py / matplotlib 3.11.1 可用，tkinter 缺失 |
| git 状态 | 分支 `cursor/ir3-o3-fea-gui-6b3c`，HEAD = `b141aad`（S2/S3 收口，689 tests）；**S4 新代码（`src/hl3/{cli/run.py,viz/,fea/,gui/}`、对应测试）仍是工作树未提交/未跟踪状态** |
| metrics.json | `benchmarks/metrology/metrics.json` 停留在 Round 2 修订（`source_revision = 1bcc1de…`，test_suite 记录 87 passed）——**未随 S1–S4 刷新** |

两个口径声明，先说清楚再打分：

1. **派工清单 ≠ R2-F1 冻结表。** R2-F1 的 B 组是 B1 吞吐、B2 实时、B3 TTFR、B4 跨平台、B5 GPG lint、B6 FEA；本次清单把 B 组换成了「cross-platform, Python, UQ, FEA, OSS schema, Challenge-ready」，C 组把 C1（可复现性）写成了「Challenge」。本文**按给定清单判分**，但 §4 同时按 R2-F1 原表校验——换清单不能换判定权，正式判定只认冻结表（IR3-F1 §3.1 已登记原表口径下 B 组 0/6）。
2. **A 组"parity"按能力面判**（该能力存在、正确、有测试），R2-F1 的正式计量门槛（噪声下 σ_u、正式 S 曲线口径、100 µε 噪声底、Challenge/标定实测）另行标注——能力面 PASS 不等于计量门已关。

---

## 1. A 组 · 精度平权 6 项

| # | 项 | 判定 | 一句话理由 |
|---|-----|------|-----------|
| A-1 | FFT-CC 初值 | **PASS** | 真 ZNCC 的 FFT 整像素搜索 + 种子进 ICGN（HYBRID 路径），有直接测试 |
| A-2 | IC-GN 一阶 + 二阶 | **PASS** | 6 参与 12 参两个求解器都存在、共享一个核，二阶有 44 条专项测试 |
| A-3 | 立体 + 三角化 | **PASS（限合成域）** | 匹配→三角化→U/V/W 全链 241 条测试；但纯针孔、合成标定、一阶匹配 |
| A-4 | 应变 4 张量 | **PASS** | engineering / Green-Lagrange / Euler-Almansi / Hencky（+logarithmic 别名）全在，刚体旋转零应变有精确断言 |
| A-5 | VSG | **PASS** | GPG Eq. 7.2 全树唯一实现 + "无 VSG 不出应变"强制 |
| A-6 | HDF5 schema | **PARTIAL** | 实现、验证器、往返测试全绿；但版本停在 `1.0.0-draft.2`，且产品链不产 `.hl3` |

### A-1 FFT-CC —— PASS

- **代码**：`src/hl3/correlate/icgn.py::integer_search_fftcc`（L448–539）——`rfft2` 互相关 + 积分图（summed-area table）把原始相关归一成**真 ZNCC**；平坦窗逐候选剔除；`ICGNParams.search_radius > 0` 时自动作为 ICGN 种子（`_resolve_initial_guess`，L1290–1305），即路线图说的"FFT-CC 初值 + HYBRID 路径"。
- **测试**：`tests/test_icgn_synth.py::test_integer_search_hits_exact_shift`、`::test_large_displacement_needs_fftcc_seed`（证明无种子必失败、有种子必收敛，即种子是被真实消费的）。
- **无缺口**。按路线图定义（初值路径），此项闭合。

### A-2 IC-GN 一阶 + 二阶 —— PASS

- **代码**：`icgn_first_order` / `icgn_second_order` / `icgn`（按 `shape_order` 分发），同一个 `_icgn` 核。二阶用 6×6 单项式矩阵表示 warp 群（Gao et al. 2015 路线，`warp_matrix_second_order` L709），`compose_inverse_second_order` 带退化增量拒绝。插值为预滤波双三次 B 样条（S 曲线达标的那条路线，Keys 双三次已按 R2-G2 弃用）。
- **测试**：`tests/test_icgn_second.py`（44 条），含 `test_second_order_recovers_a_quadratic_warp_far_better_than_first_order`、`test_second_order_recovers_the_curvature_terms`、`test_the_composition_is_exactly_closed_on_the_affine_subgroup`；`tests/test_icgn_synth.py::test_subpixel_translation_recovered`（metrics.json 存档：196 POI，MAE = 8.08×10⁻⁴ px，RMSE = 1.10×10⁻³ px）、`::test_subpixel_phase_sweep`（每相位 |bias| < 0.01 px 锁进测试；IR4 用户总结引用的实测峰峰值 1.73×10⁻³ px）。
- **诚实标注**：立体匹配侧 `StereoMatchParams` **拒绝** `shape_order != 1`（`src/hl3/stereo/match.py` docstring 明示 deferred）——二阶只在 2D 链可用，立体链未接线。R2-F1 正式 A1/A2 门（带噪 σ_u ≤ 0.01 px、≥3 套散斑）未按正式协议出成绩单。

### A-3 立体 + 三角化 —— PASS（限合成域）

- **代码**：`src/hl3/stereo/match.py`（平面视差种子 + ICGN 精化 + 极线质量门，F 阵永远来自标定而非拟合）、`src/hl3/stereo/triangulate.py`（中点 / DLT / Sampson / 非线性四档 + 逐点 3×3 协方差 + 手性门）、`src/hl3/stereo/calibrate.py`（合成台架 + DLT resection）、`src/hl3/pipeline/dic3d.py`（参考帧立体匹配一次 → 双视时序跟踪 → 三角化 → 世界系 U/V/W）。
- **测试**：`tests/test_stereo_match.py`（50 条，含 `test_match_recovers_the_true_correspondence`、`test_a_baseline_error_passes_the_gate_and_still_ruins_the_depth`——连"极线门看不见什么"都测了）、`tests/test_stereo_synth.py`（71 条，含 `test_predicted_covariance_matches_monte_carlo_spread`）、`tests/test_pipeline_3d.py`（120 条，刚体平移平面全链）。metrics.json 存档：0.02 px/相机噪声 → 4.90 µm 3D RMS，**自标 `measured-no-formal-gate`**。
- **诚实标注**（四条，缺一不可）：① 纯针孔 L0，零畸变模型；② 标定 = 已知 3D 点的 DLT resection，**不是 Zhang 平面标定**，无光束法平差、无 Σ_cal（A6 门连续三轮无主，IR3-F1 §3.2）；③ 立体匹配仅一阶形函数；④ 曲面 3D 应变**显式关闭**（`dic3d.py` L280–292 强制 `StrainMode.OFF`）。全部数字来自合成孪生，零实测、零 Challenge 数据。立体精度上限在标定（R1-F4 R-01），而标定恰是本链最薄的一环。

### A-4 应变 4 张量 —— PASS

- **代码**：`src/hl3/strain/tensors.py`——`engineering`、`green_lagrange`、`euler_almansi`、`hencky`（`logarithmic` 为 schema 别名），外加主应变、γ_max、von Mises、Tresca、面积膨胀、极分解转角；闭式 2×2 谱分解保 NaN 传播。`strain_tensor()` 名称与 schema `@tensor` 词表逐一对应。
- **测试**：`tests/test_strain.py`（120 条）：`test_uniform_strain_matches_the_closed_form_tensor`（逐张量）、`test_rigid_rotation_is_zero_for_every_finite_strain_measure`（有限应变族对刚体旋转**精确**归零）、`test_engineering_strain_under_rotation_is_the_documented_artefact`（-θ²/2 伪应变按文档值验证）、`test_logarithmic_is_the_schema_alias_of_hencky`。
- **无缺口**（能力面）。正式 A4 计量门（≤100 µε 噪声底成绩单）未按正式协议出档，但 `test_larger_windows_lower_the_strain_noise_floor` 已锁定趋势。

### A-5 VSG —— PASS

- **代码**：`src/hl3/strain/vsg.py`——GPG Eq. (7.2)，算式本体在 `hl3.io.hdf5_schema.vsg_size_px` **全树只有一份**（防报告值与存档 `@vsg_px` 漂移）；后置滤波窗 max/cascade 两种口径显式可选、默认 GPG 口径；mm 换算与逆算窗口齐全。
- **测试**：`tests/test_strain.py::test_vsg_matches_gpg_equation_7_2`、`::test_the_vsg_formula_has_exactly_one_implementation`、`::test_compute_strain_cannot_be_called_without_a_vsg_size`（**无 VSG 记账不允许出应变**）；`tests/test_pipeline_2d.py::test_vsg_follows_the_gpg_formula`、`::test_config_reports_its_own_vsg`。
- **小缺口**：`hl3.viz` 出图未随图标注 VSG（IR3-F1 门 G-S4-VIZ-3 的要求，`src/hl3/viz/plot2d.py` 内无 vsg 引用，`tests/test_viz.py` 仅 1 条内建后端测试）。记账层闭合、出图层未闭合。

### A-6 HDF5 schema —— PARTIAL

- **已有**：`src/hl3/io/hdf5_schema.py`（常量/位域/canonical JSON/`config_hash`/`input_hash`/写读/`validate_file`，标准库-only 分层，h5py 缺失 fail-soft）+ `docs/schema-hdf5.md`（附录 D：**纯 h5py 最小读取示例，无需 HL3**）+ `python -m hl3.cli.validate`（退出码语义冻结）。测试：`tests/test_hdf5_schema.py`（23 条：`test_roundtrip_matches_analytic_solution`、`test_writer_is_deterministic`、`test_validator_catches_illegal_files`、`test_reader_rejects_future_major_version`）+ `tests/test_validate.py`（16 条）。
- **缺口（判 PARTIAL 的原因）**：① 版本仍 `1.0.0-draft.2`（`hdf5_schema.py` L76，注释明示"不承诺兼容"），G6 冻结评审无主（IR3-F1 §3.2）；② **产品链与 schema 未接通**——`hl3.pipeline.dic2d` 不 import `hl3.io`，`hl3 run` 只出 `.npy/.npz` + JSON（`src/hl3/cli/run.py` docstring），全仓库唯一写 `.hl3` 的入口是合成样例 `write_synthetic_hl3`。schema 是真的，"schema 是产品输出格式"目前不是。

**A 组小结：5 PASS + 1 PARTIAL，"A 组 6 项全 PASS"不成立。**且按 R2-F1 正式计量口径（Challenge 数据、Zhang 标定、正式成绩单），A 组实际更远。

---

## 2. B 组 · 显著优势 6 项（给定清单口径）

| # | 项 | 判定 | 一句话理由 |
|---|-----|------|-----------|
| B-1 | cross-platform | **FAIL** | CI 仅 ubuntu-latest 单 job，零 Windows/macOS 运行证据 |
| B-2 | Python | **PASS** | 全链 Python API + `hl3` CLI，700 条测试全走 API |
| B-3 | UQ | **PARTIAL** | 传播链正确且 MC 验证过；但覆盖率门、Σ_cal、默认开启都没有 |
| B-4 | FEA | **PARTIAL** | 双向投影原语扎实；B6 四要素只有 1/4 |
| B-5 | OSS schema | **PASS**（draft 前提） | 开放、可验证、纯 h5py 可读；但只能宣称"草案" |
| B-6 | Challenge-ready | **FAIL** | 仓库零 Challenge 数据、零成绩、零复现包 |

### B-1 cross-platform —— FAIL

- **有的**：纯 Python + NumPy、零编译扩展（可移植性地基）；`pyproject.toml` 规范打包 + `hl3` console script。
- **没有的**：`.github/workflows/ci.yml` 只有一个 `runs-on: ubuntu-latest` job；`IR3-G3-ci.md` 白纸黑字"CI 仍 Linux CPU；未宣称三平台已绿"；IR3-F1 §3.1 登记 B4 **未派工**，"起步都谈不上完成"。零 Windows/macOS 实跑、零跨平台数值一致（<1e-6）对账、零安装器。`tests/test_env_guards.py` 反而是**政策性禁止** Windows runner（防 CI 变成 VIC 评估机），与"三平台已验证"是两回事。
- fail-closed 纪律下：**FAIL**。"portable by construction" 是论证，不是证据。

### B-2 Python —— PASS

- **代码**：全链皆一等 Python API——`hl3.correlate`（求解器/参数/状态码）、`hl3.pipeline.dic2d`（`Dic2DConfig`/`run_sequence`：capture 回放→相关→参考更新→应变，`_provenance` 参数快照）、`hl3.pipeline.dic3d`、`hl3.strain`、`hl3.uq`、`hl3.fea`、`hl3.viz.save_field`；`python -m hl3 doctor|run|validate`（`src/hl3/cli/__main__.py`），`pip install .` 可装。
- **测试**：700 条全部经 Python API；`tests/test_pipeline_2d.py::test_runs_are_bit_for_bit_reproducible`、`::test_mock_capture_sequence_recovers_the_integer_translations`（采集→相关→应变链）；`tests/test_cli_run.py::test_run_synthetic`（子进程全链）。
- **诚实标注**：无 `sweep`/`report` 子命令（S4 计划里有）；UQ 与出图未接进 pipeline/CLI 单调用；B3 TTFR **正式门 evaluable=false**（未发 PyPI、无录屏）。作为"全链可脚本化"这一项本身：PASS。对比表述只允许："HL3 全链可 Python 脚本化；VIC 公开叙事以桌面工作流为主（厂商公开资料，未独立验证）"。

### B-3 UQ —— PARTIAL

- **有的（数学是真的）**：段 A：核内 `Cov(p) = 2σ²H⁻¹`（`icgn.py` L1163–1173）；段 B/C/D：`src/hl3/uq/propagate.py`（段 C 对 PLS 线性算子**精确**、复用拟合器自己的 `_TERMS`/`_weights_1d`/`_REL_EPS`，段 D 冻结解析 Jacobian）；3D 侧 `triangulation_covariance`。四条假设 A1–A4 **注册在案**并随结果携带。
- **测试**：`tests/test_uq.py`（39 条）：`test_closed_form_anchor`（闭式解 1e-12）、`test_monte_carlo_ratio_is_within_the_gate_band`（**400 次 MC**，比值带 0.8–1.25，均值 ≈1.0±0.05）、`test_chain_from_the_kernel_covariance_to_strain_std`（核协方差→应变 σ 端到端）、`test_operator_is_the_fitters_own_operator`；`tests/test_icgn_synth.py::test_covariance_scales_with_noise`；`tests/test_stereo_synth.py::test_predicted_covariance_matches_monte_carlo_spread`。
- **缺的（对照 S3/C2 冻结门）**：① ≥1000 次 MC + **95% CI 实证覆盖率 ∈ [90%, 98%] 测试**——不存在；② 标定协方差 Σ_cal 接入——不存在（依赖没做的 A6 标定升级）；③ **默认开启**——`compute_covariance` 默认 False，pipeline/CLI 均不出 σ 场，"每个输出量默认带不确定度通道"未实现；④ 传播张量仅 engineering/green_lagrange；⑤ 已注册假设 A1（POI 独立）在常用 step<subset 配置下已被仓库内测量证实**系统性低估约 1.8×**（预测/实测 ≈ 0.55–0.58，IR4 用户总结引档）——假设是声明了的，但对外宣称"UQ 领先"时必须连这句一起说。

### B-4 FEA —— PARTIAL

- **有的**：`src/hl3/fea/project.py`（860 行）：`TriMesh` + `project_to_nodes` / `interpolate_at_points`，三种投影（barycentric 单调 / least_squares 一致（matrix-free CG）/ nearest 兜底），掉点/域外点全部计数不吞。测试：`tests/test_fea.py::test_constant_field_round_trip`、`::test_linear_field_least_squares` + `tests/test_s4_smoke.py`（假绿已消除：fea 包非空、导入即得 API）。
- **缺的（对照 B6 冻结定义四要素）**：① 网格文件导入（VTK/Exodus）——`fea/__init__.py` 自我声明"不导入网格文件"，IR3-O3 报告同（连 IR3-F1 放宽后的最小门 G-S4-FEA-2 VTK legacy ASCII 也没做）；② **同滤波链（等效 VSG）对比报告 + 归一化残差 z 判定**——`fea/__init__.py` 原文承认是"the next piece"；③ 实测边界条件导出（G-S4-FEA-5）——无；④ 开孔板案例单脚本——无；真实 FE 解算器输出——无（IR3-F1 已登记 evaluable=false）。四要素得一。**PARTIAL，且是弱 PARTIAL**。

### B-5 OSS schema —— PASS（draft 前提下）

- 证据同 A-6，外加许可证据：LICENSE = Apache-2.0、pyproject 声明、全源 SPDX 头（ADR-LIC-001 执行）；`tests/test_validate.py::test_output_is_byte_for_byte_reproducible`、`::test_command_reports_exactly_what_the_library_returns`（命令 = 库的忠实外壳，结构性单一事实源）。"第三方无 HL3 也能读"由 docs 附录 D + 标准库-only 分层 + 一致性样例只用内置过滤器三件事共同保障。
- **对外表述边界**：只能说"开放 schema **草案** + 参考实现 + 验证器"。宣称"稳定开放格式"要等 G6 冻结。作为对 `.z3d` 类专有格式的结构性差异化（公开资料口径），此项成立。

### B-6 Challenge-ready —— FAIL

- **事实**：仓库内零 Challenge 数据（IR3-F1 §3.2：A5 数据未下载，预算/派工均未安排）；零 MEI/Star 图/官方噪声底指标；零一键复现包；`benchmarks/metrology/metrics.json` 停在 Round 2 修订，其中 stereo 条目自标 `measured-no-formal-gate`、噪声底自标 `diagnostic-stub-no-formal-gate`。
- **已有的地基（不构成 ready）**：确定性（bit-for-bit 测试）、`config_hash`/`input_hash`、指标 schema `hl3.metrology.metrics.v1`、`tests/test_stereo_synth.py::test_stereo_error_budget_is_the_right_order_for_the_challenge_geometry`（Challenge 几何的误差量级自检）。这些是 S7 的入场材料，不是成绩。**FAIL**。

**B 组小结（给定清单口径）：2 PASS + 2 PARTIAL + 2 FAIL → 未达 ≥4/6。**

---

## 3. C 组 · 独有能力 3 项（给定清单口径）

| # | 项 | 判定 | 理由 |
|---|-----|------|------|
| C-1 | UQ | **PARTIAL** | 同 B-3：数学链 PASS，C2 冻结门三件套（≥1000 MC 覆盖率、Σ_cal、默认开启）缺三 |
| C-2 | Challenge | **FAIL** | 同 B-6。另注：R2-F1 原 C 组此位是 C1"可复现性"——若按原义判，同机确定性 + 参数快照 PASS，但异机复算差异报告无（单机环境，IR3-F1 §3.2 登记移交）→ 也只是 PARTIAL。两种读法都到不了 PASS |
| C-3 | OSS schema | **PASS**（draft 注记） | C3 三件套齐：schema 一致性测试套件（`tests/test_hdf5_schema.py`）+ `hl3 validate`（`tests/test_validate.py`）+ 纯 h5py 参考读取（docs 附录 D + 无 h5py 导入分层测试） |

**C 组小结：1 PASS + 1 PARTIAL + 1 FAIL → "C 组全 PASS"不成立。**

---

## 4. 公式判定

> 超越成立 ⇔ A 组 6 项全 PASS ＋ B 组 ≥4/6 PASS ＋ C 组全 PASS（R2-F1 §2 冻结）

| 条件 | 给定清单口径 | R2-F1 冻结原表口径 |
|------|-------------|-------------------|
| A 全 PASS | **否**（5 PASS + 1 PARTIAL；正式计量门更远） | 否（A3 Challenge、A5/A6 标定与实测全开） |
| B ≥ 4/6 | **否**（2/6） | 否（IR3-F1 登记 **0/6** 正式 PASS：B1/B2 未做，B3/B6 evaluable=false，B4/B5 未派工） |
| C 全 PASS | **否**（1/3） | 否（C1 异机复算缺、C2 覆盖率门缺、C3 draft） |

**三个条件全部不满足。超越公式在当前 S4 收口状态下不成立，也不接近成立。**给定清单比冻结表宽松（把最难的吞吐/实时换成了软件项），结论仍是不成立——这本身就是最有信息量的复评结果。附带程序性提醒：正式对外判定只能按 R2-F1 原表；用替换清单得出的任何"更好看"的分数不得进入对外叙事（RUL-08 纪律）。

另一条必须记录的证据链事实：**S4 的全部新代码目前是工作树未提交状态**（`git status`：`src/hl3/fea/`、`src/hl3/viz/`、`src/hl3/gui/`、`src/hl3/cli/run.py`、四个新测试文件均 untracked）。"仓库内工件"标准严格说尚未满足——S4 收口前必须先把代码落进 git 历史。

---

## 5. 诚实清单：我们赢在哪、输在哪（对外叙事只许连着一起引用）

### 5.1 有仓库内证据的真实优势（赢的部分）

1. **开放性**：Apache-2.0 全栈、机器可读 schema 镜像 + 验证器 + 纯 h5py 第三方可读、SPDX/SBOM 纪律。对手工程格式专有（公开资料）。这是结构性差异，不随版本消失。
2. **Linux / 无头**：整条链（相关→应变→UQ→出图→校验）在 Linux CPU 无头环境 46 秒跑完 700 条测试；无头出图不需要任何 GUI 工具链。VIC 公开分发形态为 Windows 桌面（厂商公开资料，未独立验证）。
3. **UQ 数学**：逐段可证明（段 C 精确）、假设逐条注册、独立 Monte Carlo 交叉验证、协方差从核 Hessian 免费获得的传播链，加 3D 三角化协方差。这块的**数学质量**是公开可审计的。但见 §2 B-3：默认化、覆盖率实证、Σ_cal、A1 低估 1.8× 都还压在桌上——"UQ 数学领先"成立，"UQ 产品领先"不成立。
4. **可审计与确定性**：bit-for-bit 重跑测试、九种失败状态码从不糊成数字、fail-closed 文化连"极线门看不见什么误差"都写进测试。这是复现包文化的地基，对手公开叙事无此形态（公开资料口径）。

### 5.2 结构性落后，且不因代码质量而改变（输的部分——一条都不许含糊）

1. **产品**：无安装器、无发布、未上 PyPI、schema 是草案、`hl3 run` 不产 `.hl3`、无报告系统、"15 分钟第一张带不确定度的云图"没有演示过。我们有一个研发内核，**不是一个产品**。
2. **相机与采集**：只有 Mock 生产者。零 GenICam、零实机、零同步、零标定采集助手。VIC-Snap 对标面为零（S6，硬件在环实验室是先决条件）。
3. **GUI**：`hl3.gui.viewer` 是骨架——本环境连 tkinter 都没有，viewer 明确不启动交互会话；AOI 类未接入计算 pipeline。iris 级可视化对标面为零（GAP-1，beta 用户回路不存在）。
4. **实时与振动**：VIC-Gauge 级点测、全场实时、振动/模态分析（厂商公开宣传能力，未独立验证）——对标面为零（S6/B2）。
5. **SEM / 显微镜**：零实现，且 GAP-5 法务 fail-closed——在书面 FTO 结论之前**永久不做**。这不是排期问题，是我们主动放弃的疆域，对外必须如实说。
6. **标定**：无 Zhang、无畸变模型、无实标定板检测、无 Σ_cal。Stereo Challenge 1.0 的公开结论是立体精度上限在标定——**对手最强的地方恰是我们最薄的地方**。
7. **GPU / 吞吐**：零（S5，外部基准机）。任何吞吐比较在满足 G2 §7.3 同机四条件前禁言（RUL-03）。
8. **品牌、支持组织、存量装机**：25 年 vs 0 年。组织与时间问题，代码无解（R3-F4 §5 原表照引）。

**一句话定位（沿 IR3-F1 §3.3，本文确认仍然成立）**：S4 交付的是无头研发内核的最小闭环，它在开放性、Linux 无头链与 UQ 数学上有真实且可审计的优势；它**不是 VIC 替代品**，超越公式三个条件今天一个都不满足。

---

## 6. 距离最近的可关缺口（按"纯软件、本环境可闭合"排序，供父调度器派工）

1. 提交 S4 工作树代码入 git（零成本，证据链前提）。
2. UQ 覆盖率门：≥1000 次 MC 的 95% CI 实证覆盖率测试（纯计算，C2 三缺一可关）。
3. `hl3 run` 产 `.hl3` + `validate` 自校（把 schema 从样例格式变成产品格式，同时救 A-6 与 B-5 的 draft 缺口）。
4. 三平台 CI 矩阵（GitHub Actions 加 windows/macos runner + 数值一致对账，B-1 从 FAIL 升 PARTIAL/PASS 的唯一路径）。
5. FEA 的 VTK legacy ASCII 导入 + 等效 VSG 对比报告 + BC 导出（B-4 补齐到最小链）。
6. 2D Challenge 精选子集下载 + manifest + 指标复跑（B-6/C-2 的第一步，需数据预算）。
7. Zhang 标定 + 畸变 + Σ_cal（A-3 的天花板项，工作量最大）。

*IR4-F4 完。本文只写入 `.agent_workspace/s1s4/IR4_F4_exceed_rescore.md`；引用键沿用 A1–A6/B1–B6/C1–C3、RUL-03/06/07/08、GAP-1/5/6、G6、S1–S8。*
