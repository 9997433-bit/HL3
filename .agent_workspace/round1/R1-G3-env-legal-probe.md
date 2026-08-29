ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# R1-G3：Linux 环境与合法下载边界探针

探针日期：2026-08-28（UTC）。本次只执行只读环境检查、抓取公开网页 HTML 和解析公开下载链接；**未下载、安装或运行任何 VIC/Windows 二进制文件，也未提交许可证申请**。

## 结论摘要

- 当前是 Ubuntu 24.04.4 LTS、x86_64、4 vCPU 的 KVM Linux 云机；无 NVIDIA 设备、驱动或 CUDA 工具链。
- 未发现 Wine、Windows、WSL 挂载、PowerShell、`cmd.exe` 或 Windows 虚拟机运行器。虽然有图形显示 `DISPLAY=:1`，但它不等于 Windows 兼容层。
- Correlated Solutions 公开下载页列出的 VIC-2D 8、VIC-3D 11.4、VIC-EDU、VIC-Volume 和两个免费生成器，当前下载目标都是 Windows 的 MSI；校准板生成器的另一官方产品页还提供 EXE。本站没有列出 Linux 原生包。
- VIC 四个分析产品不是免许可证软件：官方流程要求首次启动后提交本机专属 12 字符/数字代码，获批 30 天评估许可证。不得破解、生成密钥、伪造申请或运行未授权副本。
- 散斑图案生成器和校准板生成器的下载页明确写明“完全免费且无需许可证”，因此可从官方链接合法获取其公开版本；但它们并非开源，且 Windows 安装格式在本机不可直接运行。本轮据此只记录链接，不下载、不强装 Wine。
- 无 VIC 仍可用合成图、固定 fixture、golden result 和 OpenCorr/DICe/Ncorr/µDIC 等公开工具开发与验证。

## 1. 当前云环境事实

| 项目 | 实测结果 | 含义 |
|---|---|---|
| OS | Ubuntu 24.04.4 LTS (Noble) | 不是 Windows |
| 内核 | `Linux cursor 6.12.94+` | Linux 云内核 |
| 架构 | x86_64，64 位 | 能解释 `win64` 文件名，但不能原生执行 PE/MSI |
| CPU | 4 个在线逻辑 CPU；`Intel(R) Xeon(R) Processor`；1 socket × 4 cores × 1 thread | 适合小型 CPU fixture/单元测试，不代表生产性能 |
| 虚拟化 | KVM，全虚拟化 | 当前 guest 仍是 Linux；没有已配置的 Windows guest |
| 内存 | 15 GiB，可用约 14 GiB；无 swap | 中小型图像集可用 |
| 工作盘 | 252 GiB，总可用约 238 GiB | 容量不是本轮阻塞项 |
| 图形会话 | `DISPLAY=:1`；`WAYLAND_DISPLAY` 未设置 | 可做 Linux GUI 测试，但不能让 Windows 程序原生运行 |
| GPU | `/dev/nvidia*` 不存在；`nvidia-smi` 不存在；NVIDIA proc 驱动节点不存在 | 没有可见 NVIDIA GPU |
| CUDA | `nvcc` 不存在；`/usr/local/cuda` 不存在 | 不能构建或验证 CUDA 路径 |
| PCI 探针 | `lspci` 不存在 | 无法用该命令补充 PCI 清单；上述设备节点/驱动/CUDA 检查仍一致为无 GPU |
| Wine | `wine`、`wine64` 均不存在 | 不能运行 Windows EXE/MSI |
| Windows/WSL | `cmd.exe`、`powershell.exe` 不存在；`/mnt/c/Windows` 不存在 | 没有可见 Windows 或 WSL Windows 文件系统 |
| 其他运行器 | `qemu-system-x86_64`、`pwsh` 不存在 | 没有现成 Windows VM/PowerShell 路径 |

关键探针命令包括 `uname -a`、`lscpu`、`systemd-detect-virt`、`command -v`、NVIDIA 设备/驱动节点检查、内存与磁盘检查。环境结论是 **Linux + CPU-only + 无 Windows 兼容层**。

## 2. Correlated Solutions 官方下载页

