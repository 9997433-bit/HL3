ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR4-F2 · S4 产品面审计：HL3 实际交付 vs VIC-2D 8 / VIC-3D 11 客户所得

- **审计对象**：`src/hl3/{cli,gui,viz,fea,io,capture}/`、`pyproject.toml`、`tests/test_{gui,fea,viz,cli_run,s4_smoke}.py`（工作树现状，含未提交文件）。
- **对照基线**：`research/vic_public_feature_baseline.md`（厂商公开宣传，未独立验证）、`s1s4/IR3-F1-s4-gates.md` 门禁表、`s1s4/IR3-F3-gui-scope.md` 与 `s1s4/IR3-F4-fea-contract.md` 两份 FROZEN 契约、`round3/R3-F4-beyond-vic-roadmap.md` §3-S4。
- **实测环境**：Python 3.12.3，numpy 2.4.4，h5py 3.16.0，matplotlib 3.11.1，Pillow 12.3.0；**tkinter、blake3 缺席**。全量套件 `PYTHONPATH=src python3 -m pytest tests src/tests -q` → **700 passed, 0 skipped, 45.3 s**（IR3-F1 基线 690+2skip，S4 冒烟三项已翻真绿）。
- **纪律**：只引公开资料；无"比 VIC 快/准"表述；iris 只出现在否定与引用句式（RUL-03/06）。每条结论附文件行号或可复跑命令。

> **先说一个总括性事实**：S4 的全部产品代码（`src/hl3/__main__.py`、`cli/run.py`、`cli/__main__.py`、`viz/`、`fea/`、`gui/`、四个新测试文件）在审计时刻**均为 git 未跟踪/未提交状态**（`git status`），`pyproject.toml` 处于半暂存（`MM`），另有一个走错目录的 `IR3-G3-ci.md` 落在仓库根且内容与工作树自相矛盾（该文件称"未注册 console script"，而工作树 pyproject 已注册）。**从 git 历史看，S4 产品尚不存在**。以下审计针对工作树。

---

## 1. S4 实际交付 vs VIC 客户实际所得

### 1.1 S4 实际交付清单（实测，非宣称）

