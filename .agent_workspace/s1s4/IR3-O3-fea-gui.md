ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# IR3-O3 FEA + GUI 基线

- `hl3.fea`: 三角形网格上 DIC↔节点双向投影（barycentric / least_squares / nearest）。不做 VTK 文件导入、不做全局 FE-DIC。
- `hl3.gui`: 包导入无 matplotlib 副作用；`PolygonAOI` JSON 侧车；`viewer` 在缺 tk/mpl 时退出码 2。
- 明确不是 iris 级界面。
