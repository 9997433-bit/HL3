ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR3-F1 · S4 阶段 pass/fail 门禁清单（CLI 全链 + 无头出图 + FEA 对照最小链 + 社区查看器基线）

- **子代理**：IR3-F1（fable，云端）｜Impl-R3 / 10 代理（4 fable + 3 opus-fast + 3 gpt-sol）｜**本循环最后一轮，完成后父调度器总结停止**
- **日期**：2026-08-28
- **输入**：`s1s4/IR2_BRIEF.md`、`s1s4/IR3_DISPATCH.md`、`round3/R3-F4-beyond-vic-roadmap.md` §3-S4、`round2/R2-F1-sota-reconciliation.md` §2 B 组表（B3/B5/B6 冻结门槛）、`src/hl3/cli/validate.py`、`src/hl3/pipeline/`（dic2d/dic3d 现状）、`src/hl3/uq/`、`tests/test_s4_smoke.py`（IR3-G2 已暂存）、`pyproject.toml` viz extra 草案（IR3-G3 工作区内）
- **效力**：低于 `LEGAL.md` → RUL/ADR-LIC-001 → R2-F1 Gate 表 → G2 协议（RUL-08 顺序）。本文不新设阈值，只把已冻结的 B3/B5/B6 门槛与 S4 派工范围落到 `IR3_DISPATCH.md` 的独占路径与责任代理上。
- **判定纪律**：每门二元 pass/fail，fail-closed；证据 = 仓库内工件 + 可复跑命令（工作目录 = 仓库根，包未 pip 安装，子进程复跑一律 `PYTHONPATH=src`），不接受口头宣称。不达标按 RUL-07 登记 xfail 与实测数值，禁止放宽门槛。全程零 GPU 内核、零相机 SDK、零显微镜（IR3_DISPATCH 首行 + RUL-04/GAP-5）、零 VIC 逆向、无"比 VIC 快/准"表述（RUL-03）、**无任何"iris 级/对齐 iris"表述**（RUL-06）。

---

## 0. 诚实基线：S2/S3 收口后 S4 侧已有什么、没有什么

本 checkout（`b141aad` + 本轮已暂存文件）实测 `python3 -m pytest tests src/tests -q`：**690 passed, 2 skipped，45.3 s**。2 个 skip 是 `tests/test_s4_smoke.py` 对 `hl3.cli.run` 与 `hl3.viz` 的 importorskip。**注意一个假绿**：`hl3.fea` 的冒烟已"pass"，但那只是因为 `src/hl3/fea/`（与 `src/hl3/gui/`）目前是**空目录**，被 Python 当成隐式命名空间包导入成功——里面一行代码都没有。本文把消除这个假绿列为正式门（G-S4-FEA-1）。

### 0.1 已经存在（S4 不得重做，只做包装与复用）

| 能力 | 证据 |
|------|------|
| `python3 -m hl3.cli.validate`：退出码语义、机读输出、变异测试套件、纯 h5py 子进程读取验证 | `src/hl3/cli/validate.py`、`tests/test_validate.py` |
| `hl3.cli` 包 docstring 明文承诺：导入无副作用、不拉子模块、不依赖 numpy/h5py；`hl3 run` 等"属于 S4、宁缺毋滥" | `src/hl3/cli/__init__.py` |
| 2D/3D pipeline 单一入口：确定性单线程、`_provenance` 参数快照、`config_hash`/`input_hash`、schema 合规产物、失败传播保真 | `src/hl3/pipeline/dic2d.py`、`dic3d.py` |
| UQ 传播链：图像噪声 σ → 位移协方差 → 应变 CI，蒙特卡洛交叉验证 + 覆盖率实证 | `src/hl3/uq/`、`tests/test_uq.py` |
| 本环境 matplotlib 3.11.1、h5py 3.16.0 可用；`viz = ["matplotlib"]` extra 已在 IR3-G3 工作区草案中 | 实测 import + `git diff pyproject.toml` |
| S4 冒烟骨架（importorskip 三表面） | `tests/test_s4_smoke.py`（IR3-G2 独占） |

