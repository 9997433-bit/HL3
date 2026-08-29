ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR1-F1 · S1 阶段 pass/fail 门禁清单（2D 计量收口）

- **子代理**：IR1-F1（fable，云端）｜Impl-R1 / 10 代理（4 fable + 3 opus-fast + 3 gpt-sol）
- **日期**：2026-08-28
- **输入**：`s1s4/DISPATCH.md`、`s1s4/IR1_DISPATCH.md`、`round3/R3-F4-beyond-vic-roadmap.md` §3-S1、`round2/R2-F1-sota-reconciliation.md` A 组表、`round2/R2-G2-bench-run.md` §3、`src/hl3/correlate/icgn.py`、`src/hl3/io/hdf5_schema.py`、`benchmarks/metrology/metrics.json`
- **效力**：低于 `LEGAL.md` → RUL/ADR-LIC-001 → R2-F1 Gate 表 → G2 协议。本文不新设阈值，只把已冻结的 A1/A2/A4/G6 门槛落到 Impl-R1 的独占路径与责任代理上。
- **判定纪律**：每个门二元 pass/fail，fail-closed；证据 = 仓库内工件 + 可复跑命令，不接受口头宣称。任何门不达标按 RUL-07 登记 xfail 与实测数值，**禁止放宽阈值**。全程零显微镜实现（RUL-04/L-7）、零 VIC 逆向（LEGAL.md 红线）、无"比 VIC 快/准"表述（RUL-03，G2 §7.3 同机条件未满足前永久禁言）。

---

## 0. 诚实基线：一阶内核今天已经做到什么、没做到什么

门禁设计的第一原则是不把已有能力重复立项，也不把没做的事说成做了。逐条对照 `src/hl3/correlate/icgn.py`（约 950 行，CPU float64 规范实现）与 `benchmarks/metrology/metrics.json`（rev `1bcc1de`）：

### 0.1 已经存在（S1 不得重做，只做回归保护）

| 能力 | 证据 |
|------|------|
| 一阶仿射 ICGN + ZNSSD（对 `g = a·f + b` 精确不变），ZNCC 报告值 | `icgn_first_order`、模块 docstring |
| **预滤波双三次 B 样条插值已是内核默认**（不是 Keys；R2-G2 实测 FAIL 的 Keys 从未进过内核） | `BSplineInterpolator`（Unser 递归预滤波 + reflect101 边界） |
| FFT-CC 整数初值 + ICGN 精化的串联（`search_radius > 0` 即启用，ZNCC=-1 表示"无初值"而非"零初值"） | `integer_search_fftcc`、`_resolve_initial_guess` |
| 失败分类学：9 态 `Status` 枚举，退化输入给状态码不给貌似合理的数（平坦子集、单向纹理、越界、空 AOI 全部有定义行为） | `Status`、spec §2.6 失败表 |
| 逐点位移协方差选项（`compute_covariance` + `image_noise_sigma`，`Cov ≈ 2σ²(JᵀJ)⁻¹`） | `ICGNResult.covariance` |
| 条件数守门（缩放 Hessian，`cond ≤ 1e10`）、对角加载、收敛判据按子集边缘像素运动归一 | `_well_conditioned`、`ICGNParams` |
| 合成平移精度：196/196 收敛，MAE ≈ 8.1×10⁻⁴ px，分量 bias ≤ 4.4×10⁻⁴ px，回归门已锁 | `metrics.json` `icgn_synthetic_translation`、`tests/test_icgn_synth.py` |
| HDF5 schema 机读镜像（`1.0.0-draft.2`），**quadratic 12 参数、应变张量族、VSG 公式的槽位已预留**，纯标准库可导入 | `hdf5_schema.py`：`SHAPE_PARAM_COUNT`、`STRAIN_TENSORS`、`vsg_size_px` |
| 测试基线：87 passed（Round 2 合并后记录于 metrics.json） | `python3 -m pytest tests src/tests -q` |

### 0.2 尚不存在或从未实测（S1 门禁的全部对象）

