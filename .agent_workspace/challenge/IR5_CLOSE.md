# IR5 收口（父调度器）

用户：按原 SOP 跑建议的下一步（Challenge 第三方证据）。

## SOP 执行情况

本轮 **Task 子代理启动失败**：平台返回 `You've used all included Cloud Agent usage`，`environment=local` 同样失败。无法按 4 fable + 3 opus-fast + 3 gpt-sol 生成独立子进程。父调度器（本对话模型）在 `/workspace` 直接完成了 IR5 十个槽位的规格、实现、下载与跑数，**没有伪造** `ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh` 等行。

## 做了什么

- 从 **https://idics.org/challenge/** 页面上的官方 Google Drive 拉取 2D Challenge 1.0 Sample 14/15，以及 Stereo 1.0 Sample 1 `Translate.zip`（约 1.06 GB，仅缓存，不入库）。
- **拒绝** SEM-DIC Round Robin 文件夹（RUL-04）。
- 实现 `python -m hl3.bench download|2d|stereo` 与 `hl3 challenge`。
- Sample 15 对官方 `CommandedDisplacementLineCut.xlsx` 做独立 Python 线切割：subset 21 / step 16 / search 16，**RMSE 0.083 px，bias −0.035 px**，收敛率 0.64。不是官方 MATLAB 计分器，也不是 VIC 对照。
- Sample 14 无随包真值；全点收敛，v RMS 0.022 px（文件名 Amp 0.1）。
- Stereo：无标定文件可解析为 3×4 `P`；只做了左相机 2D 诊断。10 mm 台步下收敛率 1.2%——预期如此（离面刚体不能当单目 2D 做）。**不是**论文 <80 µm 的 3D 成绩。

## 明确没有关闭的门

A5 官方 Stereo Challenge 3D 成绩、Zhang/Brown 标定、曲面 3D 应变、schema 1.0、对标/超越 VIC。