### 0.2 尚不存在或本环境闭合不了（S4 门禁的全部对象与诚实边界）

| 空白 | 诚实说明 |
|------|----------|
| `hl3.cli.run` / `hl3.cli.__main__` | 不存在；pyproject 无 console script（且 pyproject 本轮归 IR3-G3，O1 不得注册脚本入口） |
| `hl3.viz` | 不存在；任何形式的出图代码为零 |
| `hl3.fea` / `hl3.gui` | 仅空目录（见上，假绿）；无网格导入、无投影、无对比、无查看器 |
| GUI 工具链 | 本环境 tkinter 与 PySide6 **均不可导入**（实测 ModuleNotFoundError）：交互行为在本环境无验证回路，只能做结构级测试 + GAP-1 移交 |
| FEA 真解算器输出 | 仓库内无 Abaqus/ANSYS/Calculix 输出文件，也不得为此引入新二进制依赖：B6 对照的"FE 侧"只能用解析/合成参考场，必须显式标注 |
| B5 报告 lint | **本轮未派工**（IR3_DISPATCH 无对应路径）：B5 不进入本轮判定，登记 not-evaluated |
| 三平台 CI（B4） | 未派工；CI 仍 Linux CPU 单平台（IR3-G3 只允许加 matplotlib 可选项） |
| metrics.json s4 段 | `benchmarks/metrology/metrics.json` **本轮无人持有独占路径**：任何代理写它都违反路径纪律。S4 门的登记场所改为各自报告 + 本文 §3 台账，metrics.json s4 段移交后续 |
| S1–S3 遗留 | schema 仍 `1.0.0-draft.2`（G6）；Zhang 标定升级（A6）、Stereo Challenge 数据（A5）、异机复算（C1）在 IR3 派工中同样无人持有——**这些在本循环内结构性关不掉**，见 §3.2 |

---

## 1. 门禁总表

责任代理与独占路径按 `IR3_DISPATCH.md`；规格输入为并行产出的 `IR3-F2-cli-contract.md`（CLI）、`IR3-F3-gui-scope.md`（GUI 范围）、`IR3-F4-fea-contract.md`（FEA），门槛与规格冲突时本文优先（本文与 R2-F1 冻结表冲突时 R2-F1 优先）。

### A 组 · CLI 全链（责任：IR3-O1，路径 `src/hl3/cli/run.py`、`src/hl3/cli/__main__.py`、`tests/test_cli_run.py`）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S4-CLI-1 入口存在** | `PYTHONPATH=src python3 -m hl3.cli run <args>` 可用，且 `python3 -m hl3.cli`（`__main__.py`）提供 run/validate 子命令分发；退出码 0=成功、非 0=失败；`--help` 可用。console script 注册涉及 pyproject（IR3-G3 独占），**不作门槛也不许 O1 顺手改** | `tests/test_cli_run.py` 子进程测试 |
| **G-S4-CLI-2 全链复用** | run 只包装 `hl3.pipeline`（dic2d 必做，dic3d 视配置），不重实现相关/应变/UQ 任何一步；产物经 `validate_file` 零 error；配置消费与 pipeline 参数一一对应，无 CLI 私有算法参数 | 测试 + 模块 docstring |
| **G-S4-CLI-3 确定性与溯源** | 同输入同参数双跑：位移/应变数据集逐位一致、`config_hash`/`input_hash` 相等；CLI 参数快照并入产物 provenance（口径沿 `_provenance`）；时间戳类字段按既有 schema 政策处理，不得因此放弃逐位断言 | 测试内双跑 + 产物读回断言 |
| **G-S4-CLI-4 失败语义** | 缺图像/坏配置/不可写输出 → 非零退出 + stderr 诊断，不留半成品文件；至少 3 种注入失败逐一被测 | `tests/test_cli_run.py` |
| **G-S4-CLI-5 validate 零回归** | 既有 `python3 -m hl3.cli.validate` 行为与 `tests/test_validate.py` 全部断言不变；`hl3.cli` 包导入保持无副作用、不依赖 numpy/h5py（`__main__.py` 必须惰性导入子命令实现） | 既有测试常绿 + 新增导入卫生测试 |
| **G-S4-B3 TTFR 锚点（B3）** | **正式门 = `pip install hl3` → 第一张应变云图 <15 min + 脚本化秒表 + 录屏**（R2-F1 冻结）。本环境无 PyPI 发布、无录屏回路：本轮只允许 (a) 仓库内脚本化秒表——干净 venv 本地安装（`pip install .[viz]`）→ 合成散斑 → `hl3.cli run` → `hl3.viz` 出图，实测墙钟时间入 O1 报告；(b) 正式门登记 evaluable=false + 原因。**仓库内秒表数字不得冒充 B3 正式成绩** | IR3-O1-cli.md 秒表记录 + 复跑命令 |

