ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast
<!-- SPDX-License-Identifier: Apache-2.0 -->

# IR4-O3：S1–S4 全量法律与合规扫描

## 0. 结论先行

**仍然干净。零阻断项。** S1–S4 全部产品源码、测试与文档中没有专有二进制、没有 OpenCorr 代码资产、没有逆向或许可绕过材料、没有 GPU 内核、没有相机 SDK、没有显微镜/SEM 畸变实现。七项指定关键词的全部命中都归入三类无害语境：**禁止性政策文本**、**公开竞品对标记录**、**断裂力学术语**。

S4 新增的 GUI / FEA / viz 三个包**没有引入新的知识产权风险**：没有抄 `iris`，没有借用受限色表，没有 UI 外观仿制面，字体与 PNG 编码器均为自建。但命名层面浮现出 **4 个需要在 S4 对外发布前处理的非阻断问题**，其中最实际的一个是 `hl3.gui` 与 README 许可证表中「后续商业 GUI 层」的命名空间重叠；另一个是项目自有的 **L-2 法律门按字面已经处于 FAIL 状态**（缺 allowlist 文件 + 一条自 S1 起未登记的良性命中）。详见 §5。

## 1. 扫描基线与范围

- Git 基线：`96c741cf78a24b4cc2ff62fdc2788ae2e6bd39b2`（`docs: assess VIC customer gaps in S4`），**外加扫描时工作树中全部未跟踪的 S4 文件**（`src/hl3/{viz,fea,gui}/`、`src/hl3/cli/{run,__main__}.py`、`src/hl3/__main__.py`、`tests/test_{viz,fea,gui,cli_run}.py`）与 `pyproject.toml` 的未提交改动。
- 范围：`src/hl3/` 35 个 `.py`（15,216 行）、`tests/` + `src/tests/` 19 个 `.py`（8,659 行）、`docs/`（1 个文件）、`benchmarks/`、`pyproject.toml`、`.github/workflows/`、Git 全历史对象，以及 `.agent_workspace/` 全部规划与审计文档。
- 与前三轮的差异：前序 `IR1-G1` / `IR2-G1` / `IR3-G1` 的 `rg` 未加 `--hidden`，因此**整个 `.agent_workspace/` 目录被 ripgrep 的隐藏目录规则跳过**。本轮全部检索均加 `--hidden --no-ignore` 重跑，这也是本轮能发现 §5 F1 的原因。
- 功能证据：`CUDA_VISIBLE_DEVICES='' pytest tests src/tests -q` → **700 passed in 46.09s**；其中 fail-closed 法律门 `test_env_guards.py`（2 项）与 `test_stereo_synth.py::test_stereo_package_ships_no_distortion_implementation` 全绿。

## 2. 七项指定关键词逐条判定

| 关键词 | shipped 树（src/tests/docs/benchmarks） | 判定 |
|---|---|---|
| `opencorr` | 2 条，均为 README 及其 `PKG-INFO` 镜像的「不 vendor、不改写、不翻译」边界声明 | **PASS** |
| `iris` | **0 命中** | **PASS** |
| `vic-3d` / VIC 家族 | 3 处：`test_env_guards.py` 的环境变量守卫名、README 与 `PKG-INFO` 的商标免责声明 | **PASS** |
| SEM / 显微镜畸变 | 0 实现。仅 schema 枚举与「不实现」范围声明 | **PASS** |
| GPU / `.lib` | 0 原生库、0 GPU 后端 | **PASS** |
| eval key / 许可密钥 | 0 命中（仅禁止性文本） | **PASS** |
| `crack` | 1 条实体命中：`icgn.py:946` 的断裂力学术语 | **PASS（内容）／见 F1（流程）** |

### 2.1 OpenCorr

