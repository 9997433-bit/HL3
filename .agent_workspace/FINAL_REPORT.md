# HL3 全局总结（三轮 4/3/3 调度结束）

## 用户目标

做两款 DIC 应变分析软件（二维 / 三维），对标并最终超过 Correlated Solutions 的 **VIC-2D 8** 与 **VIC-3D 11**。

## 能否“下载这两个软件做深度分析”

**不能在本环境合法完成安装分析。**

官方提供 30 天评估版，但是：

- 安装包为 **Windows MSI**（VIC-2D 8、VIC-3D 11.4 等）
- 首次运行需提交 **PC 专属 12 位密钥** 申请评估许可
- 本 Cloud Agent 为 **Linux、无 Wine、无 CUDA**

禁止破解、逆向、伪造评估申请。功能分析仅基于官方公开页、iDICs 良好实践、已发表论文与 GitHub 开源实现（OpenCorr、DICe、Ncorr、muDIC、ALDIC、DuoDIC 等）。

免费的散斑/标定板生成器亦为 Windows 安装包，本轮只记录链接、不安装。

## 调度执行

每轮 **10 子代理 = 4 fable + 3 opus-fast + 3 gpt-sol**（已纠正先前误写的 2/2/2）。共 3 轮，模型 slug 未降级。R1-F1 为指定云端 `claude-fable-5-thinking-xhigh`。

## 产品结论（如何超过 VIC）

VIC 的护城河是**整条测量链 + 硬件交钥匙 + 支持品牌**，不是单个相关器。HL3 的攻击面是：

1. 跨平台与自助许可（对 Windows-only + 销售密钥流）
2. Python-first（对 vicpyx 后挂）
3. 默认不确定度 UQ（对 MatchID 已验证的需求、VIC 公开叙事偏弱）
4. 公开 HDF5 schema + 可审计 Apache-2.0 内核
5. GPU 吞吐作为加速后端（CPU float64 为计量规范）
6. 局部 + 全局 DIC 接口预留（v1 只交付 LOCAL）

显微镜/SEM 畸变：**FTO 书面意见前零实现**（即使 US7133570B1 显示过期迹象）。

## 本仓库已落地

- CPU 一阶 ICGN（ZNSSD）参考核，合成平移误差 ~0.0008 px
- 立体三角化/合成标定原型，0.02 px 匹配噪声下 ~5 µm RMS
- 公开 HDF5 schema 草案与读写校验
- 合成散斑、插值 S 曲线、噪声底脚本
- CI 与 232 个 CPU 测试
- 完整竞品矩阵、PRD、P0–P9 阶段门、超越判定公式

**未落地（诚实）**：VIC-Snap 级采集、VIC-Gauge 实时、iris 可视化、工业安装器、与 VIC 的同机对照。

后续路线见 `.agent_workspace/round3/R3-F4-beyond-vic-roadmap.md`。