| 空白 | 诚实说明 |
|------|----------|
| 二阶（quadratic，12 参数）形函数 | 内核硬编码 6 参数仿射：`warp_matrix`/`compose_inverse` 是 3×3 齐次仿射代数，`ICGNResult.p` 固定 `(n,6)`。schema 有槽位≠内核有实现 |
| 应变引擎 | `src/hl3/strain/` 目录不存在。schema 里的应变常量是**格式定义**，没有任何计算代码 |
| 2D pipeline | `src/hl3/pipeline/` 目录不存在。"图像进→HDF5 出"今天要手写脚本串接 |
| A2 S 曲线 | **内核真实插值器（B 样条 + ICGN 全链）的 S 曲线从未测过**。R2-G2 §3 测的是独立的双线性/Keys 插值器（Keys 峰峰 0.010–0.014 px FAIL），结论只证明"必须实测最终插值器"，不能外推为内核已过关 |
| A1 噪声底 | metrics.json 的 `noise_floor_stub` 自我声明是"线性化平移诊断 stub，非生产 ICGN 测量"。σ_u ≤ 0.01 px 对生产内核**尚无成绩** |
| A4 应变噪声底 | 无应变引擎，故无任何数字 |
| schema 1.0 冻结 | 仍为 `1.0.0-draft.2`，docstring 明言"冻结前不承诺兼容" |
| 邻域/可靠性引导播种 | FFT-CC 逐点独立播种存在；reliability-guided 或邻点传播路径不存在（大变形场景初值鲁棒性未覆盖） |

---

## 1. 门禁总表

责任代理与独占路径按 `IR1_DISPATCH.md`。"复跑命令"以仓库根为工作目录；G3 汇总门要求每个数字可由命令 + 源码 blob 哈希追溯。

### A 组 · 二阶形函数（责任：IR1-O1，路径 `src/hl3/correlate/**`、`tests/test_icgn_second.py`）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S1-SF2-1 代数正确性** | 12 参数 quadratic warp 的构造/求逆/逆合成组合闭合：恒等元、`W(p)∘W(p)⁻¹=I`、随机参数往返误差 ≤ 1e-12（二阶合成不精确封闭时，必须写明所用近似及其误差界，测试锁住该界） | `tests/test_icgn_second.py` 单元测试全绿 |
| **G-S1-SF2-2 一阶零回归** | 现有 `tests/test_icgn_synth.py` 与 87 项基线**不改一行断言**全绿；一阶路径合成平移 MAE 仍 < 5×10⁻³ px 回归限内 | `python3 -m pytest tests -q` 输出 |
| **G-S1-SF2-3 二阶精度增益** | 合成解析二次位移场（系数已知）上：二阶收敛点比例 ≥ 一阶；二阶位移 MAE 至少比一阶低一个可断言的裕度（测试内写死具体数，来自实测后锁定）；纯平移场上二阶不劣于一阶（过参数化不引入偏置超过 2× 一阶水平） | `tests/test_icgn_second.py` 中的对照测试 |
| **G-S1-SF2-4 失败语义不变** | `Status` 枚举数值不变（R2-O1 §2.7 已发布为规范）；二阶新增退化情形（12×12 Hessian 病态）复用 `SINGULAR_HESSIAN`，不新增未文档化状态码 | 测试断言 + `icgn.py` docstring 更新 |
| **G-S1-A2 S 曲线（A 组锚点 A2）** | 经**生产 ICGN API**（非独立插值器、非 stub）做相位扫描：一阶与二阶、B 样条插值下，S 曲线偏置峰峰值 ≤ 0.01 px（v1 门槛，R2-F1 A2）。**不达标 → xfail 登记实测峰峰值，禁改阈值** | `tests/test_s1_metrology.py`（G2 落测）+ `benchmarks/metrology/metrics.json` 新增 `interpolation_scurve_production` 条目 |
| **G-S1-A1 位移噪声底（锚点 A1）** | 生产 ICGN 在带噪静态对（≥3 套独立散斑，两幅独立噪声实现）上 σ_u ≤ 0.01 px；替换掉 metrics.json 里的线性化 stub 或将 stub 明确降格为 legacy 诊断条目 | 同上，metrics.json 新增 `noise_floor_production` 条目，脚本判 pass/fail |

