ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# R3-F2 — Claims & Legal Scan（全仓扫描）

- **扫描时间**：2026-08-28（Round 3）
- **扫描范围**：`/workspace` 全部工作区（含未跟踪的 `build/`、`__pycache__`、缓存目录）、git 全历史（`rev-list --all`，含全部分支与 stash）、当前暂存区。
- **扫描维度**：① VIC 二进制 ② OpenCorr 复制源码 ③ 显微镜实现 ④ 破解密钥 ⑤ 无协议的"比 VIC 快"类夸大宣称。
- **判定依据**：`LEGAL.md`、`round2/R2-F1-sota-reconciliation.md`（RUL-03 / RUL-04 / N1–N3 / 禁止宣称清单）、`round2/R2-G1-license-adr.md`（ADR-LIC-001）、`round2/R2-F4-r3-gates.md`（L-2 门）。

## 结论：**PASS**（5/5 维度全部干净；2 项非阻塞观察项见 §7）

---

## 1. VIC 二进制 — CLEAN

- **工作树**：对 `.git` 外全部文件做 `file --mime-type` 分类，非文本文件仅为本地 `__pycache__/*.pyc`、`.ruff_cache/*`（均被 `.gitignore` 排除，未跟踪）。无 `.exe/.dll/.msi/.msix/.lib/.so/.bin/.zip` 等任何安装包或库文件。
- **git 全历史**：`git rev-list --objects --all`（含 10+ 分支与 stash）中**不存在任何 >100 KB 的 blob**——184 MB/225 MB 级的 VIC 安装包从未进入过历史。56 个跟踪文件全部为文本（Python/Markdown/TOML/YAML）。
- **stash 检查**：唯一 stash（`r2-shared-checkout-wip`）仅含 `MASTER_PLAN.md` 与 `triangulate.py` 的文本改动。
- 代码中出现的 "VIC" 字符串仅在 `tests/test_env_guards.py`，且是**防御性守卫**（断言 CI 非 Windows、`VIC_2D_HOME`/`VIC_3D_HOME` 等环境变量不得存在），与 LEGAL 边界同向。

## 2. OpenCorr 复制源码 — CLEAN

- `src/`、`tests/`、`benchmarks/`、`build/` 中 **零** OpenCorr 命中；仓库无任何 C/C++ 文件、无 vendor/third_party 目录（纯 Python + NumPy）。
- "OpenCorr" 仅出现在 `.agent_workspace/` 规划与审计文档及 `README.md` 中，语境全部为：引用其论文、对标其公开结果、或**禁止复制**的政策文本（ADR-LIC-001 / RUL-01 / N2）。
- `src/hl3/correlate/icgn.py` 模块头明确声明 "Only NumPy is required. No GPU, no external DIC code."，算法出处为公开文献（R1-O1 规格 §9 引用）。README §法律声明重申"不 vendor、不改写、不翻译 OpenCorr 等 MPL/copyleft 项目的任何源文件"。
- 与同轮独立扫描 `round3/R3-G1-sbom-legal.md`（"No vendored OpenCorr — PASS"）交叉一致。
- 顺带核验 Ncorr / DICe / muDIC / ALDIC：`src/` 中的 "DICe" 命中均为 `drop_indices` 的大小写误匹配（假阳性），无任何第三方 DIC 代码。

## 3. 显微镜实现 — CLEAN（严格符合 RUL-04）

- **零实现代码**：`src/hl3/stereo/calibrate.py` 与 `triangulate.py` 的 docstring 均明确写出 "No non-parametric distortion field / stereo microscopy … Blocked behind the written patent-clearance opinion … intentionally absent"。无显微镜畸变数学、无伪代码、无测试向量、无原型。
- **唯一命中**：`src/hl3/io/hdf5_schema.py` 中 `"stereo_microscope"` 作为畸变模型枚举字符串出现两处，参数计数登记为 `None`（"长度由 @model_params 决定"），`docs/schema-hdf5.md` L216 同样只是 schema 表行。**这正是 RUL-04 第 3 条显式豁免的情形**："`DistortionModel::StereoMicroscope` 枚举值可以存在但无任何实现绑定（保留 schema 槽位不等于实现）"。无任何代码路径消费该枚举做校正计算。
- `build/lib/`（未跟踪的旧构建副本）中的对应文件携带相同的"intentionally absent"声明，无额外内容。

## 4. 破解密钥 — CLEAN

- 对 `crack / keygen / serial / license key / activation / bypass / 破解 / 密钥生成` 的全仓大小写不敏感扫描：所有命中均为 `LEGAL.md`、`README.md`、各轮报告中的**禁止性政策文本**（"不得破解、不得生成密钥、不得绕过许可证"）或 R2-F4 L-2 门对扫描正则本身的定义。
- 序列号形态扫描（`XXXX-XXXX-XXXX` 类分段串、≥24 位十六进制串，排除 SPDX/哈希语境）：**零命中**。无任何真实密钥、序列号、激活码或 keygen 工件。
- `LEGAL.md` 提到"12 字符 PC 专属密钥"仅为对官方评估**流程**的公开信息描述，非密钥材料。