`src/`、`tests/`、`benchmarks/`、`docs/`、`pyproject.toml` 中零代码资产。仓库无 `vendor/`、`third_party/`、`external/` 目录，无任何 C/C++/CUDA 源文件。`.agent_workspace/` 内约 20 条命中全部是 ADR-LIC-001 §2 的禁止性裁决文本（"不得复制、改写、翻译、生成或 vendor 任何 OpenCorr 源文件"）、R2-F1 的 RUL-01 裁决，或 `research/oss_dic_landscape.md` 的公开生态调研表格。**没有一条构成复用。**

### 2.2 iris

`iris` 是 Correlated Solutions 的可视化引擎名。在 `src/ tests/ docs/ benchmarks/` **零命中**——这正是本项检索的价值所在：S4 新增的可视化包命名为 `hl3.viz`，其色表名取自 matplotlib（`viridis`/`gray`/`bwr`），**没有采用、缩写或影射 `iris`**，也没有出现 `vicpyx`、`vic-snap`、`vic-gauge`、`.z3d` 等专有产品/格式串。`.agent_workspace/` 内的 `iris` 命中全部位于研究与规划文档，且已按 **RUL-06** 强制挂「公开资料推断 + 置信度」标签，明文规定"永不进入'已对齐'清单"。

### 2.3 VIC 家族与逆向痕迹

- `tests/test_env_guards.py` 断言 CI 不运行于 Windows、不存在 `HL3_VIC_HOME` / `VIC_2D_HOME` / `VIC_3D_HOME`——这是**防御性**用法，越界即测试失败。
- 无专有工程格式解析、无反编译、无密钥生成、无许可证绕过、无 UI 仿制资产。
- **L-3（专有手册文本污染）复核**：抽查 `src/` 全部 docstring 与注释，未发现任何"VIC 内部如何做"式表述；算法描述一律指向公开文献、规格章节号或 iDICs 公开实践。
- 本轮新落地的 `.agent_workspace/s1s4/IR4_G2_customer_gap.md` 是一份 VIC↔HL3 对比文档，需单独审：它在第 9 行明写"以下 VIC 能力均只按公开产品资料描述，未在本环境独立验证"，且全文论证方向是 **HL3 不如 VIC**（自贬而非贬损竞品），不构成虚假比较广告或商誉侵害。唯一需要注意的是它引用了 VIC-Snap / VIC-Gauge / iris / DMT 等产品名——若该文本将来外发，必须随附 README 那段商标与指称性合理使用声明（见 F6）。

### 2.4 SEM / 显微镜畸变（RUL-04、L-7、专利 fail-closed）

- Python 源码中**没有**以 distort / brown / conrady / radial / tangential / prism / fisheye / telecentric / microscop 命名的函数或类定义。
- `stereo_microscope`、`telecentric`、`brown_conrady_k3p2`、`brown_conrady_k6p2s4` 仅作为 `hdf5_schema.py` 的**枚举字符串与参数长度元数据**存在（`DISTORTION_PARAM_COUNT["stereo_microscope"] = None`），没有任何计算分支绑定它们；`docs/schema-hdf5.md` 同理，是格式规范而非实现。
- 立体链声明并实现纯 pinhole L0：`match.py` 记录 `"distortion_model": "none_pinhole_l0"`，`dic3d.py` 记录 `"pinhole_L0"`，两者均有测试锁定。
- `test_stereo_package_ships_no_distortion_implementation` 同时检查**定义不得存在**与**免责 docstring 不得删除**（"删掉声明"不能成为让测试通过的路径），本轮通过。

### 2.5 GPU 与二进制库