> 双五次 B 样条：S1 只要求**测得双三次 B 样条真实 S 曲线后做记录性决策**——若 G-S1-A2 以双三次通过，双五次列为 backlog 不设门；若不过，双五次成为 xfail 的整改路径。不为未测的插值器预设门。

### B 组 · 应变 / VSG（责任：IR1-O2，路径 `src/hl3/strain/**`、`tests/test_strain.py`）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S1-STR-1 引擎存在且口径一致** | `src/hl3/strain/` 提供切窗 PLS（逐点局部平面拟合）位移梯度估计；VSG 窗口可配；输出至少 engineering 与 green_lagrange 两族，命名与 `hdf5_schema.STRAIN_TENSORS`/`STRAIN_METHODS` 严格一致；等效 VSG 尺寸按 `vsg_size_px(window_pts, step_px, subset_px)` 同一公式计算并随结果输出 | `tests/test_strain.py` + API docstring |
| **G-S1-STR-2 解析场验证** | 均匀单轴拉伸 + 刚体平移合成场：应变恢复误差 ≤ 门内写死的解析容差；**纯刚体旋转场上 Green-Lagrange 应变 ≈ 0**（工程应变允许其已知的一阶旋转伪应变，测试注明这是量的性质不是 bug） | `tests/test_strain.py` 解析对照测试 |
| **G-S1-STR-3 无效点不投毒** | 窗口内含 `Status != CONVERGED` 点时：显式剔除/降权并在输出 flags 标记，**不得让 NaN 静默扩散**；有效点不足以定平面时该点应变置无效而非外推 | 注入失败点的单元测试 |
| **G-S1-A4 应变噪声底（锚点 A4）** | 带噪静态对经"生产 ICGN → 应变引擎"全链：σ_ε ≤ 100 µε（v1），**成绩必须与所声明 VSG（px）成对出现**，无 VSG 声明的应变噪声数字视为无效。不达标 → xfail 登记（σ_ε, VSG）实测对 | `tests/test_s1_metrology.py` + metrics.json 新增 `strain_noise_floor` 条目 |

### C 组 · 2D pipeline（责任：IR1-O3，路径 `src/hl3/pipeline/**`、`tests/test_pipeline_2d.py`）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S1-PIPE-1 端到端可跑** | 单一入口（Python API）：参考图 + ≥1 目标图 + 参数 → ICGN →（可选）应变 → 写出 schema 合规 HDF5；`hdf5_schema.validate_file` 对产物零 error 通过（无 h5py 环境按既有 `skip_reason` 纪律跳过并注明） | `tests/test_pipeline_2d.py` 端到端测试 |
| **G-S1-PIPE-2 确定性** | 同输入同参数连跑两次：结果数值逐位一致，`config_hash` 一致；参数快照完整写入产物（S3 的 C1 在此埋桩，不在 S1 扩展为跨机复算门） | 测试内双跑断言 |
| **G-S1-PIPE-3 失败传播保真** | 逐点 `Status` 无损进入产物的 flags/valid 掩码；下游读回的无效点集合与内核输出**逐点相等**；无一处把失败点写成貌似合理的数 | 含人为失败点的往返测试 |
| **G-S1-PIPE-4 CI 可跑性（Impl-R1 停止条件"精度测试可跑"）** | 全部 S1 测试（含 `test_s1_metrology.py`）在 Linux CPU、无网络、无 GPU 下 `pytest` 直跑通过或按纪律 xfail/skip；总时长不破坏现有 CI 预算（基线 87 项约 9 s，S1 全量以 ≤ 5 min 为门） | CI 日志 / 本地计时 |

