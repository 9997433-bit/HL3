# S1–S4 实施调度（SOP：每轮 10 = 4 fable + 3 opus-fast + 3 gpt-sol，共 3 轮）

用户指令：做到 **S4 停止并总结**。S5（GPU）/S6（相机实时）不做。

| 轮 | 范围 | 停止条件 |
|----|------|----------|
| Impl-R1 | **S1** 2D 计量收口 | 二阶形函数或明确 xfail；应变/VSG；2D pipeline；精度测试可跑 |
| Impl-R2 | **S2+S3** | 立体匹配→U/V/W→曲面应变；确定性/工程哈希/UQ 传播；`hl3 validate` |
| Impl-R3 | **S4** | CLI、无头出图、FEA 对照最小链、社区查看器基线；然后父调度器总结停止 |

模型映射（禁止降级）：
- fable = `claude-fable-5-thinking-xhigh` ×4（Impl-R1 的 F1 为云端）
- opus-fast = `claude-opus-5-thinking-high-fast` ×3
- gpt-sol = `gpt-5.6-sol-xhigh-fast` ×3

报告第一行：`ACTUAL_MODEL_SLUG: <slug>`  
`git add` 只用独占路径，禁止 `git add .`。显微镜零实现。无 VIC 逆向。