- 全工作树按 `.exe/.dll/.msi/.msix/.lib/.a/.o/.bin/.so/.dylib/.zip/.7z/.rar/.tar/.gz/.whl/.pyd/.cu/.ptx/.cl/.cpp/.c/.h` 扫描：**零候选**。无文件 > 10 MB。
- Git 全历史最大 blob 为 90,226 B（`round1/R1-O1-hl3-2d-spec.md`），> 100 KB 的 blob 数为 **0**——与公开所述约 184 MB / 225 MB 的 VIC 安装包不存在任何量级相符的历史对象。
- ADR-LIC-001 §3 点名禁用的 `OpenCorrGPU.lib` 及配套 `.dll`：零命中（仅存在于该 ADR 的禁止条款本身）。
- `src/` 无 CuPy / PyTorch / JAX / Numba / OpenCL 导入。**注意一类必然的假阳性**：朴素的 `.lib` 检索会命中 `strain/pls.py:55` 与 `uq/propagate.py:69` 的 `from numpy.lib.stride_tricks import sliding_window_view`——那是 NumPy 的纯 Python 子模块，不是二进制库。
- 相机 SDK（GenICam/GenTL、Basler pylon、FLIR Spinnaker、Harvesters）零命中；`hl3.capture.mock` 仍是纯软件合成采集。`cli/run.py:281` 的参数组名 "synthetic source (no files, no cameras)" 是唯一的 camera 字样，属反向声明。
- CI（`.github/workflows/ci.yml`）显式置空 `CUDA_VISIBLE_DEVICES`，无 Windows/macOS runner。

### 2.6 评估密钥 / 许可绕过

`eval key`、`license key/server/bypass`、`keygen`、`serial`、`activation`、`dongle`、`decompile`、`disassemble`、`破解`、`盗版`、`注册机`、`序列号`、`密钥` 全仓检索：**全部命中均为禁止性政策文本**（LEGAL.md、README、PKG-INFO、各轮 ADR 与门定义），无一为实现、脚本或获取记录。LEGAL.md 记录的「12 字符 PC 专属密钥 + 30 天评估许可」来自 Correlated Solutions 公开下载页，且结论明确为"本环境不能合法完成该 Windows 许可闭环"。

### 2.7 crack

唯一的实体命中是 `src/hl3/correlate/icgn.py:946`：

> `inside one subset (bending, the neighbourhood of a crack tip or a hole)`

这是**断裂力学的裂纹尖端**，讨论的是子集内位移场非线性会超出一阶形函数的表达能力，与软件破解无关。`.agent_workspace/` 内的 `裂纹` 命中同样全部是力学语境（裂纹场覆盖率门 G2D-7、COD 虚拟引伸计路线、NaN 裂纹带测试设计）。**内容上完全无害**——但它在流程上触发了 F1。

## 3. 对项目自有法律门 L-1…L-7 的复核

| 门 | 定义（R2-F4 §L） | 本轮判定 |
|---|---|---|
| L-1 | VIC 二进制/安装包/大文件 | **PASS** — 无 PE/MSI，无 >10 MB 文件，历史无 >100 KB blob |
| L-2 | 专有字符串/逆向痕迹 + allowlist 登记 | **形式 FAIL / 实质 PASS** — 见 F1 |
| L-3 | 专有手册文本污染 | **PASS** — `src/` 注释无厂商实现细节声称 |
| L-4 | 依赖许可证矩阵（SBOM） | **PASS（有缺口）** — 无 copyleft 运行时依赖；清单不完整，见 F2 |
| L-5 | 数据集入库 | **PASS** — 仓内无 Challenge 数据本体；`benchmarks/metrology/metrics.json` 为自生成指标 |
| L-6 | 声明一致性 | **PASS（一处待补）** — 无"实测优于 VIC"、无"已对齐 VIC UI"；见 F7 |
| L-7 | 显微镜模块零代码 | **PASS** — 门的 FAIL 条件是 `src/` 存在**实现**；现有命中全为范围声明、schema 枚举与门测试正则自身 |

### 依赖许可证矩阵（L-4 展开）