### D 组 · Schema（责任：IR1-O3 产物侧 + IR1-F4 规范侧；冻结评审需 G1 法务复核签字）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S1-SCH-1 槽位实证** | `quadratic`（12 参数）与应变/VSG 槽位由**真实 pipeline 产物**（非仅 `write_synthetic_hl3` 合成写手）写入并读回逐位一致——schema 冻结前每个承诺字段至少被真实代码路径行使一次 | `tests/test_pipeline_2d.py` 往返断言 |
| **G-S1-SCH-2 1.0 冻结评审** | 去掉 `-draft` 后缀当且仅当：docs §12.1 冻结检查单逐项打勾、`docs/schema-hdf5.md` 与 `hdf5_schema.py` 交叉断言测试全绿、G-S1-SCH-1 通过。冻结即承诺 §11.2 版本策略（更高主版本必须拒读）。检查单未清零 → schema 保持 draft，**本门记 fail 而非降格通过** | 冻结声明（版本号提交）+ `tests/test_hdf5_schema.py` |
| **G-S1-SCH-3 迁移测试** | 仓库内至少一个 `1.0.0-draft.2` 样例文件：冻结后的读取器对它的行为（兼容读入或明确拒绝+可诊断报错）有测试锁定，二选一但必须显式 | 迁移测试 + 样例文件（小于 1 MB，可入 git） |

### E 组 · 汇总判定（责任：IR1-G2 测试 / IR1-G3 metrics.json）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S1-SUM-1 机器可判** | `benchmarks/metrology/metrics.json` 由脚本重生成：A1/A2/A4 每项带 `status: pass|fail|xfail`、实测值、阈值、复跑命令、源码 blob 哈希；**pass/fail 由脚本比较判定，人手不改 status 字段** | metrics.json + 生成脚本 |
| **G-S1-SUM-2 S1 出口** | 出口 = G-S1-SF2-1…4、STR-1…3、PIPE-1…4、SCH-1…3、SUM-1 全 pass，**且** A1/A2/A4 三锚点各自为 pass 或"RUL-07 纪律 xfail（登记实测值+差距+整改指向）"。存在任何未登记的 fail → S1 不出口，冻结 Impl-R2 派工（R3-F4 §7 熔断第 1 条） | 本表全量核对 + `PROGRESS.md` 记录 |

---

## 2. 全局约束（随门禁生效，违反任一即该代理产出整体 fail）

1. **独占路径纪律**：`git add` 只用各自独占路径，禁止 `git add .`（DISPATCH.md）。
2. **零显微镜**：S1 任何代码/文档不得出现显微镜能力实现（GAP-5 fail-closed）。
3. **零 VIC 逆向**：不接触 VIC 二进制/专有格式；对比表述只引公开资料并标"厂商公开宣传值，未独立验证"。
4. **阈值不可议**：A1 ≤ 0.01 px、A2 峰峰 ≤ 0.01 px、A4 ≤ 100 µε 来自 R2-F1 冻结表，S1 内任何人无权修改；差距只能 xfail 登记。
5. **stub 退役**：S1 出口后 metrics.json 中不得再有以 stub 数字冒充生产成绩的条目；保留的 stub 必须带 `diagnostic-stub` 降格标签（现有 `noise_floor_stub` 已自带，保持即可）。
6. **报告首行**：每个 IR1 代理报告第一行 `ACTUAL_MODEL_SLUG: <slug>`，禁止静默降级。

---

## 3. 与 Impl-R1 停止条件的对账

DISPATCH.md 停止条件 → 门禁覆盖：**二阶形函数或明确 xfail** → G-S1-SF2-1…4 + RUL-07 通道；**应变/VSG** → G-S1-STR-1…3 + G-S1-A4；**2D pipeline** → G-S1-PIPE-1…4；**精度测试可跑** → G-S1-PIPE-4 + G-S1-SUM-1。schema 冻结（G6）在 R3-F4 §3-S1 出口证据内，故 G-S1-SCH-1…3 一并列为 S1 出口项。

*IR1-F1 完。本文只写入独占路径 `.agent_workspace/s1s4/IR1-F1-s1-gates.md`；引用键沿用 A1/A2/A4、G6、RUL-03/04/07、GAP-5、S1–S8。*
