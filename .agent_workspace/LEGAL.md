# 法律边界（强制）

## 允许

- 阅读 Correlated Solutions 官方产品页、系统页、下载说明、公开宣传册与已发表应用案例。
- 阅读 iDICs Good Practices Guide、Stereo-DIC Challenge 等公开标准与数据集。
- 阅读并（在各自许可证下）参考 GitHub 开源 DIC：OpenCorr、DICe、Ncorr、muDIC、ALDIC、DuoDIC、MultiDIC 等。
- 基于公开文献复现 **算法类别**（ZNCC/ZNSSD、ICGN、立体标定、三角化、应变张量、PLS 平滑），不复制专有实现。

## 禁止

- 下载、传播、安装破解版 VIC-2D / VIC-3D / VIC-EDU / VIC-Volume。
- 反编译、逆向、密钥生成、许可证绕过。
- 把专有手册/二进制中的未公开实现细节当自己的代码。
- 向 Correlated Solutions 提交虚假评估密钥申请。

## 官方评估版事实（公开信息）

来源：https://www.correlatedsolutions.com/downloads

- VIC-3D 11.4：Windows 10+ 安装包（约 184MB），首次打开显示 12 字符 PC 专属密钥，提交表格后获得 30 天评估许可。
- VIC-2D 8：Windows 安装包（约 225MB），同样的密钥流程。
- 评估期内销售工程师会跟进。
- 本仓库运行环境为 Linux Cloud Agent，**不能**合法完成该 Windows 许可闭环。

结论：深度功能分析走 **公开规格 + 文献 + 开源对标**；若用户本地持有合法许可，可在后续在其 Windows 工作站做 UI 走查，不在本环境进行。
