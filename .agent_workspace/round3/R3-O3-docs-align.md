ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# R3-O3 · README 与文档对齐实测报告

- **子代理**：R3-O3（opus-fast），Round 3 / 3，4 fable + 3 opus-fast + 3 gpt-sol 编制
- **独占路径**：`README.md`、`docs/**`、`round3/R3-O3-docs-align.md`
- **分支**：`cursor/r3-o3-docs-align-6edb`（从 `cursor/dic-sota-plan-259d` 切出）
- **纪律**：**未改动** `src/hl3/correlate/**`、`src/hl3/stereo/**`、`src/hl3/io/*.py`、`tests/**`、`pyproject.toml`、`.github/**`。`git add` 逐文件指定，未用 `.`。

---

## 0. TL;DR

旧 README 是 Round 2 中途写的（提交 `a5e4e8f`），此后 R2-O2 的 `calibrate.py`、R2-G2 的实测数字和 schema 的 `-draft.2` 都已落地，README 没跟上。本轮把 README 重写为**逐条可复核**的版本：

- 状态由「Round 2 / 3」改为「Round 3 / 3（收尾轮）」，并写明 **87 个测试**及其按模块拆分（ICGN 21 / stereo 32 / schema 23 / mock capture 9 / env guards 2），全部是 `pytest --collect-only` 实数，不是估计。
- 模块表由 4 行扩到 6 行，补上此前 README 里完全缺席的 `src/hl3/stereo/calibrate.py`（1098 行）与 `tests/test_env_guards.py`，并把每个模块的能力写到「能对着源码逐项打勾」的粒度。
- 新增「已实测的数字」小节：7 项数字全部标注出处（R2-O1 / R2-O2 / R2-G2 / 本轮复跑）与对应的回归断言，并保留「吞吐一律未测量」这条红线。
- 「尚未实现」由一段散文改成分方向的表，纠正了旧文「标定求解未实现 / 不确定度传播未实现」这两处**低于事实**的表述（线性 DLT 反解与两处协方差传播其实已经有了）。
- `docs/schema-hdf5.md` §12 补「实现现状」段：`hl3` 命令行、`diff`、`repack`、`spec/conformance/` 都还不存在，规范版本仍是 `1.0.0-draft.2`，只加说明不动规范性要求（修订记录 A-7）。

改动后 `python3 -m pytest -q tests src/tests` 仍为 **87 passed**。

---

## 1. 交付物

| 文件 | 改动 |
|---|---|
| `README.md` | 重写：状态、模块表、测试计数、实测数字、未实现清单、文档索引、法律小节的可测断言 |
| `docs/schema-hdf5.md` | §12 增「实现现状」段；§14 增修订记录 A-7。版本号未动 |
| `.agent_workspace/round3/R3-O3-docs-align.md` | 本报告 |

提交：`ec0bb94`（单一提交，仅上述前两个文件）。

---

## 2. 逐条对齐：旧 README 断言 → 代码事实 → 处置