| 表面 | 行数 | 实测能做什么 | 实测不能做什么 |
|------|-----:|--------------|----------------|
| `hl3.cli`（4 文件，1518 行） | 1518 | `python -m hl3 {doctor,run,validate}` + `--version`；`run`：2D 序列相关（文件或 `--synthetic`），完整 ICGN 参数面、参考帧策略、种子策略、应变 off/auto/required、`--min-valid-fraction` 质量门、退出码 0/1/2 三值统一；输出 `.npz`/`.npy` + 确定性 JSON 摘要（`SUMMARY_SCHEMA=1`，含 provenance 与逐帧质量）；`doctor`：环境报告 + 48×48 算术自检（版本表说零件在，只有算术说零件对）；`validate`：`.hl3` 结构校验 | **写不出 `.hl3`**（`--out x.hl3` → `error: --out must end in .npz or .npy`，exit 2）；无 3D（只包 dic2d）；无 AOI 入口；无 UQ 输出；无出图命令；无 `export/diff/sweep/report`；provenance 无 `config_hash`/`input_hash`（这两个哈希全仓库只在 `hdf5_schema.py` 里存在） |
| `hl3.viz`（4 文件，1687 行） | 1687 | 无头出图双后端：matplotlib（PNG/PDF/SVG，真坐标轴+色标）与**零依赖内置渲染器**（自带 PNG 编码器、Netpbm、33 锚点 viridis/gray/bwr、3×5 像素字体色标端值）；量名注册表（符号量对称范围+bwr）；NaN 点画中性灰不插值；序列级统一色标（`scope="sequence"`）；字节确定性；`HL3_VIZ_BACKEND` 可钉后端 | 不读 `.hl3`（只吃数组或 run 对象）；**应变图无 VSG 标注**（`grep -ri vsg src/hl3/viz/` 零命中，G-S4-VIZ-3 判 fail）；无动画/等值线/3D 表面/HTML 报告/FEA 叠加（docstring 已如实排除） |
| `hl3.fea`（2 文件，1023 行） | 1023 | `TriMesh`（2D，构造期全量校验）+ 均匀网格空间索引点定位 + 三种 DIC→FE 节点投影（barycentric 加权/least_squares 矩阵自由 CG/nearest）+ FE→DIC 反向采样；完整审计尾（n_samples/weight/coverage/filled_by_nearest）；确定性并列裁决 | **无任何网格文件导入**（VTK/Exodus/inp 均无，docstring 明示排除）；无同滤波链（等效 VSG）对比报告；无归一化残差 z 判定；无边界条件导出；只支持 2D 点（3D 世界坐标点云进不来） |
| `hl3.gui`（3 文件，133 行） | 133 | `PolygonAOI`（射线法点在多边形内 + JSON 侧车往返）；包导入无 matplotlib/tkinter 副作用 | **查看器是空壳**（详见 §2.1）：任何环境下都不开窗、不读文件、不显示任何场；AOI 无交互编辑、无 role/hole、无写回 `.hl3`，且**没有任何下游消费它**（pipeline/CLI 均无 mask 入口） |
| `hl3.io` | 1296+9 | S2 冻结的 `hdf5_schema`：常量镜像、`write_synthetic_hl3`、`read_analysis` 纯 h5py 读取器、`validate_file` | S4 零新增。包 docstring 自称 "readers, writers and exporters"，实际 exporters 为零；**真实测量结果没有任何进入 `.hl3` 的路径**（合成写入器只写解析解） |
| `hl3.capture` | 140 | `MockCapture`：确定性合成散斑、丢帧/噪声/时戳抖动 | 无任何真实相机路径（S6 范围，符合派工红线） |
| `pyproject.toml` | 39 | `viz = ["matplotlib"]` extra；`[project.scripts] hl3 = "hl3.cli.__main__:main"`（入口真实存在，能接通） | 未发布 PyPI（`0.0.1.dev0`）；scripts 段未提交；B3 正式口径（`pip install hl3`）不可评 |

S4 测试面：`test_cli_run.py`(3) + `test_fea.py`(2) + `test_gui.py`(2) + `test_viz.py`(1) + `test_s4_smoke.py`(3) = **11 个测试盖约 4360 行新产品代码**。对比 S1 内核 127 测试盖一个文件——产品层的测试密度约为内核层的 1/50。

### 1.2 对照表：按测量链逐环

VIC 侧一律为厂商公开宣传值（`research/vic_public_feature_baseline.md`），未独立验证。

