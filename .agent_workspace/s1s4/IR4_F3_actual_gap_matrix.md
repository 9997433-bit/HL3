ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR4-F3 — 实际差距矩阵（HL3 S4 已实现代码 vs 全竞品，36 行复评）

- **代理**：IR4-F3（fable，`claude-fable-5-thinking-xhigh`）
- **日期**：2026-08-28
- **本文件与 R1-F3 的区别**：R1-F3 的 HL3 列是**目标定位**（M/D/L）；本文件的 HL3 列是 **S4 时点 `src/hl3/` 树里真实存在的代码**。每行状态均以源文件为证据，不引用路线图承诺。
- **输入**：`.agent_workspace/round1/R1-F3-gap-matrix.md`（36 行框架与竞品列，原样继承）、`src/hl3/` 全树逐文件阅读、`research/vic_public_feature_baseline.md`、`benchmarks/metrology/metrics.json`（2026-08-28 实测：87 tests pass / 0 fail，纯 CPU）。
- **竞品列免责**：V2D/V3D/MID/GOM/EKO/OC/DICe 各列**未重新复核**，原样沿用 R1-F3 的公开资料评分（●=完整 ◐=部分 ○=未见 ？=不明），其脚注见 R1-F3 §2。本轮只重写 HL3 列。

## 0. 状态图例（HL3 NOW 列）

| 状态 | 判据 |
|------|------|
| **DONE** | 该能力在 `src/hl3/` 中有可运行、有测试的实现（哪怕是 CPU 参考级） |
| **PARTIAL** | 核心原语/子集已实现且可用，但用户可感知的完整功能缺关键环节 |
| **MISSING** | 计划内（R1 标 M 或 D）但代码里没有 |
| **LEGAL-BLOCKED** | 代码注释/规范明文因法律（专利清查）冻结，任何分支均禁止实现 |
| **WONT-V1** | R1 即定为 L（后置），代码里没有且本就不该有 |

判据纪律：**只按代码打分，不按 docstring 里的"未来工作"打分**。凡模块自述"deliberately not implemented / later work"的，一律不算已有。

## 1. 主矩阵（36 行）

> HL3 NOW 单元格 = 实际实现的一句话概括；状态列单值，供 §2 计数。