| # | 旧 README 的说法 | 代码事实（本轮核实） | 处置 |
|---|---|---|---|
| D-1 | 「当前状态：Round 2 / 3」 | `PROGRESS.md` 的 Round 2 为 COMPLETE，Round 3 IN_PROGRESS；`round3/DISPATCH.md` 已存在 | 改为「Round 3 / 3（收尾轮），预 alpha」 |
| D-2 | 没有任何测试数量 | `pytest --collect-only`：87 个，分布 21/32/23/9/2 | 状态段与模块表都给出计数，并注明「对应当前提交」 |
| D-3 | 模块表只列 `stereo/`，描述为「针孔投影、由投影矩阵解析求基础矩阵、四档三角化」 | `stereo/` 是两个文件：`triangulate.py`(474) 与 `calibrate.py`(1098)。后者含 DLT resection、RQ 分解、Umeyama、误差度量、端到端实验驱动，README 完全没提 | 拆成两行，并各自写明「纯 L0 针孔、无畸变」「只有线性 DLT，不是 Zhang」 |
| D-4 | 「尚未实现：**标定求解**」 | 已有 `resection_dlt()` + `decompose_projection()`：从已知三维靶点线性反解相机并还原 `K,R,t`。缺的是 Zhang 平面法、角点检测、畸变、LM 束调整、`Σ_cal` | 改为「只有基于已知三维靶点的线性 DLT 反解」，逐项列出真正缺的东西 |
| D-5 | 「尚未实现：**不确定度传播**」 | `ICGNParams.compute_covariance` 输出逐点 `(n,6,6)`＝`2σ²(JᵀJ)⁻¹`；`triangulation_covariance()` 输出逐点 `3×3`，且与 Monte-Carlo 比值 0.994–0.998 | 改为「已有匹配项，缺标定项 `Σ_cal` 与端到端链路」；「为什么再做一个 DIC」表里也补了同一句 |
| D-6 | 相关器只写「ZNSSD 判据、B 样条插值」 | 还有：FFT-CC 整像素初值搜索、四阶中心差分参考梯度、Cholesky + 对角加载、7 种状态码、收敛后按最终 warp 重算 ZNCC | 模块表补全，措辞与 `icgn.py` 模块 docstring 一致 |
| D-7 | 「schema…参考读写器 + **一致性测试套件**」 | 有 23 个 pytest 测试与 `validate_file()`，但**没有** `spec/conformance/` 样例集、没有 `hl3` CLI | README 改为「结构验证器」，另在 schema 文档 §12 写明实现现状 |
| D-8 | 安装命令用 `python`，且未说明零安装路径 | 本机 `python` 不存在，只有 `python3`；`pyproject` 的 `pythonpath = ["src"]` 让 `PYTHONPATH=src` 直接可跑 | 全部改 `python3`，补一句零安装用法与依赖分层（h5py 可选、blake3 缺失降级） |
| D-9 | 「吞吐指标一律未经测量」，但没有任何已测数字 | R2-O1 / R2-O2 / R2-G2 有大量已实测的**精度**数字，README 一个都没引用，等于把自家可复核的成果藏起来 | 新增「已实测的数字」表，同时把「吞吐未测量」这句独立保留、加粗，避免读者误读为性能承诺 |
| D-10 | 文档索引缺 `LEGAL.md`、`PROGRESS.md`、PRD、SOTA 裁决、`research/`、`round3/` | 这些文件都在仓库里 | 索引补齐 |
| D-11 | 法律小节全是承诺，没有可执行证据 | `tests/test_env_guards.py` 实际断言：非 Windows、无 `HL3_VIC_HOME`/`VIC_2D_HOME`/`VIC_3D_HOME`、CI 下 `HL3_CI_CPU_ONLY=1` 且 `CUDA_VISIBLE_DEVICES` 为空 | 加一句「这条边界不只是承诺」，指向该测试文件 |

另外 README 里新增的最小示例是**照抄即可复现**的：`MockCapture` 第 1 帧相对第 0 帧是 `np.roll(base, (index, 2*index))`，即 `u=+2 px, v=+1 px`；实跑输出 36/36 收敛、`u=2.0, v=1.0`。我特意在示例后面写明「这是整像素位移，只用来说明 API 形状」，因为用非带限的 mock 纹理做亚像素演示会给出 ~1×10⁻² px 的残差（我实测过），那是演示自身重采样的误差，不是内核精度，写进 README 只会误导。

---

## 3. 我自己跑过的验证（不是转述报告）

```
$ python3 -m pytest -q tests src/tests
87 passed in 8.44s          # 改动后复跑：87 passed in 6.77s

$ python3 -m pytest --collect-only -q <file>
tests/test_env_guards.py     2 | tests/test_hdf5_schema.py    23
tests/test_icgn_synth.py    21 | tests/test_stereo_synth.py   32
src/tests/test_mock_capture.py  9

$ PYTHONPATH=src python3 -m hl3.io.hdf5_schema selftest
OK  schema=1.0.0-draft.2  hash_algo=blake2b-256
OK  往返一致：u/v/exx  形状=(3, 20)  vsg=57.0 px  空间单位=px
OK  strict 违规数=1  文件体积=50.6 KiB

$ PYTHONPATH=src python3 -c "from hl3.stereo.calibrate import main; main()"   # 27.4 s
  matching_only      rms=4.901um  rms_z=4.717um  p95=9.362um  max=21.05um
  calibration_only   rms=0.3096um rms_z=0.3055um p95=0.4235um max=0.4814um
```

立体那两行与 R2-O2 报告 §0 的 4.90 µm / 4.71 µm 逐位一致，所以 README 引用它们是**复核过**的，不是抄结论。环境：4 vCPU、无 GPU、Python 3.12.3、NumPy 2.4.4、h5py 3.16.0、无 blake3（故自检显示 `blake2b-256` 降级，与 schema A-2 条一致）。