| 依赖 | 声明位置 | 许可证 | 兼容性 |
|---|---|---|---|
| numpy ≥1.24 | 运行时 | BSD-3-Clause | ✅ |
| pytest ≥7 | extra `test` | MIT | ✅ |
| matplotlib | extra `viz`（S4 新增） | Matplotlib License（BSD/PSF 系） | ✅ 未 vendor，非核心运行时 |
| h5py ≥3.8 | extra `hdf5` | BSD-3-Clause | ✅ |
| blake3 ≥0.3 | extra `hash` | Apache-2.0 / CC0 双授权 | ✅ |
| **Pillow** | **未声明**，`cli/run.py:228` 软导入 | MIT-CMU (HPND) | ✅ 许可无冲突，声明缺失 → F2 |
| **hdf5plugin** | **未声明**，`hdf5_schema.py:587` 软导入 | MIT（内含 BSD/MIT 系编解码器） | ✅ 许可无冲突，声明缺失 → F2 |

**无强 copyleft 运行时依赖，与 ADR-LIC-001 的宽松许可选型一致。**

## 4. S4 新增 GUI / FEA / viz 命名风险专项

用户核心问题。逐包结论如下。

### 4.1 `hl3.viz` — 无新增风险，但有一项应当归档的第三方归属

三条独立的检查线全部清白：

1. **色表数据来源。** `viridis` 的 33 个锚点是 Nathaniel J. Smith 与 Stefan van der Walt 的 **CC0 公共领域**数据，模块 docstring 已具名致谢；`gray` 与 `bwr` 是端点间的线性 ramp，属**构造式定义**（`((0,0,0),(255,255,255))`、`((0,0,255),(255,255,255),(255,0,0))`），不承载可版权表达。MathWorks 的 `parula`、MATLAB 的 `jet` 等受限色表**零命中**——查过了，不在仓内。
2. **命名策略经得起推敲，而且作者自己划了线。** 用 matplotlib 的名字承载自建的表，法律上属接口兼容（描述性通用名 + matplotlib 本身为 BSD 系许可，非商标性使用）。更值得记的是 docstring 里那条自我约束：`coolwarm` 等「既非公式、又非公共领域数据」的表**被刻意留空而不是近似后借名**——"一张偏差 5% 却答应同一个名字的表，比一张缺失的表更糟，因为只有后者是可见的"。这条纪律同时挡住了法律风险与计量误导。`viridis` 的 3/255 最大偏差也已在 docstring 中量化披露。
3. **自建资产无外部血统。** PNG 编码器按 PNG 规范直写（stdlib `zlib` + `struct`，IHDR/IDAT/IEND，filter-0），Netpbm 同理；色标数字标签用的 3×5 点阵字体是模块内手写的 ASCII 艺术（19 个字形，只覆盖 `format(x,'.4g')` 能产生的字符），**没有引入任何字体文件**，因而不触及字体授权。

唯一动作项：CC0 归属目前只活在 docstring 里，仓库没有 `NOTICE` 或 `THIRD-PARTY` 文件承载它（F2）。

### 4.2 `hl3.fea` — 无 IP 风险，风险在措辞而非代码

纯 NumPy 的重心坐标定位、节点投影与 CG 求解，全是教科书有限元几何，无外部代码血统。命名上的隐患是"FEA"这个标签比实际能力大——而**这一条源码里已经防住了**：`fea/__init__.py` 的 docstring 用三段明列"本包不做什么"，其中"投影不是求解器，把两者混为一谈正是 RUL-05 这条规则存在的理由"一句，直接把 R2-F1 的裁决写进了模块文档。`IR4_G2_customer_gap.md` 第 51 行也据实写明"FEA 不是闭环，只是几何小工具"。

结论：代码层面无新增风险；风险窗口在 S4 对外发布的措辞（F6）。

### 4.3 `hl3.gui` — 两个真实的命名问题（均非阻断）

**外观仿制面为零。** 整个包 133 行：一个多边形 AOI 的 JSON 边车（`aoi.py`，纯几何 + 射线法点在多边形内判断，不依赖任何 GUI 工具包），加一个只做依赖探测的 `viewer.py`——它检查 matplotlib 与 tkinter 可导入，然后明确打印"interactive session is not started"。**没有窗口布局、没有菜单树、没有图标、没有工具栏、没有配色方案**，也就没有任何可能与 VIC 桌面构成商业外观（trade dress）相似的表面。RUL-06「从未合法见过 VIC UI」的前提保持成立。