| # | 能力 | V2D | V3D | MID | GOM | EKO | OC | DICe | HL3 NOW（S4 实际） | 状态 |
|---|------|-----|-----|-----|-----|-----|----|------|--------------------|------|
| 1 | 2D 平面内相关（单相机） | ● | ○ | ● | ● | ● | ● | ● | CPU 参考级 IC-GN/ZNSSD 全链：一阶+二阶形函数、B 样条插值、FFT-CC 整像素初值、序列管线、CLI；87 项测试全过¹ | **DONE** |
| 2 | 立体 3D DIC（双目） | ○ | ● | ● | ● | ● | ● | ● | S2–S6 全链可跑（立体匹配→三角化→U/V/W→四向环闭合残差），但**纯针孔、零畸变模型、无真实标定**，只能吃外部给定的投影矩阵² | **PARTIAL** |
| 3 | 多相机拼接（>2 相机 / 360°） | ○ | ◐ | ◐ | ● | ● | ○ | ○ | 无多相机管线/拼接；仅 `triangulate_multiview_dlt`/`triangulate_nonlinear` 原语接受 N≥2 视图带权³ | **MISSING** |
| 4 | DVC 体相关（CT 体数据） | ○ | ○ | ○ | ○ | ◐ | ● | ○ | 无任何 3D 体素代码（R1 即定 L） | **WONT-V1** |
| 5 | 采集软件（VIC-Snap 类） | ◐ | ◐ | ◐ | ● | ○ | ○ | ○ | 仅 `CaptureSource` 协议 + `MockCapture` 合成源（确定性帧、时间戳、丢帧模拟）；无任何真实相机/GenICam/模拟量⁴ | **MISSING** |
| 6 | 实时点测量 / 虚拟引伸计 | ◐ | ◐ | ？ | ● | ○ | ○ | ○ | 无实时模式；`vsg.py` 明文把虚拟引伸计与 VSG 尺寸区分开且**未实现前者**；无 DAQ/模拟量输出 | **MISSING** |
| 7 | 全场实时相关 | ◐ | ◐ | ○ | ● | ○ | ◐ | ○ | 单线程纯 NumPy 逐点循环，无在线管线；`icgn.py` 自述"slow, readable reference" | **MISSING** |
| 8 | 出版级可视化（iris 类） | ● | ● | ◐ | ● | ◐ | ○ | ◐ | 场云图两后端（零依赖 PNG/PGM/PPM 写入器 + matplotlib 出 PNG/PDF/SVG）、发散色表、NaN 涂灰、整段序列统一标尺；无动画/视频/3D 渲染/等值线/交互报告⁵ | **PARTIAL** |
| 9 | Python 脚本 / API | ● | ● | ◐ | ● | ● | ◐ | ◐ | 产品本体即 Python 包：`pyproject.toml` 可 `pip install`、`hl3` console script、全层 importable、逐位确定性；无 GUI 依赖 | **DONE** |
| 10 | HDF5 / 开放自描述数据格式 | ● | ◐ | ◐ | ◐ | ◐ | ◐ | ◐ | schema 规范 `docs/schema-hdf5.md`（1.0.0-draft.2）+ 机器可读镜像 + `validate_file` + 参考读取器 + 规范化 JSON/哈希；但**管线结果尚未接入 .hl3 写入**（CLI 只出 .npz/.npy，写入器仅覆盖合成用例）⁶ | **PARTIAL** |
| 11 | FFT / FRF / ODS 振动分析 | ● | ● | ◐ | ◐ | ○ | ○ | ○ | 无（树内唯一 FFT 是相关初值搜索的 FFT-CC，与振动分析无关） | **MISSING** |
| 12 | FEA 导入与试验-仿真对比 | ◐ | ● | ● | ● | ● | ○ | ◐ | DIC↔FE 双向投影原语（P1 三角网格：barycentric/最小二乘 CG/nearest，落点定位与丢样计数）；**无网格文件导入器**（Abaqus/ANSYS/Exodus/VTK 都没有）、无 FEVAL 式同滤波链对比⁷ | **PARTIAL** |
| 13 | 虚拟应变片 VSG / 提取工具 | ● | ● | ● | ● | ● | ○ | ◐ | GPG Eq.(7.2) 唯一实现 + 反解（目标 VSG→窗口）+ `@vsg_px` 强制入库 + `with_window` 廉价窗口扫描 + 每点应变 σ；无"放置应变片提取"工具、无一键收敛曲线向导⁸ | **PARTIAL** |
| 14 | AOI 编辑器（多边形、孔洞、裂纹缝） | ● | ● | ● | ● | ● | ◐ | ◐ | `PolygonAOI`（JSON 存取 + 射线法点内测试）+ 任意 POI 点列；无 GUI 编辑器、无孔洞/多联通/裂纹缝 | **PARTIAL** |
| 15 | 刚体运动去除 / 坐标系变换 | ● | ● | ● | ● | ◐ | ○ | ◐ | `umeyama` 锁尺度刚体拟合（已导出、用于对齐误差分解）+ 每点 `rotation_angle(F)` + 旋转不变张量族；无面向位移场的一键去除工作流、无坐标系管理 | **PARTIAL** |
| 16 | 标记点跟踪（DMT 类） | ○ | ◐ | ◐ | ● | ○ | ○ | ● | 无 | **MISSING** |
| 17 | SEM / 显微 DIC（含畸变校正） | ● | ● | ◐ | ？ | ○ | ○ | ○ | 无；且立体显微非参数畸变层在 `stereo/{calibrate,match,triangulate}.py` 三处明文"任何分支禁止实现，直到书面专利清查意见（spec S10.4）存在" | **LEGAL-BLOCKED** |
| 18 | 红外热像融合 | ○ | ● | ◐ | ？ | ？ | ○ | ○ | 无 | **MISSING** |
| 19 | 批处理 / 无头 CLI | ● | ◐ | ● | ◐ | ◐ | ● | ● | `python -m hl3 doctor/run/validate`：无头、退出码 0/1/2、确定性 JSON 摘要、`--synthetic` 自带冒烟、Linux CI 实跑；3D 暂无子命令（走库 API）⁹ | **DONE** |
| 20 | 模板化报告 | ● | ● | ◐ | ● | ◐ | ○ | ○ | 无（CLI JSON 摘要是机器输出，不是报告模板） | **MISSING** |
| 21 | 暗色主题 | ● | ？ | ？ | ？ | ？ | ○ | ○ | 无 GUI，故无主题（`gui/viewer.py` 仅是依赖检查桩） | **MISSING** |
| 22 | 浮动 / 网络许可（许可摩擦） | ◐ | ● | ？ | ● | ◐ | ● | ● | Apache-2.0（LICENSE + pyproject + 27 个 SPDX 头）：零许可摩擦，与 OC/DICe 同口径得分；商业浮动许可基础设施不存在（开源形态也不需要）¹⁰ | **DONE** |
| 23 | Linux / macOS 分析端 | ○ | ○ | ○ | ○ | ○ | ● | ● | 纯 Python+NumPy，无平台特定代码；本轮全部实测在 Linux 完成，`doctor` 报告平台信息 | **DONE** |
| 24 | 不确定度量化 UQ | ◐ | ◐ | ● | ◐ | ◐ | ◐ | ◐ | 链 A–D 已通：ICGN Hessian→Cov(p)→位移方差→PLS **精确**线性传播→应变分量 σ（假设 A1–A4 注册随行）；三角化 3×3 位置协方差 + 质量门；缺噪声底板向导、参数推荐、Σ_cal、系统误差项¹¹ | **PARTIAL** |
| 25 | 全局 FE-DIC | ○ | ○ | ○ | ○ | ● | ○ | ● | 无（纯局部 subset 路线；FEA 投影属后处理） | **MISSING** |
| 26 | 深度学习匹配 | ○ | ○ | ○ | ○ | ○ | ○ | ○ | 无（R1 排期即 V2） | **WONT-V1** |
| 27 | 插件市场 / 生态 | ○ | ○ | ○ | ◐ | ○ | ○ | ○ | 无插件协议/索引；仅有内部后端缝（`resolve_strain_backend`/`resolve_match_backend` 可注入 callable，schema 预留 PLUGIN 位域） | **MISSING** |
| 28 | 合成图像生成 / 虚拟试验（FEDEF 类） | ○ | ○ | ● | ○ | ◐ | ○ | ◐ | 测试级合成基建已在用：`MockCapture` 散斑流、过采样 Fourier 平移散斑（计量测试）、合成立体场景全家桶（`synth_*` + 噪声注入 + 闭环误差分解）、HDF5 `SyntheticSpec` 解析真值用例；**无**面向用户的"FEA 位移场→已知真值散斑图"渲染器¹² | **PARTIAL** |
| 29 | 材料参数辨识（VFM / FEMU） | ○ | ○ | ● | ○ | ◐ | ○ | ○ | 无（R1 即定 L） | **WONT-V1** |
| 30 | 标定工具链（板 + 独立标定 + 质量诊断） | ● | ● | ● | ● | ● | ◐ | ◐ | **不能标定真实相机**：只有合成闭环测试台（已知 3D-2D 对应的 DLT resection + K/R/t 分解 + 位姿/重建误差分解）；`calibrate.py` 明文"Not Zhang's method"，无角点检测、无畸变、无 BA¹³ | **MISSING** |
| 31 | 自动种子 / 起点检测 | ● | ● | ◐ | ● | ◐ | ◐ | ◐ | 多路种子已实现：FFT-CC 整像素搜索（带平坦度门）、立体名义平面视差种子、内置极线深度扫描粗搜、时序 PREV_FRAME 传递；失败给 `NO_INITIAL_GUESS` 状态码；无特征匹配兜底、无断帧自动重定位 | **PARTIAL** |
| 32 | 大变形 / 不连续处理 | ◐ | ◐ | ◐ | ◐ | ◐ | ◐ | ◐ | 增量参考更新（INCREMENTAL 按中位 ZNCC 触发 / EVERY_N）+ 跨参考 warp 复合回原参考；二阶形函数在内核可用但 2D 管线只接一阶、立体匹配明文拒绝二阶；无裂纹/COD 工具¹⁴ | **PARTIAL** |
| 33 | GPU 加速相关器 | ○ | ○ | ？ | ？ | ？ | ● | ○ | 无（`metrics.json` 记录 `gpu_used: false`；内核自述 GPU 后端为 future work 且须逐位复现 CPU 结果） | **MISSING** |
| 34 | 高速 / 超高速动态 | ◐ | ● | ◐ | ● | ◐ | ◐ | ◐ | 无高速相机 SDK、无相位触发/峰谷采样；管线能吃任意帧序列但无任何高速专属能力 | **MISSING** |
| 35 | 实时数据流 API（SCPI / gRPC） | ◐ | ◐ | ○ | ● | ○ | ○ | ○ | 无 | **MISSING** |
| 36 | 开源内核 / 计量可溯源到源码 | ○ | ○ | ○ | ○ | ○ | ● | ● | 全树 Apache-2.0 源码即规范实现：逐位确定性写入 docstring 契约、87 项测试断言数值、`metrics.json` 钉死源码 blob 哈希与复现命令 | **DONE** |