| 链环 | VIC-2D 8 / VIC-3D 11 客户拿到 | HL3 S4 客户实际拿到 | 差距定性 |
|------|------------------------------|---------------------|----------|
| 2D 相关 | 全场位移/应变，宣传 1/100 px 运动分辨率，实时 2D（许可） | CPU 单线程参考 IC-GN（一阶+二阶形函数、FFT-CC 初值、ZNCC 门、协方差可选），确定性逐位可复现 | 功能面可用；吞吐无 GPU/多线程（S5 范围），实时为零 |
| 3D 立体 | 标定→任意曲面 3D U/V/W/应变，宣传 32 核 1M 点/s | 库层有 `hl3.stereo`+`dic3d`，但 **CLI 无 3D 入口**；标定只有线性 DLT（非 Zhang），**无镜头畸变模型**，A6 连续三轮无主 | 3D 对产品用户**不存在**：没有任何命令能跑立体链 |
| AOI | AOI 编辑器是每次分析的第一步；自动种子检测 | `PolygonAOI` 数据类 + JSON 侧车，**无交互编辑、无消费方**——`hl3 run` 无 `--aoi`，`dic2d.py:438` 明写 masked AOI 不在范围 | 孤儿功能：画了也没人用 |
| 应变 | exx/eyy/exy + 主应变 + Mises（标准输出），VSG 概念 v8 内置 | pipeline 交接面只出 exx/exy/eyy；`hl3.strain.StrainField` 明明算了 e1/e2/gamma_max/von_mises（`field.py:310-314`），`viz.QUANTITIES` 也注册了它们的色图，**中间管线没接**——npz 里没有，`save_run_field` 画不出 | 已实现未接线；CLI 报告 L_VSG（好），viz 图上不标 VSG（违 VIZ-3 门） |
| UQ | 非 VIC 主叙事（本项目的差异化点） | `hl3.uq` S3 已交付（协方差传播+MC 覆盖率实证），但 **S4 CLI/viz/npz 全链一个 σ 都不输出** | 自家最大卖点没进产品面；"15 分钟拿到**带不确定度**的应变云图"（R3-F4 §3-S4 目标原文）实测不成立：拿得到应变，拿不到不确定度 |
| 结果格式 | 专有工程文件 + CSV/STL/ASCII/MATLAB 导出、HDF5（v8 新增） | 公开 `.hl3` 规范 + 验证器 + 纯 h5py 读取器——但 `hl3 run` **写不出它**；实际交付格式是 npz/npy/JSON；无 CSV/MATLAB/VTK 导出 | 结构性卖点（开放格式）与产品口（CLI）互相看不见，详见 §3.1 |
| 可视化 | iris：出版图、动画、等值线、4K/PDF、FEA 叠加、散斑贴图 | 无头 `save_field`/`save_run_field`：PNG/PDF/SVG（mpl）或零依赖 PNG/PPM/PGM；计量上诚实（NaN 掩膜、序列统一色标、色标端值） | 无头出图是真实的结构性差异点（VIC 公开叙事以桌面为主）；但功能广度不在一个量级，且已如实自我声明 |
| GUI | 成熟 Windows 桌面工作流（工程、报告、模板、暗色主题） | 一个不开窗的空壳（§2.1） | 事实上为零 |
| 采集/实时 | VIC-Snap + VIC-Gauge + 全场实时 + 相机深绑 | MockCapture（仅 CI 用途） | 零（S6 范围，按红线属"诚实的零"） |
| FEA 对比 | iris 导入 FE、对比工作流 | 双向几何投影（数学质量高）但无文件导入、无对比报告 | B6 最小链**未闭合**（§2.2） |
| 分发/许可 | Windows-only、PC 密钥、销售跟进 | `pip install`（未发布）、Apache-2.0、Linux CI 常绿、`doctor` 自诊断 | 唯一在 S4 真正兑现的结构性优势雏形；但没上 PyPI 之前 B3 正式门 evaluable=false |
| 显微镜/SEM、DMT、多系统拼接 | 有 | 无（RUL-04/GAP-5 fail-closed） | 合规缺席，不追 |

**一句话**：VIC 客户拿到的是"从相机到报告"的完整闭环产品；HL3 S4 客户拿到的是一条**只有 2D、终点是 npz 的高质量无头管道**，加上三个互相不通气的零件（.hl3 生态、AOI、FEA 投影）和一个不存在的 GUI。R3-F4 对 S4 的定位是"无头产品链的最小闭环"——**"无头"成立，"闭环"不成立**：run 的输出进不了 validate，进不了（规划中的）GUI，AOI 的输出进不了 run，UQ 的输出进不了任何东西。

### 1.3 IR3-F1 门禁对账（S4 出口条件 G-S4-SUM-2 的核对）