### B 组 · 无头出图（责任：IR3-O2，路径 `src/hl3/viz/**`、`tests/test_viz.py`）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S4-VIZ-1 无头渲染存在** | `hl3.viz` 在 Agg 后端（显式 `matplotlib.use("Agg")` 或等效）下从 schema 合规 HDF5 或 pipeline 结果对象渲染位移/应变云图，输出 PNG + 至少一种矢量格式（SVG/PDF）；全程无 DISPLAY、无 GUI 工具链导入 | `tests/test_viz.py` |
| **G-S4-VIZ-2 可选依赖纪律** | `import hl3` 及全部非 viz 模块不依赖 matplotlib；matplotlib 缺席时 `import hl3.viz` 给出含安装指引（`pip install hl3[viz]`）的清晰 ImportError；测试用 importorskip，无 viz extra 的环境全套件仍绿 | 测试 + 与 IR3-G3 CI 可选任务对账 |
| **G-S4-VIZ-3 计量出图诚实** | 云图带量名/单位色标；应变图必须随图注明 VSG（沿 `hl3.strain` 记账值，禁止无 VSG 的应变云图）；无效点（`Status` 非 OK）渲染为掩膜而非插值抹平；UQ 存在时 σ 场可出图，且主图不得把带不确定度的量画成无不确定度 | `tests/test_viz.py` 内容断言 |
| **G-S4-VIZ-4 测试口径** | 禁止跨 matplotlib 版本的像素哈希断言；判定改为程序化内容检查（图元/数组/元数据级），阈值写死在测试内；输出文件存在且非平凡大小 | 同上 |
| **G-S4-VIZ-5 非 iris 级声明** | 模块 docstring 明文：本模块是**无头出图基线**——无动画、无 4K/出版流水线对标、无 FEA 叠加打磨、无交互；出现任何"iris 级/对齐 iris/媲美 iris"字样即整体 fail（RUL-06，GAP-1 长尾） | docstring + L-2 式字符串扫描 |

### C 组 · FEA 对照最小链（责任：IR3-O3，路径 `src/hl3/fea/**` 及对应测试）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S4-FEA-1 假绿消除** | `src/hl3/fea/__init__.py` 与 `src/hl3/gui/__init__.py` 落地为**正规包**（含范围 docstring），空目录命名空间包的假绿被真实实现替换；冒烟从"空目录也能 pass"变为"导入即拿到公开 API" | 包文件 + `tests/test_s4_smoke.py` 常绿 |
| **G-S4-FEA-2 网格导入最小面** | 至少一种开放文本格式（VTK legacy ASCII 或等效）+ 数组直构 API 的 FE 网格导入；仅 numpy + 标准库，**不新增依赖**（pyproject 归 IR3-G3；Exodus/netCDF 明示超范围）；坏文件 → 清晰异常 | 单元测试 + docstring 范围声明 |
| **G-S4-FEA-3 DIC↔FE 双向投影** | DIC 点结果 → FE 节点插值与反向采样均存在；合成场往返误差上界实测后写死在测试内（禁止"足够小"断言）；网格外查询点显式无效标记 | 测试 |
| **G-S4-B6 同滤波链对比（B6 锚点最小版）** | 对 FE 侧场施加与 DIC 相同的等效 VSG/PLS 滤波后再比（复用 `hl3.strain`，不 fork）；输出机读对比报告含归一化残差（z 分数，σ 取自 UQ 链）；开孔板式案例单脚本复现。**正式 B6 需真实 FE 解算器输出：本轮 FE 侧为解析/合成参考场，报告必须标注 `fe_source: synthetic`，此门本轮最高成绩 = "最小链 pass + 正式门 evaluable=false"** | IR3-O3-fea-gui.md + 测试 + 案例脚本 |
| **G-S4-FEA-5 实测边界条件导出** | 边界节点集上的实测位移可导出为机读格式（CSV/JSON），字段含单位与坐标系声明；测试实际行使一次导出并读回 | 测试 |

