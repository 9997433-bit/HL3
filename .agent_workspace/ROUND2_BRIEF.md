# Round 2 结论简报（父调度器）

- **轮次**：Round 2 / 3（靶向重构与深度优化）
- **派发**：10 = **4×fable** + **3×opus-fast** + **3×gpt-sol**（已更正的 4/3/3，禁止再写 2/2/2）
- **模型**：10 份报告首行均声明实际 slug；无静默降级
- **测试**：合并后本机 `pytest tests src/tests` → **87 passed**
- **法律**：仍无 VIC 二进制；Linux CPU-only

## 1. 相对 Round 1 的演进

| 项 | Round 1 | Round 2 |
|----|---------|---------|
| 相关器 | 仅规格 | CPU 一阶 ICGN（ZNSSD），合成平移 mean\|err\| ≈ 8×10⁻⁴ px |
| 立体 | 规格 | 三角化+合成标定原型；0.02 px 匹配噪声下 ~4.9 µm RMS |
| 数据格式 | 两份草案 | HDF5 schema 可执行常量 + 读写/校验 |
| 许可证 | 三口径 | ADR：内核 Apache-2.0；OpenCorr 不复制；GPU .lib 禁用 |
| 吞吐数字 | 互相矛盾 | RUL-03：G2 协议为唯一口径；未同机测 VIC 不得宣称更快 |
| 显微镜 | 规格里有实现倾向 | RUL-04：FTO 前零实现 |
| CI | 无 | `.github/workflows/ci.yml` CPU pytest |
| GUI | 未做 | **诚实：本轮达不到 VIC-class GUI** |

绑定裁决见 `round2/R2-F1-sota-reconciliation.md`（RUL-01…08）与 `round2/R2-G1-license-adr.md`。

## 2. 潜在边界风险

- 并行子代理曾共用 checkout，产生不完整 `triangulate.py` 副本；集成时以 O2 分支为权威。
- Keys 双三次插值偏差在 G2 脚本上未过门（P-P ~0.03 px）；内核默认 B 样条。
- HDF5 测试在无 h5py 的 CI 中会 skip；需 Round 3 把 h5py 纳入 CI 或明确可选。
- `src/tests/test_mock_capture.py` 与 `tests/` 双路径，易漏收集。
- Stereo Challenge 标定主导误差尚未在无畸变针孔原型上复现（O2 已诚实记录）。
- 无 GPU：吞吐目标仍是纸面数字。

## 3. SOTA 验收差距（相对 VIC-2D 8 / VIC-3D 11 公开能力）

仍缺：采集（VIC-Snap）、实时 Gauge、iris 级可视化、vicpyx 级产品化 Python 工作流、FEA 对比 GUI、多相机、FFT ODS、Windows 安装器、合法 VIC 同机对照。

已具备超越楔子的**地基**：开源可审计内核、公开 schema、UQ 字段、跨平台 CPU 参考、合成基准。

按 R2-F4 量表诚实评分：**规划完备度 A ≈ 4；实现完备度 B ≈ 2.5**（有 ICGN+立体+schema，无全链 headless 工程）。

## 4. Round 3 攻坚（注入全体子代理）

1. 交叉核验 RUL 与代码一致（无显微镜代码、无 OpenCorr vendor、无吞吐吹牛）。
2. 产出 `benchmarks/metrology/metrics.json`（ICGN bias、噪声底、立体重建误差）。
3. CI 安装 h5py；统一测试发现路径；补边界测试。
4. 冻结最终 `MASTER_PLAN.md` + 用户可读路线图：如何在后续真正超过 VIC（测量链补齐顺序）。
5. README/文档与代码对齐；SBOM/依赖与 LEGAL 扫描。
6. **禁止**假装已有 iris/VIC-Snap；禁止下载破解 VIC。