| 门 | 判定 | 依据 |
|----|------|------|
| CLI-1 入口存在 | pass | 三子命令 + `--help` + 退出码实测 |
| CLI-2 全链复用 | **fail** | 包装纪律合格（无私有数学），但"产物经 validate_file 零 error"不可满足——产物根本不是 `.hl3` |
| CLI-3 确定性溯源 | partial | JSON 摘要字节确定 + 参数快照有；`config_hash`/`input_hash` 缺席 |
| CLI-4 失败语义 | **fail（未测）** | 门要求 ≥3 种注入失败逐一被测；`test_cli_run.py` 三个测试全是快乐路径，零失败注入 |
| CLI-5 validate 零回归 | pass | `test_validate.py` 常绿，`hl3.cli` 导入无副作用保持 |
| B3 TTFR | evaluable=false（预期内） | 未发布 PyPI；仓库内链条缺"CLI 出图"一步（§3.1 条 2），秒表也没人跑 |
| VIZ-1 无头渲染 | pass（从 pipeline 结果侧） | PNG+PDF/SVG 实测可写；HDF5 侧未接 |
| VIZ-2 可选依赖 | pass（超额） | 比门槛更强：无 matplotlib 也能出 PNG |
| VIZ-3 计量诚实 | **fail** | 应变图无 VSG 标注；σ 场无自动接线 |
| VIZ-4 测试口径 | **弱 pass** | 无像素哈希（合规），但内容级断言也基本没有（1 个测试只查文件头和大小） |
| VIZ-5 非 iris 声明 | pass | docstring 排除清单齐全，无违禁词 |
| FEA-1 假绿消除 | pass | 空目录假绿已被真实包替换 |
| FEA-2 网格导入 | **fail** | 无任何文件导入（连门槛点名的 VTK legacy ASCII 也没有） |
| FEA-3 双向投影 | pass | 往返误差上界写死在测试内（1e-12 / 1e-8） |
| B6 最小链 | **fail** | 同滤波链对比、z 分数报告、案例脚本全部缺席 |
| FEA-5 边界条件导出 | **fail** | 不存在 |
| GUI-1 范围诚实 | pass | docstring "Not a publication tool"，无头导入安全实测 |
| GUI-2 无头测试纪律 | **fail（未测）** | viewer 的任何路径零测试覆盖 |
| GUI-3 交互验证移交 | **fail（未登记）** | `IR3-O3-fea-gui.md` 共 7 行，无 GAP-1 移交段 |
| SMK-1 冒烟翻绿 | pass | 3 skip → 3 真导入，700 passed |
| CI-1 可选项纪律 | pass | ci.yml 未动，无 matplotlib 的最小依赖车道实测仍绿（新测试全部只需 numpy） |
| SUM-1 套件常绿 | pass | 700 passed 45.3 s，新增用时 ≈0.4 s，远低于 5 min 预算 |

**结论：22 门中 8 个 fail / 未满足。按 G-S4-SUM-2 的字面（"存在未登记 fail → S4 不出口"），S4 未达出口条件。** 三份收官报告（IR3-O1/O2/O3，合计 18 行）没有登记任何一个 fail，这本身违反 RUL-07 的 xfail 登记纪律。

---

## 2. 坏/空/桩模块清单

### 2.1 `hl3/gui/viewer.py` —— 桩，且桩本身是坏的（最严重单点）

1. **没有 `if __name__ == "__main__"` guard**。文内 `--help` 文本自我宣传的调用方式是 `python -m hl3.gui.viewer [field.npy]`，实测该调用**静默退出 0，什么都不发生**（模块被导入后没有任何执行入口）：
   ```text
   $ PYTHONPATH=src python3 -m hl3.gui.viewer f.npz ; echo $?
   0        # 无任何输出。tkinter 在本机缺席，按契约本应 exit 2 + stderr 提示
   ```
   连 `--help` 都打印不出来。这不是"交互无法验证"，是**入口不存在**。