### D 组 · 社区查看器基线（责任：IR3-O3，路径 `src/hl3/gui/**` 及对应测试；范围以 IR3-F3 为准）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S4-GUI-1 范围诚实** | `hl3.gui` docstring 明文"社区版基础查看器，**明确不是 iris 级**"（R3-F4 §3-S4 原文）；无工具链硬依赖——本环境 tkinter/PySide6 均缺席（§0.2 实测），导入 `hl3.gui` 在无工具链、无 DISPLAY 下必须安全 | docstring + 无头导入测试 |
| **G-S4-GUI-2 无头测试纪律** | 测试只做结构级断言（数据装载、视图状态、组件构造），工具链缺席时干净 skip 并给原因；禁止假装跑过交互 | 对应测试 |
| **G-S4-GUI-3 交互验证移交** | 交互走查在本环境**不可验证**：O3 报告必须登记 GAP-1 移交（beta 用户回路），不得出现"GUI 已验证可用"类宣称；违者整体 fail | IR3-O3-fea-gui.md 移交段 |

### E 组 · 冒烟 / CI / 汇总（责任：IR3-G2 冒烟、IR3-G3 CI 与 extras）

| 门 ID | 判据（二元） | 证据工件 |
|-------|--------------|----------|
| **G-S4-SMK-1 冒烟翻绿** | `test_s4_smoke.py` 的 `hl3.cli.run`/`hl3.viz` 两个 skip 随模块落地翻绿；`hl3.fea` 项在 G-S4-FEA-1 后为非空真绿 | pytest 输出 |
| **G-S4-CI-1 CI 可选项纪律** | CI 保持 Linux CPU 常绿；matplotlib 只作**可选**任务/步骤加入，无 viz extra 的最小依赖任务必须保留且绿；`pyproject.toml` 本轮改动仅限 `viz` extra（及 G3 报告所需最小项） | `.github/workflows/ci.yml` + diff 审计 |
| **G-S4-SUM-1 套件常绿** | Linux CPU、无网络、无 GPU 下全量 pytest 通过或按纪律 skip/xfail；**690 passed 基线不改一行断言全绿**；S4 新增测试总时长 ≤5 min（当前全套件 45 s，余量必须留给后续阶段） | pytest 输出 / CI 日志 |
| **G-S4-SUM-2 S4 出口即总结停止** | 出口 = CLI-1…5、VIZ-1…5、FEA-1/2/3/5、GUI-1…3、SMK-1、CI-1、SUM-1 全 pass，**且** B3/B6 两锚点各自为 pass 或"evaluable=false + 原因"登记，B5/B4 按 §3.1 登记 not-evaluated/未派工。存在未登记 fail → S4 不出口，父调度器不得进入总结（R3-F4 §7 熔断纪律同样适用于收官轮） | 本表全量核对 + 父调度器 `PROGRESS.md` |

---

## 2. 全局约束（随门禁生效，违反任一即该代理产出整体 fail）