ICGN 的 8.08×10⁻⁴ px 我没有单独复跑生成脚本，但它对应的回归断言 `test_subpixel_translation_recovered`（门限 5×10⁻³ px）在上面的 87 passed 里；README 对这一项标注了出处与断言名，读者可自行加严复算。

---

## 4. `docs/schema-hdf5.md` 的这一处改动为什么必要

§12 开头用现在时写「参考实现提供：`hl3 validate` / `hl3 diff` / `hl3 repack`」，并列出 `spec/conformance/` 样例集。这四样**一个都不存在**。对一份声称 CC-BY-4.0、要让第三方独立实现读写器的规范来说，这是最坏的一类漂移：外部实现者会照着不存在的 CLI 去对齐行为。

处置遵循「规范文档只由 schema 负责人改语义」的边界：

- 规范性要求一字未动，版本仍 `1.0.0-draft.2`，`flags` 位、路径树、必填级别全未触碰；
- 只在命令块后补一段「实现现状」，指明今天真正存在的是 `validate_file(path, strict=...)` 与 `python -m hl3.io.hdf5_schema selftest`，并说明现有 23 个测试覆盖到样例分类里的哪几条（2D 完整、若干非法用例、写入器确定性）；
- 在 §14 修订记录加 A-7，注明「只加实现现状说明，未改动任何规范性要求」，与 A-1..A-6 的记账方式保持一致。

---

## 5. 发现但**未**修复的问题（不在我的独占路径内）

| # | 问题 | 建议归属 |
|---|---|---|
| F-1 | ADR-LIC-001 执行规则 1 要求内核源文件带 `SPDX-License-Identifier: Apache-2.0`。实际只有 `src/hl3/io/*.py`、`tests/test_hdf5_schema.py`、`docs/schema-hdf5.md`、`README.md` 有；`icgn.py`、`stereo/*.py`、`capture/mock.py`、其余 3 个测试文件、`.agent_workspace/*/scripts/*.py` 都没有 | R3-O1 / R3-O2 各自加自己文件的头；R3-G1 在 SBOM/合规报告里记一笔 |
| F-2 | `pyproject.toml` 的 `testpaths = ["tests"]` 不含 `src/tests`，裸跑 `pytest` 会**静默漏掉** 9 个 mock capture 测试（87 变 78）。CI 与 README 都靠显式写两个路径兜住 | R3-G3（`pyproject` 测试配置是其独占路径）：要么并入 `testpaths`，要么把 `src/tests` 移到 `tests/` |
| F-3 | 仓库有 `.ruff_cache/`，但 `pyproject.toml` 无 ruff 配置、CI 无 lint 步骤。实跑 `ruff check src tests` 有 9 个错误、`ruff format --check` 有 9 个文件待格式化 | R3-G3；注意加 lint 会触及算法文件，需与 R3-O1/O2 协调顺序 |
| F-4 | `PROGRESS.md` 的「Round 状态」表里 Round 3 出现两行（IN_PROGRESS 与 PENDING 各一），是重复行 | R3-F3（`MASTER_PLAN.md` / 进度收尾） |
| F-5 | CI 只有 Python 3.11 单版本、无 h5py 缺失车道，而 `hdf5_schema` 的「无 h5py 也能 import」是明写的设计承诺，目前没有任何 job 验证它 | R3-G3 |

F-1 我可以在自己的两个文件里满足（已满足），但不去动别人的算法文件——这正是 R2-O1 报告里点名过的共享 checkout 事故的成因。

---

## 6. 法律与边界自检

- 本轮只读源码、跑自带测试、写 Markdown。**未下载任何外部数据集、未接触任何 VIC 资产、未安装新依赖、未联网取数**。
- README 中所有对商用产品的表述都限于「无关联、非衍生、非替代」与商标声明，没有任何功能对比数字。
- 新增的英文摘要末句明确写出「所有数字来自自生成合成数据、吞吐未测、不声称任何基准套件成绩」，把过度声称的风险堵在文首文末两处。
- 我给 README 加的每一个数字都能追到仓库内的命令或断言，没有引入无出处的性能/精度声明。

---

## 7. 复现本报告

```bash
git checkout cursor/r3-o3-docs-align-6edb
python3 -m pytest -q tests src/tests                                        # 87 passed
python3 -m pytest --collect-only -q tests/test_stereo_synth.py | tail -1    # 32
PYTHONPATH=src python3 -m hl3.io.hdf5_schema selftest
PYTHONPATH=src python3 -c "from hl3.stereo.calibrate import main; main()"
git show --stat ec0bb94
```