2. 即使在依赖齐全的工作站上，`main()` 也**从不启动交互**——第 45-49 行无条件打印 "interactive session is not started in this non-interactive context" 后返回 0，并**完全忽略传入的文件参数**。客户在任何机器上都得不到一个窗口。
3. 对 FROZEN 契约 `IR3-F3` 的偏离是全面的：冻结文件名 `view.py` / 冻结调用面 `--analysis --field --frame --save-aoi path` / 读 `.hl3` 经 `read_analysis` / `valid_mask` 单一事实源 / 帧导航 / 色标带单位——**一条都没有**。推翻 FROZEN 条目需要 ADR 并在 MASTER_PLAN 留痕（FRZ 纪律），仓库内无此 ADR。
4. 测试覆盖为零：`test_gui.py` 只测 AOI；viewer 的退出码 2 路径、缺依赖路径均未测（G-S4-GUI-2 fail）。

### 2.2 `hl3/fea/` —— 实现质量高，但与自己的 FROZEN 契约背道而驰，且 B6 三件套缺二

- `project.py` 的数学本身是本轮最扎实的新代码（lumped/consistent L2 投影 + 矩阵自由 CG + 空间索引 + 完整审计尾，测试断言写死误差上界）。
- 但 `IR3-F4` 冻结的导入面是**恰好** `{TriMesh, Projection, project_points, mesh_from_vtk}`、方法**只有** `nearest_node`、点维度 D∈{2,3}、`cells_csr()` 对齐 schema §9.1。实现交付的是完全另一套名字（`locate_points/project_to_nodes/interpolate_at_points`），2D-only，无 `mesh_from_vtk`，无 `cells_csr`。方向上是"做多了插值、做丢了文件导入和 3D"——**无 ADR 的契约反转**。后果实打实：3D 立体链的世界坐标点云（契约 §1 表中的 `Dic3DRun` 行）现在进不了 FEA 模块。
- B6 最小链三件套（同滤波链对比报告、z 分数、边界条件导出）**零交付**，门禁表里这是 S4 的核心锚点之一。IR3-O3 报告对此的全部记载是一行"不做 VTK 文件导入、不做全局 FE-DIC"，把契约要求的 VTK 导入说成了范围排除。

### 2.3 `hl3/gui/aoi.py` —— 能用但孤儿 + 违冻结格式

- 侧车格式冻结为 `{"hl3_aoi_sidecar": "1.0", polygons: [{role: outer|hole, vertices}], sequence, reference_camera}` 且经 `canonical_json`；实现是 `{name, units, vertices}` 单多边形，无版本键、无 role、无孔洞支持、用普通 `json.dumps`。两个格式互不兼容，且实现侧**没有版本字段**，将来想修就是断代。
- 全仓库无消费方：`grep -ri aoi src/hl3/{pipeline,cli,correlate}` 只命中 dic2d 的一句"不支持"。

### 2.4 其余

| 模块 | 状态 |
|------|------|
| `hl3/io/__init__.py` | docstring 自称含 "exporters"，实际为空承诺；S4 无人持有该路径（派工如此），但结果是产品链断在这里 |
| `hl3/cli/__main__.py` docstring | "Until the console script is registered in pyproject.toml…"——工作树 pyproject 已注册，陈述过期（小） |
| 仓库根 `IR3-G3-ci.md` | 走错目录的报告 + 内容与工作树矛盾（称未注册 scripts）；`.agent_workspace/s1s4/` 下另有同名新版。应删根版 |
| `.coverage.cursor.pid44563.*` | 覆盖率临时文件散落仓库根，未入 .gitignore |
| `tests/test_gui.py` | `import pytest` 未使用（lint 级） |
| **全部 S4 源码未提交** | `git status`：`src/hl3/{__main__.py,cli/run.py,cli/__main__.py}`、`fea/`、`gui/`、`viz/`、4 个测试文件均 untracked。任何 clone 该仓库的人拿到的仍是 S2/S3 |

**明确不是坏/桩的**：`hl3.viz` 全部三个实现文件（含零依赖 PNG 编码器与像素字体，工程上完整且诚实）、`hl3.cli.run`/`__main__`/`validate`（在其自设边界内质量高）、`hl3.fea.project` 的数学、`hl3.capture.mock`。本轮的问题模式不是烂代码，是**接线缺失与契约漂移**。