但有两点需要处理：

- **F4：命名空间与开源/商业许可边界重叠。** README 许可证表把「后续商业 GUI / 采集 / 许可管理层」归为 `LicenseRef-HL3-Commercial`，并强调其为"独立组件，不受根 Apache-2.0 自动覆盖"。现在 `src/hl3/gui/` 出现在 Apache-2.0 树内、且三个文件都带 `SPDX-License-Identifier: Apache-2.0` 头——**今天不存在歧义**（逐文件声明是清楚的），但"商业 GUI 层"与"开源 `hl3.gui`"共用同一个自然语言标签，会让未来陈述 open-core 边界变得别扭。`gui/__init__.py` 已自称"Community GUI baseline"，说明作者有这个意识；建议把这层区分固化进 README 许可证表，并让任何商业层落在独立分发名/命名空间（如 `hl3-studio` / `hl3_studio`）下。
- **F6 的一半：** 133 行的 AOI + 依赖探针，在发布说明里**不能**被写成"GUI"。

### 4.4 顺带核查：项目名与分发名

`hl3` 在 PyPI 上未被占用（`/pypi/hl3/json` → 404），无抢注冲突。名称本身与 DIC 领域无在先商业标识冲突。

## 5. 发现与建议

零阻断项。以下按严重度排序。

**F1（中低・流程）L-2 门按字面已处于 FAIL 状态。** R2-F4 定义的 L-2 门要求：`src/ tests/ benchmarks/ docs/` 上跑 `rg -i '(\.z3d|vic-snap|vic-gauge|keygen|crack|license.{0,10}bypass|patch.{0,10}serial)'`，且 `.agent_workspace/` 与 `docs/` 中的合理命中"须在白名单文件 `legal/scan-allowlist.txt` 中逐条登记路径+行号+理由；未登记的命中一律 FAIL"。实际情况：(a) **`legal/` 目录根本不存在**，allowlist 从未建立；(b) 该正则现在在 `src/hl3/correlate/icgn.py:946` 有一条命中（`crack tip`），而 round3 的 `R3-F2-claims-legal-scan.md` 曾记录"0 命中"——该行由 S1 阶段的 `3fa436f`（二阶 IC-GN）引入，位于 R3-F2 扫描基线之后，其后的 IR1/IR2/IR3 三次法律扫描都没有重跑这条正则，因而漂移未被发现。**内容零风险，制度需要收口。** 建议二选一：建立 `legal/scan-allowlist.txt` 并登记该行与理由（断裂力学术语），或把正则收紧为词边界并排除力学语境（如 `crack(?!\s+tip)` 或改用 `crack(ed)?\s*(exe|patch|version)`）。前者更符合门的原始设计意图。

**F2（低・合规资产）第三方许可清单不完整。** Pillow 与 hdf5plugin 是被软导入但未在 `pyproject.toml` 声明的可选依赖；两者许可（MIT-CMU、MIT）都与 Apache-2.0 无冲突，因此**不是许可冲突，是清单缺口**——SBOM 与 L-4 门都依赖这份清单的完整性。同时仓库没有 `NOTICE` / `THIRD-PARTY` 文件来承载 viridis 的 CC0 归属（目前只在 docstring 中）。建议：把 `pillow` 加入新 extra（如 `images`）或 `viz`，把 `hdf5plugin` 加入 `hdf5`，并新建一个 `THIRD-PARTY.md` 收录上表 + viridis 的 CC0 致谢。