**证据脚注（全部指向树内实物）**

1. `correlate/icgn.py`（一阶 6 参 + 二阶 12 参 IC-GN、B 样条预滤波插值、FFT-CC、条件数/平坦度守卫、状态码、可选 Cov(p)）；`pipeline/dic2d.py`（序列编排）；`cli/run.py`；`benchmarks/metrology/metrics.json`：87 passed / 0 failed / 0 skipped，静图噪声底板 stub 在 σ=1 灰度时 pooled_std ≈ 0.0018 px（标注 diagnostic-stub，非产品级 ICGN 指标）。
2. `stereo/match.py`（平面视差种子 + IC-GN 精修 + Sampson 门）、`stereo/triangulate.py`（四档三角化 + 协方差 + 质量门）、`pipeline/dic3d.py`（四向环闭合、RejectReason 分类）。三个模块同声明：零镜头畸变（纯 L0 针孔）、一阶形函数 only（match 层）；`metrics.json` 的立体项标注 "exact synthetic pinhole cameras… not an end-to-end Stereo-DIC or Challenge score"。3D 表面应变未实现（`dic3d.temporal_config` 强制 `StrainMode.OFF` 并说明 S7 是未做的世界系工作）。
3. `stereo/triangulate.py::triangulate_multiview_dlt / triangulate_nonlinear(weights=…)`；`calibrate.py::_study_multiview` 仅是三相机合成对照实验。
4. `capture/mock.py`：`np.roll` 平移合成散斑 + 噪声 + 时间戳抖动 + 丢帧；模块首行自述 "never enumerates or opens real cameras"。
5. `viz/imwrite.py`（标准库 PNG/PGM/PPM，字节级确定）、`viz/plot2d.py`、`viz/colormaps.py`。
6. `io/hdf5_schema.py`：`write_synthetic_hl3`（仅合成用例）/`read_analysis`/`validate_file`/`canonical_json`/`config_hash`；`cli/run.py` 落盘 `np.savez`/`np.save`。真实 run→`.hl3` 写入器是缺口。
7. `fea/project.py`：`TriMesh`/`locate_points`/`project_to_nodes`/`interpolate_at_points`，三法（lumped L2、matrix-free CG 一致 L2、nearest），nan 传播 + `n_outside/n_dropped` 计数。
8. `strain/vsg.py`（Eq. 7.2 唯一拷贝在 `io/hdf5_schema.vsg_size_px`，此处只包装）、`strain/field.py`（`@vsg_px` 强制、`with_window` 扫描）、`uq/propagate.py`（每点应变 σ）。
9. `cli/__main__.py`（懒加载 dispatch，doctor 在断环境也能跑）、`cli/run.py`（npy/npz/pgm 原生，PNG/TIFF 走 Pillow，拒收彩色图）、`cli/validate.py`（零自有检查，全部转发 `validate_file`）。
10. 根 `LICENSE` + `pyproject.toml` `license = Apache-2.0` + 树内 27 个 `SPDX-License-Identifier: Apache-2.0` 头。R1-F3 给 OC/DICe 此行 ● 的口径即"开源无许可摩擦"（其脚注 40）。
11. `uq/propagate.py`（段 B/C/D，C 段对固定窗口/权重/掩码**精确**；A1 独立性假设随结果携带）、`correlate/icgn.py`（段 A：`compute_covariance`）、`stereo/triangulate.py::triangulation_covariance`（仅匹配项，Σ_cal 明文未含）。
12. `capture/mock.py`；`tests/test_icgn_synth.py`（metrics.json 记录其过采样 Fourier 平移散斑发生器）；`stereo/calibrate.py::synth_* / run_synthetic_experiment`；`io/hdf5_schema.SyntheticSpec`。
13. `stereo/calibrate.py` docstring："What this module is *not*：Not Zhang's method……All of that is later work"。可用面仅限：手头已有非共面 3D 点及其量测像点时的 DLT resection（无畸变）。
14. `pipeline/dic2d.py`（`ReferenceMode.INCREMENTAL/EVERY_N` + `compose_total` 链式法则）；`correlate/icgn.py::icgn_second_order`（Gao 2015 6×6 截断复合，含测试 `tests/test_icgn_second.py`）；`stereo/match.py::StereoMatchParams` 显式 `raise` 拒绝 `shape_order != 1`。