1. **独占路径纪律**：`git add` 只用各自独占路径，禁止 `git add .`；`pyproject.toml` 与 `.github/workflows/ci.yml` 仅 IR3-G3 可动；`benchmarks/metrology/metrics.json`、`src/hl3/io/**`、`src/hl3/stereo/calibrate.py` 本轮**无人持有，任何代理不得改动**。
2. **范围红线**（IR3_DISPATCH 首行）：零 GPU 内核、零相机 SDK、零显微镜实现（GAP-5 fail-closed）；`fea`/`gui`/`viz` 新包 docstring 沿用既有范围排除句式。
3. **零 VIC 逆向**；不读写 `.z3d` 等专有格式；对比表述只引公开资料并标"厂商公开宣传值，未独立验证"；**iris 一词只允许出现在"不是 iris 级"的否定句式与公开资料引用中**（RUL-06）。
4. **阈值不可议**：B3 <15 min（正式口径含 pip install 与录屏）、B6 定义（网格导入 + 双向投影 + 同滤波链对比 + 边界条件导出）来自 R2-F1 冻结表；差距只能 xfail 或 evaluability 登记。
5. **合成不冒充**：仓库内 TTFR 秒表 ≠ B3 正式成绩；合成/解析 FE 参考场 ≠ 真实解算器输出；一切此类数字在报告中显式标注来源，混淆记 fail。
6. **报告首行**：每个 IR3 代理报告第一行 `ACTUAL_MODEL_SLUG: <slug>`，禁止静默降级。

---

## 3. 诚实台账：S4 收官时能宣称什么、不能宣称什么

### 3.1 B 组对账（R3-F4 §3-S4 的"4/6 在望"到底望到了哪）

| KPI | 本轮最高可达状态 | 登记 |
|-----|------------------|------|
| B3 TTFR | 仓库内脚本化秒表 pass；正式门（PyPI 安装 + 录屏）**evaluable=false** | O1 报告 |
| B4 跨平台 | **未派工**：CI 仍单平台 Linux，"B4 起步"都谈不上完成 | 本文 |
| B5 GPG 报告 lint | **未派工**：not-evaluated，无任何部分成绩 | 本文 |
| B6 FEA 闭环 | 最小链 pass（合成参考场）；正式门（真实 FE 输出）**evaluable=false** | O3 报告 |
| B1/B2 | S5/S6 范围，本循环明令不做 | 本文 |

**结论（禁止父调度器总结时改写）**：S4 收官后 B 组 **0/6 正式 PASS**。B3/B6 拿到的是"最小可验证证据 + 正式门缺口清单"，B4/B5 连这个都没有。R2-F1 超越公式在本循环结束时**不成立、也不接近成立**；合规表述只有一种："软件测量链地基完成（S1–S4 最小面），超越判定全部待后续阶段与用户侧资源。"

### 3.2 无主遗留（本循环结构性关不掉，父调度器总结必须逐条列出）

| 项 | 状态 | 缺口原因 |
|----|------|----------|
| G6 schema 1.0 冻结 | 仍 `1.0.0-draft.2` | IR2-F1 §3 曾写"随 Impl-R3 收口"，但 IR3 派工无人持有 `src/hl3/io/**` |
| A6 标定升级（Zhang + 光束法平差 + bootstrap Σ_cal） | 未做 | `calibrate.py` 连续两轮无主 |
| A5 官方 Stereo Challenge 成绩 | 数据未下载 | 预算/派工均未安排 |
| C1 异机复算 | 仅同机证据 | 单机环境，移交项 |
| GUI 交互验证 / iris 级可视化 | 基线≠打磨 | GAP-1，beta 回路不存在 |

### 3.3 一句话诚实定位（供最终总结引用）

S4 交付的是**无头产品链的最小闭环**：命令行进、带溯源与不确定度的数据出、无头出一张诚实标注的云图、FEA 侧有一条可复跑的最小对照链、GUI 有一个明确自称"不是 iris 级"的查看器骨架。它**不是 iris 级可视化、不是 VIC 替代品、不是超越成立**——是让后续 S5–S8 有地可站的地板。

---

*IR3-F1 完。本文只写入独占路径 `.agent_workspace/s1s4/IR3-F1-s4-gates.md`；引用键沿用 B1–B6、A5/A6、C1、G6、RUL-03/04/06/07/08、GAP-1/5/6、S1–S8。*