---

## 3. CLI / GUI 可用性差距

### 3.1 CLI（对标 VIC-2D 8 的"命令行批处理"与 R3-F4 的 15 分钟目标）

1. **`.hl3` 断路（最高优先）**：`hl3 run` 只写 npz/npy/JSON，`hl3 validate` 只读 `.hl3`——同一个 CLI 的两个子命令**处理互斥的格式**。项目对外的三大卖点之一"带版本号的公开格式 + 验证器 + 独立读取器"（README 第一表），对真实测量数据是够不着的：全仓库唯一的 `.hl3` 写入口是 `write_synthetic_hl3`（解析解专用）。修复路径明确：pipeline 结果 → schema §9 的 `fields/` 写入器，约束都已在 `hdf5_schema.py` 里。
2. **拿不到图**：没有 `hl3 plot`/`report`；B3 的链条 `run → 第一张应变云图` 中间必须手写 Python 调 `hl3.viz`。对"15 分钟 TTFR"而言，纯 CLI 用户走不完（实测 run 本身 <1 s，瓶颈全在缺的那一步）。
3. **拿不到不确定度**：`--strain` 有三态开关，UQ 却连开关都没有；summary 里无任何 σ/CI 字段。
4. **拿不到主应变**：pipeline 应变交接面只透传 exx/exy/eyy；e1/e2/von Mises 在 `hl3.strain` 里现成、在 `viz.QUANTITIES` 里已注册色图——缺的只是 `dic2d` 交接面把 `StrainField` 的全部名字放出来。
5. **无 AOI/掩膜旗标**：非矩形试样（VIC 用户的常态）只能全场跑然后自己丢点。
6. **无 3D**：`dic3d` 在库层可用，CLI 层不可达。
7. 失败路径零测试（CLI-4）：坏图像/坏配置/不可写路径的行为只有代码承诺，没有测试锁定。
8. 小项：色图不能从 CLI 选（viz 有 `colormap_choices()` 却没有消费它的旗标）；彩色图像直接拒绝（理由成文可辩，但 VIC 用户预期是软件自己处理）；console script 安装后 help 仍自称 `python -m hl3`。

**CLI 已做对的**（应保持）：三值退出码全家统一并写进 `--help`；`doctor` 的算术自检设计（不止验证导入，还验证 u=+2/v=+1）；摘要 JSON `allow_nan=False` + 排序键的字节确定性；写前检查输出路径（不把相关跑完才发现路径打错）；错误消息几乎每条都带"下一步怎么办"。这是产品级的错误设计，差的是覆盖面不是品味。

### 3.2 GUI（对标"社区版基础查看器 + AOI 编辑"这个自设的最低目标）

1. **可用性为零**：见 §2.1。当前不存在任何方式让任何用户在任何平台看到任何一个场的任何一帧。自设目标的两件事（看云图、编辑 AOI）一件都做不了。
2. 冻结范围里"最后已解算帧为初始帧、色标单位取自 `fields/u@space`、`valid_mask` 单一事实源"这些计量正确性设计全部悬空。
3. AOI 即使将来能画，也进不了任何计算（§3.1 条 5 同因）。
4. 交互验证在本环境结构性不可达（无显示服务器、无 tkinter），GAP-1 移交义务未履行——需要在收官材料里明写"GUI 未经任何人手工走查"。
5. 对照 VIC：这里不是"差距大"，是**范畴缺席**。诚实的表述只有一种：HL3 S4 无 GUI，有一份 GUI 的冻结规格书和 133 行未接线的零件。

---

## 4. Schema 冻结状态

**结论：未冻结，且冻结在本循环内结构性不可达；同时 S4 在治理外新增了三个事实格式。**