## 2. 计数

| 状态 | 行数 | 行号 |
|------|------|------|
| **DONE** | **6** | 1, 9, 19, 22, 23, 36 |
| **PARTIAL** | **11** | 2, 8, 10, 12, 13, 14, 15, 24, 28, 31, 32 |
| **MISSING** | **15** | 3, 5, 6, 7, 11, 16, 18, 20, 21, 25, 27, 30, 33, 34, 35 |
| **LEGAL-BLOCKED** | **1** | 17 |
| **WONT-V1** | **3** | 4, 26, 29 |
| 合计 | 36 | — |

**答案：DONE 6 行 vs MISSING 15 行**（PARTIAL 11、WONT-V1 3、LEGAL-BLOCKED 1）。

## 3. 与 R1 目标的三条诚实落差（供排期，不加戏）

1. **M 行（table stakes）缺口最大**。R1 §5.1 列的 17 个底线行里，S4 实打实 DONE 的只有 #1/#19（+#22 底线），而 #5 采集、#6 实时点测量、#11 FFT/ODS、#16 标记点、#20 报告、#21 暗色、#30 真实标定、#34 高速全部 MISSING——这些正是"客户询价对照清单"上会直接出局的行。其中 **#30 真实相机标定是唯一同时卡死 #2 立体链落地的 MISSING**（没有它，双目链只能吃合成/外部投影矩阵），应排最高优先级。
2. **已建成的差异化资产集中在 #24/#36/#10/#28**：UQ 传播链（含精确 PLS 段）、开源可溯源内核、schema+验证器、合成回归基建。这与 R1 楔子排名 #2（Python-first，已 DONE）、#3（UQ）、#5（开源内核）、#7（开放 schema）、#8（合成引擎）方向一致——落差在完成度而非方向。
3. **两个"半接线"要先合龙再谈新功能**：(a) 管线结果 → `.hl3` 写入器（schema、验证器、读取器都在，唯独真实 run 落盘缺席，#10 卡在 PARTIAL 的唯一原因）；(b) 二阶形函数 → 2D 管线与立体匹配（内核已实现并有专测，上层显式未接，#32 与 #2 各损一档）。两项均为纯接线工作，无新数学。

（S1 门禁自评佐证：`metrics.json` 记录 s1=partial、s2/s3=not-evaluated、exit_gate_pass=false——本矩阵的保守打分与门禁自评一致。）