主来源：[Correlated Solutions Downloads](https://www.correlatedsolutions.com/downloads)。以下文件名来自 2026-08-28 抓取的官方页面实际 `href`，而不是根据按钮文字猜测。

| 项目 | 页面标示 | 当前公开目标文件/类型 | 许可与本机结论 |
|---|---:|---|---|
| VIC-3D 11.4 | 184 MB；要求 Windows 10 | `Vic-3D-11-11.4.18.0-win64.msi`（MSI） | 专有评估软件；需获批临时许可证；本机跳过 |
| VIC-2D 8 | 225 MB | `Vic-2D-8-8.4.0.0-win64.msi`（MSI） | 专有评估软件；需获批临时许可证；`win64` 表明 Windows；本机跳过 |
| VIC-EDU | 176 MB；要求 Windows 10 | 可见下载按钮当前指向 `Vic-3D-11-11.2.12.0-win64.msi`（MSI） | 专有评估软件；按钮标签和目标文件名不完全一致，不能把它误称为独立 Linux 包；本机跳过 |
| VIC-Volume | 73 MB | `Vic-Volume-2.0.2.0-win64.msi`（MSI） | 专有评估软件；需获批临时许可证；本机跳过 |
| Calibration Target Generator | 7 MB | 下载页为 `TargetGenerator.msi`（MSI）；[校准板产品页](https://www.correlatedsolutions.com/accessories-ref/calibration-targets)另列 `cal_gen.exe`（EXE） | 官方明确“无需许可证、完全免费”；仍是 Windows 二进制，本机只记录不安装 |
| Speckle Pattern Generator | 6 MB | `speckle-setup.msi`（MSI） | 官方明确“无需许可证、完全免费”；仍是 Windows MSI，本机只记录不安装 |

补充审慎说明：

1. 官方页只对 VIC-3D 和 VIC-EDU 在正文中明确写出 Windows 10 要求，但全部六类当前下载目标均为 `.msi`、`win64.msi` 或 `.exe`，且页面没有 Linux 包。因此就**这些公开安装器**而言是 Windows-only。
2. 页面中部分产品存在重复或旧链接，例如 VIC-2D 和 VIC-Volume 各有不止一个 MSI 目标；上表采用可见“Download ... software”按钮的当前目标。安装前应始终重新核对按钮、文件版本、发布说明和数字签名。
3. “完全免费且无需许可证”只足以支持从官方页面获取和按发布方用途使用两个生成器；它不自动意味着开源、可反编译、可镜像分发或可去除版权标识。
4. VIC-3D/VIC-2D/VIC-EDU/VIC-Volume 的公开可下载性不等于获准运行。官方下载页要求安装后取得 PC 专属代码并申请 30 天评估许可；[Key Request Form](https://www.correlatedsolutions.com/keys-inquiry)还说明评估对象是合格潜在客户，由支持团队逐个处理。
5. 下载页称“12-character”，申请页称“12-digit”；本报告保留这一网页措辞差异，不据此构造或猜测任何密钥格式。

### 本轮下载决策

- **可以合法下载但本轮不下载**：官方免许可证的 Speckle Pattern Generator、Calibration Target Generator。
- **原因**：它们均为 Windows MSI/EXE，而当前机没有 Wine/Windows；强行安装 Wine 不会增加研究可信度，反而会引入兼容性、安全和许可解释风险。
- **不得当作免许可软件下载**：四个 VIC 分析产品。即使安装包可匿名取得，运行仍取决于有效商业/评估许可。
- **实际状态**：仓库内未保存任何 MSI、EXE、评估密钥或 VIC 安装产物。

## 3. 必须禁止的行为及原因

| 禁止行为 | 原因 |
|---|---|
| 破解、补丁绕过、篡改许可校验 | 绕过权利人访问控制和许可条件；也会引入来源不明二进制及供应链风险 |
| keygen、猜测或复用他人 PC key | 获得的不是本机、本主体的有效授权；不能把“程序能启动”等同于合法使用 |
| 向评估表单提交伪造 PC key、身份、机构或购买意向 | 属于向外部主体作虚假陈述；会污染审计记录，也违反本项目明确边界 |
| 下载或运行 crack、盗版镜像、未授权副本 | 无法证明来源、完整性和授权链；不得进入开发机、CI、镜像、仓库或交付物 |
| 为了“兼容”而反编译、抓取内部协议或复制专有 UI/实现 | 本任务授权仅覆盖公开网页、公开文献和依法许可的开源代码，不覆盖逆向工程 |
| 上传或传播安装器、许可证文件、专有项目样本 | 官方“可下载”不等于获得再分发权；许可证和客户数据尤其不得入库 |

工程上应把许可视为可审计依赖：记录来源、版本、许可主体、适用设备和到期日；没有正面授权时默认不运行，而不是寻找技术绕过。

## 4. 可公开获取的示例图像/数据

以下链接可用于无 VIC 开发。下载前仍应在具体版本/文件层面保留许可证和署名；“公开可访问”不自动消除署名、再分发或数据集专项条款。

1. **OpenCorr examples**
   - 说明页：[OpenCorr Examples](https://opencorr.org/opencorr/examples/)
   - 仓库总目录：[vincentjzy/OpenCorr/examples](https://github.com/vincentjzy/OpenCorr/tree/main/examples)
   - 2D 图像：[examples/2d_dic](https://github.com/vincentjzy/OpenCorr/tree/main/examples/2d_dic)
   - Stereo/3D 图像：[examples/3d_dic](https://github.com/vincentjzy/OpenCorr/tree/main/examples/3d_dic)
   - 说明页确认 2D 示例含 iDICs 2D Challenge Sample 12（带孔板单轴拉伸）和 Sample 9，3D 示例含 Stereo Challenge Sample 1/3。OpenCorr 源码仓库声明 MPL-2.0；第三方提供的图像和 DVC 数据仍应按其原始归属复核后再分发。

2. **DICe tutorials/examples**
   - 官方教程：[DICe Tutorial](https://dicengine.github.io/dice/md__d_i_ce__tutorial.html)
   - 源码示例目录：[dicengine/dice/tests/examples](https://github.com/dicengine/dice/tree/master/tests/examples)
   - 官方 release 示例包：[DICe_examples.zip](https://github.com/dicengine/dice/releases/download/v3.0-beta.2/DICe_examples.zip)
   - 教程描述 `mechanism`、`obstruction`、`full_field`，并含输入 XML、图像/视频和 gold 结果。DICe 软件公开元数据为 BSD-3-Clause，但示例包中每项媒体的再分发权不宜仅凭代码许可证推定；用于发布产品 fixture 前应检查包内声明。

3. **iDICs / DIC Challenge**
   - 官方入口：[iDICs DIC Challenge](https://www.idics.org/challenge/)
   - 数据公开性说明：[iDICs Challenge blog](https://idics.org/blog/post_2/)
   - iDICs 说明 Challenge 面向全社区，实验与合成图像用于软件验证，图像和补充数据公开传播。当前入口页的正文抓取主要显示委员会信息，旧 `sem.org/dicchallenge` 抓取还返回错误页，因此应从 iDICs 入口进入最新数据链接，避免硬编码已经失效的 SEM 路径。

4. **公开拉伸散斑原始图像**
   - 数据集：[AA5086 tensile tests with PLC effect](https://doi.org/10.5281/zenodo.1312835)（当前版本记录为 [Zenodo 1312836](https://zenodo.org/records/1312836)）
   - Zenodo API 明确标记 `access_right: open`、许可 `CC-BY-4.0`；包含 28 组拉伸试验、每组约 300–2300 张 raw DIC images、时间序列和后处理数据。
   - 单个图像归档约 70 MB 至 956 MB，按需选择小集并校验 Zenodo 给出的 MD5，禁止把整套大数据直接提交到 Git。

Correlated Solutions 下载页自己的 VIC-2D/VIC-3D tensile examples 不应被本报告归为“无条件开放数据”：页面把其分析使用放在“收到评估许可证后”的语境中。优先使用上面的 OpenCorr/iDICs/Zenodo 数据，避免许可含糊。

## 5. 无 VIC 的开发与 Mock 策略

### 5.1 分层隔离

- 定义中立接口，例如 `ProjectStore`、`ImageSequence`、`Calibration`、`CorrelationJob`、`FieldResult`、`Exporter`；不得以 VIC 私有文件格式或私有 API 作为核心领域模型。
- `MockDicEngine` 只返回受版本控制的公开 fixture；真实 OSS 引擎通过 adapter 接入。UI 只依赖接口，不依赖某个商业二进制。
- fixture 使用公开格式：TIFF/PNG 图像、JSON/YAML 参数、CSV/HDF5 位移/应变、OpenCV 标定参数。记录坐标系、单位、应变定义和掩膜。

### 5.2 确定性合成图

- 用项目自有或明确开源的 Python/C++ 生成器，固定随机种子生成散斑；不要调用或复制 Correlated Solutions 的闭源生成器。
- 对参考图施加已知仿射、旋转、正弦位移、局部应变、遮挡、亮度变化、模糊和噪声，保存解析 ground truth。
- 建立小型分层集：smoke（2 张小图）、regression（几十张）、benchmark（外部大数据按需拉取，不入 Git）。
- 验收位移/应变误差、失配掩膜、坐标和单位，不只做截图像素比较。

### 5.3 UI 与工作流 Mock

- 以公开功能需求设计自己的向导：导入 → ROI/掩膜 → 参数 → 运行 → 质量图 → 位移/应变 → 导出；不要逐像素复制 VIC 布局、图标、文案或 trade dress。
- 为文件选择、ROI、进度、取消、失败恢复和导出做状态机 fixture；长任务使用可控 fake clock 和可注入错误。
- 当前 `DISPLAY=:1` 可跑 Linux 原生 GUI/screenshot 测试；CI 仍应支持 headless/offscreen 模式。
- 保存 golden CSV/JSON 和容差规则；截图只验证布局，数值正确性由结构化结果验证。

### 5.4 可用 OSS 对照

- [DICe](https://github.com/dicengine/dice)：Windows/Linux/macOS，Linux 可从源码构建 CLI 和 GUI；适合作为公开算法/工作流对照。
- [OpenCorr](https://github.com/vincentjzy/OpenCorr)：MPL-2.0 C++ 库，含 2D、stereo/3D、DVC 与示例；其独立 GUI 被作者称为 shareware，不能把 GUI 与库许可证混为一谈。
- [Ncorr](https://github.com/justinblaber/ncorr_2D_matlab)：BSD-3-Clause 的 2D MATLAB GUI/源码；需要合法 MATLAB 环境。
- [µDIC](https://github.com/PolymerGuy/muDIC)：MIT Python 工具包，含轻量网格 GUI、虚拟实验和后处理；技术栈较旧，宜作参考/fixture 生成器而非未经验证的生产依赖。

## 6. 若用户以后拥有合法 Windows 许可：UI 走查清单

本轮**不执行**以下操作；这只是后续在用户控制的合法 Windows 工作站上的检查表。

1. 确认购买/评估许可覆盖具体产品、版本、用户、机器和用途；记录到期日，不共享 key/许可证文件。
2. 使用受支持的 Windows 10/11 环境，从官方页面重新下载；核对 HTTPS 来源、文件名、版本、签名/哈希和发布说明。
3. 由真实被许可用户安装；首次启动得到真实 PC 专属代码，只提交真实身份和真实评估信息。
4. 许可证获批后再启动分析；不要迁移 key、改硬件指纹、回拨时间或绕过联网/许可校验。
5. 使用用户有权处理的自有或开放图像，建立走查项目；避免把客户、受限手册、许可文件或专有 project 上传到云端。
6. 仅观察正常 UI：新建/打开、导入图像、ROI、参数、运行、质量指标、位移/应变、可视化、导出、错误处理。
7. 用文字记录公开可见行为和自己的测试结果；不反编译、不注入、不抓取私有协议、不解包资源、不复制受保护素材。
8. 记录产品全名、精确版本、Windows 版本、许可类型和走查日期；截图先清除姓名、序列号、PC key、路径和客户数据。
9. 将观察结果转化为独立需求和验收标准，而不是复制 UI；用 OSS/自研实现验证。
10. 到期后停止运行并按许可要求卸载/归档；删除临时许可证和敏感截图，保留合规审计记录。

## 7. 最终约束与合法下载判断

- **硬环境约束**：CPU-only Linux；无 CUDA；无 Wine/Windows；不能在本机完成 VIC 的 Windows 安装、PC-key 生成或授权 UI 走查。
- **可下载且免 VIC 许可证**：仅官方明确标注完全免费的 Speckle Pattern Generator 与 Calibration Target Generator；二者依然是 Windows 闭源二进制，本轮不下载、不执行。
- **不能无许可证运行**：VIC-2D 8、VIC-3D 11.4、VIC-EDU、VIC-Volume。匿名下载入口不是运行授权。
- **推荐路径**：用 OpenCorr/DICe/iDICs/CC-BY-4.0 Zenodo 图像、确定性合成图和结构化 fixtures 开发；将商业产品走查留给以后具备真实 Windows 许可的用户工作站。