1. **权威版本**：`src/hl3/io/hdf5_schema.py:76` `SCHEMA_VERSION = "1.0.0-draft.2"`；`docs/schema-hdf5.md` 文首状态"草案"。draft 后缀的语义是**不承诺兼容**（§12.1 原文），即今天写出的任何 `.hl3` 文件都可能被 1.0.0 正式版拒绝。
2. **§12.1 四条冻结条件一条未满足**，其中两条（"至少一个外部独立读取器"、iDICs Challenge 数据跑通）依赖外部世界，不是写代码能关的。README 第 42 行"schema 草案已冻结为 1.0.0-draft.2"的措辞有误导性——冻结的是**草案文本**，不是 schema；建议改写。
3. **G6 无主已三轮**：IR2-F1 曾写"随 Impl-R3 收口"，IR3 派工明令 `src/hl3/io/**` 本轮无人可动（IR3-F1 §2.1），于是 S4 结束时 schema 与 S2 交付时一个字节没变。这个决定本身合规，但要指名后果：**产品面（CLI/GUI/viz）与容器格式的会师被推迟到了两边都已各自定型之后**，届时对齐成本更高。
4. **治理外的新格式**（S4 实际新增的兼容性表面，均不在 schema 文档、不在 validate 覆盖内）：
   - `hl3 run` 的 npz 布局（16 个数组键）+ JSON 摘要（`SUMMARY_SCHEMA = 1`，run.py:88 有成文的 bump 政策——这是好的，但它活在 docstring 里，docs/ 没有它）；
   - AOI JSON 侧车——**无版本键**，与 IR3-F3 冻结格式互斥（§2.3）；
   - `FieldImage`/`ValueRange` 作为 viz 的机读输出结构（未承诺稳定性，可接受）。
   即：**受治理的格式（.hl3）产品写不出，产品写出的格式（npz/JSON/侧车）不受治理。** 若 S5 前不并轨，事实标准会是 npz——因为用户手里只有它。
5. 相关冻结物状态一并登记：`IR3-F3`（GUI 范围）与 `IR3-F4`（FEA 契约）两份 FROZEN 文件已被实现事实性推翻且无 ADR（§2.1/§2.2）；exit-code 契约（IR2-F4）与 `validate` 调用面保持完好；`SUMMARY_SCHEMA` 是 S4 唯一主动做了版本治理的新表面。

---

## 5. 收尾判定（供父调度器引用，措辞已按 RUL-03/06 过滤）

- S4 的合规自我定位"无头产品链的最小闭环"（IR3-F1 §3.3）**过誉了一半**：无头链的"进"（CLI）与"算"（kernel 复用）成立且质量高；"出"断在格式（无 .hl3）、断在量（无 UQ、无主应变）、断在图（CLI 不出图、应变图无 VSG）；GUI 与 FEA-B6 两条支线未达自设门槛。
- 对外可宣称的只有：**"Linux CPU 上一条确定性的 2D DIC 命令行管道 + 无头出图库 + FE 网格双向投影原语，700 测试常绿"**。任何"产品化/闭环/对标商用"表述在当前工作树上不成立。
- 最短修复清单（按解锁面积排序）：① 提交代码（零成本，当前一切都在工作树上）；② pipeline→`.hl3` 写入器接通 run（解锁 validate/GUI/schema 三处）；③ 应变交接面放出 StrainField 全部字段 + viz 图注 VSG（解锁 VIZ-3 与主应变）；④ `hl3 plot` 薄包装 `save_run_field`（解锁 B3 链）；⑤ viewer 补 `__main__` guard 并按 IR3-F3 或 ADR 二选一了断契约漂移；⑥ FEA 补 VTK legacy ASCII 导入或以 ADR 正式改约。

*IR4-F2 完。本文只写入 `.agent_workspace/s1s4/IR4_F2_product_audit.md`；所有实测命令工作目录为仓库根，`PYTHONPATH=src`。*