## 5. 夸大宣称（"faster than VIC" 无协议）— CLEAN

- **英文 "faster (than VIC)"**：`.agent_workspace/` 之外零命中；`.agent_workspace/` 内的命中全部是 RUL-03 / N3 / G2 协议对该表述的**禁止条款**（元引用，非宣称）。
- **README.md（对外门面）**：吞吐指标明确写"一律**未经测量**……任何性能数字必须按 R1-G2 公平对比协议给出硬件清单后才允许公布"（L54）；并载有完整非关联声明与 clean-room 声明（L75–89）。无任何已达成的性能/精度对比宣称。
- **中文"超过/超越 VIC"**：全部位于规划文档（MASTER_PLAN、R1/R2 规格与路线图），语境为**协议绑定目标**（target）而非已达成宣称（claim），与 RUL-03 第 2 条"降格为协议绑定目标"一致；R2-G2 与 R1-G2 明文重申"没有测吞吐，不能声称 HL3 比 VIC 快或慢"。
- **VIC 公开数字的引用**（"32 核 1×10⁶ 点/秒"）：一律标注"厂商公开宣传值，未独立验证 / 非同机不可直接排序"，符合禁止宣称清单第 2 条。
- **新增基准工件**（本轮 R3-G2 已暂存的 `benchmarks/metrology/metrics.json` + 报告）：内容为 CPU-only 精度/噪声指标，带环境披露（`device: cpu`、`CUDA_VISIBLE_DEVICES=''`），**无任何 VIC 对比或吞吐排序**——合规。
- `src/`、`tests/`、`docs/` 中无 `.z3d`、`vic-snap`、`vic-gauge`、`vicpyx`、`iris` 等专有工程格式/产品字符串（R2-F4 L-2 正则在 `src/ tests/ benchmarks/ docs/` 四目录**零命中**）。

## 6. 扫描方法摘要（可复跑）

| 检查 | 命令要点 | 结果 |
|------|---------|------|
| 非文本文件 | `find`(排除 `.git`) + `file --mime-type` | 仅本地缓存 .pyc/ruff |
| 历史大 blob | `git rev-list --objects --all` + `cat-file --batch-check`，阈值 100 KB | 0 个 |
| 跟踪二进制扩展名 | `git ls-files` + 扩展名正则 | 0 个 |
| OpenCorr/第三方 DIC | `rg -i` 于 src/tests/build | 0（假阳性已排除） |
| 显微镜 | `rg -i microscop` 全仓 + 逐处人工核验 | 仅 schema 槽位 + "intentionally absent" 声明 |
| 密钥/破解 | 词表扫描 + 序列号形态正则 | 仅政策文本 |
| 夸大宣称 | 中英文对比句式扫描 + README 全文人工审读 | 仅目标/禁止条款语境 |
| L-2 门正则 | `rg -i '(\.z3d|vic-snap|vic-gauge|keygen|crack|license.{0,10}bypass|patch.{0,10}serial)'` 于 src/tests/benchmarks/docs | 0 命中 |

## 7. 非阻塞观察项（不影响 PASS）

1. **`legal/scan-allowlist.txt` 尚不存在**（R2-F4 L-2 门为 `.agent_workspace/`、`docs/` 中的竞品词条命中预设的登记文件）。因 L-2 正则在其扫描范围（`src/ tests/ benchmarks/ docs/`）内为零命中，该门本轮**空真通过**；但建议 R3-F1/父调度器落一个空白允许清单文件，使后续 CI 化扫描有登记锚点。
2. **`MASTER_PLAN.md` L5–6 "对标并超过 VIC-2D 8 / VIC-3D 11"**：目标语态，属 RUL-03 允许的 target 表述；但 R2-F4 §4 要求任何对外"超越 VIC"表述必须附带差距表。MASTER_PLAN 为内部规划文档且 L33 已收录 RUL-03 约束，判定合规；若该句未来进入对外材料（README/官网），须挂差距表或改为"对标"。

## 8. 判定

| 维度 | 判定 |
|------|------|
| VIC 二进制（工作树 + 全历史 + stash + 暂存区） | **PASS** |
| OpenCorr 复制源码 / vendor | **PASS** |
| 显微镜实现（RUL-04 零实现线） | **PASS** |
| 破解密钥 / keygen / 许可绕过工件 | **PASS** |
| 无协议"比 VIC 快"类宣称（RUL-03 / N3） | **PASS** |

**总判定：PASS。**
