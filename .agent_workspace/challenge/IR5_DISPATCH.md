# Impl-R5 派工（Challenge 第三方证据）

用户指令：按原 SOP 跑「建议的下一步」。下一步冻结为：

1. 把当前版本定位为影子复算内核（文档，不改口径）
2. **本轮主目标**：下载并跑公开的 2D-DIC Challenge 与 Stereo-DIC Challenge 1.0
3. 本轮不做 S5 GPU、S6 采集、显微镜畸变、iris GUI

SOP：10 = 4 fable + 3 opus-fast + 3 gpt-sol。禁止静默降级。报告首行 `ACTUAL_MODEL_SLUG:`。
`git add` 只用独占路径。共享 checkout，不要 `git add -A`。

## 法律

- 数据只从 SEM / iDICs / 论文 ESM / OSTI 等**官方或论文标明的公开托管**拉取。
- **禁止**把 Challenge 图像本体 commit 进 git（体积 + 再分发许可未核）。缓存目录 gitignore。
- **禁止** vendor OpenCorr / Ncorr / ALDIC / Pyvale 的图像或 MATLAB 分析代码。指标按已发表论文**独立实现**。
- 禁止显微镜/SEM 畸变实现（RUL-04）。Brown–Conrady / Zhang **允许**（普通相机，Stereo Challenge 需要）。
- 任何数字必须标注：Challenge 子集、subset/step/VSG、是否用了提供的标定、是否含畸变。禁止「已对标 VIC」。

## 已知事实（父调度器 2026-08-29）

- 论文写明数据在 https://idics.org/challenge/ ；SEM 旧址 https://sem.org/dic-challenge/ 当前抓取为 404 / “reached this page in error”。
- Stereo-DIC Challenge 1.0：Exp Mech https://doi.org/10.1007/s11340-024-01077-7 ；标定+平移图像；随附 MATLAB 分析脚本；镜头畸变是该挑战的核心检查项。
- 2D-DIC Challenge：Reu et al. 2018 Sample 14/15；Challenge 2.0 为 star 场 / MEI（Reu 2022）。
- 仓内 `hl3.cli.run.load_image` 已能走 Pillow 读 TIFF；pipeline 2D 可用；立体链是纯针孔，需标定参数文件或 Zhang。
- CI 不得下载 GB 级数据：测试必须 `skip` 当缓存缺失。

## 独占路径

| ID | slug | 独占路径 |
|----|------|----------|
| IR5-F1 | claude-fable-5-thinking-xhigh | `.agent_workspace/challenge/IR5-F1-2d-protocol.md` |
| IR5-F2 | claude-fable-5-thinking-xhigh | `.agent_workspace/challenge/IR5-F2-stereo-protocol.md` |
| IR5-F3 | claude-fable-5-thinking-xhigh | `.agent_workspace/challenge/IR5-F3-data-license.md` |
| IR5-F4 | claude-fable-5-thinking-xhigh | `.agent_workspace/challenge/IR5-F4-gates.md` |
| IR5-O1 | claude-opus-5-thinking-high-fast | `src/hl3/bench/challenge2d.py`、`tests/test_challenge_2d.py`、报告 `IR5-O1-2d.md` |
| IR5-O2 | claude-opus-5-thinking-high-fast | `src/hl3/bench/challenge_stereo.py`、`src/hl3/stereo/calib_io.py`（若需解析公开标定文件）、`tests/test_challenge_stereo.py`、报告 `IR5-O2-stereo.md` |
| IR5-O3 | claude-opus-5-thinking-high-fast | `src/hl3/bench/__init__.py`、`src/hl3/bench/download.py`、`benchmarks/challenge/manifest.json`、`.gitignore`（只追加 cache）、`src/hl3/cli` 仅可加 `challenge` 子命令、`pyproject.toml` extra `bench`、报告 `IR5-O3-download.md` |
| IR5-G1 | gpt-5.6-sol-xhigh-fast | `.agent_workspace/challenge/IR5-G1-legal.md` |
| IR5-G2 | gpt-5.6-sol-xhigh-fast | 在有数据时实跑 O1/O2 入口；无数据则记录失败原因；`IR5-G2-run.md`；可写 `benchmarks/challenge/results/.gitkeep` 与 JSON 成绩（无图像） |
| IR5-G3 | gpt-5.6-sol-xhigh-fast | CI 保持 skip；`benchmarks/metrology/metrics.json` 追加 challenge 段；`IR5-G3-ci-metrics.md` |

O1/O2 可 `from hl3.bench.download import ...`；若 O3 尚未落地，先用环境变量 `HL3_CHALLENGE_ROOT` 读本地目录，不要复制一份下载器。