**F3（低・门覆盖）fail-closed 源码门只盯着 `hl3.stereo`。** `test_stereo_package_ships_no_distortion_implementation` 的扫描集是 `Path(stereo.__file__).parent.glob("*.py")`——S4 新增的 `hl3.viz`、`hl3.fea`、`hl3.gui`、`hl3.cli` 四个包**全部在门外**。今天它们干净，但门不覆盖就等于以后不设防。另有一个结构性空白：`test_env_guards.py` 只约束**运行环境**（非 Windows、无 VIC 变量、CPU-only），**没有任何源码级的门会因为有人写下 `import cupy` 或引入相机 SDK 而失败**——而这两项恰是 Impl-R3 明令禁止的。建议把畸变门升级为全包扫描，并新增一条禁止导入门（GPU 后端 + 相机 SDK 白名单外导入即 FAIL）。

**F4（低・命名）`hl3.gui` 与商业 GUI 层的标签重叠。** 见 §4.3。

**F5（信息・卫生）SPDX 头覆盖 37/54。** 17 个文件缺头，全部是 S1/S2 期产物（`hl3/__init__.py`、`capture/*`、`correlate/*`、`stereo/{__init__,calibrate,triangulate}.py` 及 8 个测试）——S4 新增的**源码**文件全部带头，只有 `tests/test_s4_smoke.py` 漏了。根 `LICENSE` 与包元数据都已声明 Apache-2.0，所以这不是授权瑕疵，只是逐文件可追溯性不一致。建议一次性补齐。

**F6（信息・发布纪律）README「尚未实现」表已与 S4 脱节，补写时的措辞是真正的风险点。** 该表目前仍写着应变、UQ、`hl3` 命令行、GUI"未做"，而 `hl3.strain`、`hl3.uq`、`hl3.cli.{run,validate}`、`hl3.gui` 都已存在。**低报本身没有法律风险**（虚假宣传的风险方向是高报），但更新它的那一刻就是风险窗口：`hl3.gui` 必须写成"社区版 AOI 边车 + 查看器依赖探针"而非"GUI"，`hl3.fea` 必须写成"DIC↔FE 几何投影"而非"FEA 闭环"，`hl3.viz` 必须保留"内建后端 viridis 与 matplotlib 存在 ≤3/255 偏差"的披露。若 `IR4_G2_customer_gap.md` 的对比内容外发，需随附 README 那段商标与指称性使用声明。

**F7（信息）`770 POI-solves/s` 被引用时未附硬件清单。** 该数字源自 `IR1-O3-pipeline.md`（4 帧 × 36 POI、单线程纯 NumPy），在 `IR4_G2_customer_gap.md:29` 被复引时标注了"没有正式吞吐 benchmark"，但按 L-6 与 ROUND1_BRIEF 缺陷 3 的裁决，任何吞吐数字都应挂 R1-G2 协议与完整硬件清单（本仓为 4 vCPU、无 GPU 云主机）。该数字用于论证 HL3**更慢**，实际误导风险极低，补一句宿主说明即可。

## 6. 总判定

**PASS。相对 IR1-G1 / IR2-G1 / IR3-G1 的结论没有反转：仓库依然是干净的独立实现。** 本轮在更大的扫描面（首次覆盖 `.agent_workspace/`）与更严的判据（复核项目自有的 L-1…L-7 门）下，未发现任何专有资产、逆向痕迹、许可冲突或受限实现。S4 的 GUI / FEA / viz 三个包没有带来新的知识产权风险——`iris` 未被沿用、色表数据为 CC0 或构造式、字体与编码器自建、GUI 外观面为零。

七个待办中没有一个会阻断 S4 合并：F1 与 F3 是**门的收口**（制度先于内容失效，现在补最便宜），F2 是**合规资产补全**，F4/F6 是**发布前的措辞与命名纪律**，F5/F7 是卫生项。

本判定针对上述基线提交与扫描时的工作树快照，**不为扫描后新增的文件提供前向豁免**；F3 指出的门覆盖缺口意味着新包的持续合规目前依赖人工扫描而非自动门，这正是建议优先修补它的原因。本任务只创建本报告，未修改任何产品源码。
