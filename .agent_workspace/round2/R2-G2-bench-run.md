ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# R2-G2 合成插值与噪声底板实跑

## 1. 范围与结论

本轮新增并实跑：

- `.agent_workspace/round2/scripts/interpolation_scurve.py`
- `.agent_workspace/round2/scripts/noise_floor_stub.py`

全程只使用自生成数据，没有下载 Challenge 数据或 VIC 二进制。运行时已检测到
`src/hl3/correlate/icgn.py`，但未调用：插值脚本刻意保留一个不依赖 ICGN API
稳定性的标量 ZNSSD 路径，噪声脚本则明确标为线性化位移诊断 stub。因此下列数字不是
HL3 ICGN 的验收成绩。

核心实测结论：

- 双线性插值的相位 bias 峰峰值为 `0.00465987 px`（正弦）和
  `0.00176496 px`（散斑），在 Round 1 暂定 `<=0.02 px` 门槛内。
- Keys bicubic (`a=-0.5`，无预滤波) 的相位 bias 峰峰值为
  `0.03862749 px`（正弦）和 `0.02888446 px`（散斑），**未通过**该暂定门槛。
- 输入独立高斯噪声 `sigma=1 gray count` 时，两帧差值实测
  `std=1.403231 gray`（未裁剪理论值 `sqrt(2)=1.414214`）；零位移诊断的 pooled
  `std(u,v)=(0.00178208, 0.00171700) px`。

## 2. 可复现实验配置

运行命令：

```bash
python3 .agent_workspace/round2/scripts/interpolation_scurve.py \
  --output-json /tmp/r2-g2-interpolation.json \
  --output-csv /tmp/r2-g2-interpolation.csv

python3 .agent_workspace/round2/scripts/noise_floor_stub.py \
  --noise-sigmas 0 0.25 0.5 1 2 4 8 \
  --output-json /tmp/r2-g2-noise.json
```

公共配置：`96x96` 图像、`31x31` subset、POI step `16`（16 POI）、散斑
`sigma=1.25 px`、密度 `0.08/px^2`、`8x` 过采样、seed `20260828`。
插值扫描使用 `p=0.00,0.05,...,0.95 px`，最近整数粗初值、`0.01 px` 搜索步长和
三点抛物线细化；每种纹理/插值器共 320 个估计。噪声扫描每档 30 个独立图像对。

环境：

- Linux `6.12.94+`，x86_64，KVM
- 4 vCPU，`Intel(R) Xeon(R) Processor`，1 thread/core
- RAM `16,398,384 KiB`
- Python `3.12.3`，NumPy `2.4.4`
- 脚本提交：`37ec687c8f2243ceff382ddc5b2ccbec807d00e9`

## 3. 插值 S 曲线实测

连续正弦按像素面积解析积分；散斑以高分辨率随机脉冲、频域高斯卷积、傅里叶平移及
`8x8` 块积分生成。两类真值生成均未使用被测双线性/Keys 插值器。估计器在每个 subset
上最小化 ZNSSD，只测水平平移。

| 纹理 | 插值器 | 总 bias (px) | 总 std (px) | RMSE (px) | phase bias P-P (px) | 一阶谐波幅值 (px) | 最大相位 `|bias|` (px) | 有效率 | 0.02 px 门 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| sinusoid | bilinear | 0.00012001 | 0.00233338 | 0.00233282 | 0.00465987 | 0.00233738 | 0.00242841 | 100% | PASS |
| sinusoid | Keys bicubic | 0.00006708 | 0.01381274 | 0.01379130 | 0.03862749 | 0.01926920 | 0.01936003 | 100% | **FAIL** |
| speckle | bilinear | -0.00109388 | 0.00202407 | 0.00229797 | 0.00176496 | 0.00087759 | 0.00183064 | 100% | PASS |
| speckle | Keys bicubic | -0.00029699 | 0.01042237 | 0.01041031 | 0.02888446 | 0.01450056 | 0.01457934 | 100% | **FAIL** |

这里的 `std` 汇合了相位与空间 POI，不能替代单相位随机噪声。Keys 结果只适用于本次
`a=-0.5` cubic convolution；它不是带预滤波的 cubic B-spline，也不能推出“双线性在
所有 DIC 中优于三次插值”。本结果说明必须实测最终插值器的位移 S 曲线，不能仅凭图像
重建阶数推断位移 bias。

## 4. 两幅相同图像 + 独立噪声

每个 trial 从同一张无位移散斑真值生成两幅图，分别加入独立高斯噪声并裁剪到
`[0,255]`。`difference std` 是两幅观测之差的像素标准差；`u/v pooled std` 来自已知
零初值处的一步局部最小二乘平移，仅作为噪声传播 stub。

| 输入 sigma (gray) | difference std (gray) | 未裁剪理论 `sqrt(2)sigma` | u bias (px) | u pooled std (px) | v bias (px) | v pooled std (px) |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.25 | 0.352310 | 0.353553 | -0.00000100 | 0.00044136 | -0.00004900 | 0.00045993 |
| 0.5 | 0.703590 | 0.707107 | -0.00010366 | 0.00090867 | -0.00004000 | 0.00089263 |
| 1 | 1.403231 | 1.414214 | -0.00016455 | 0.00178208 | -0.00018069 | 0.00171700 |
| 2 | 2.799603 | 2.828427 | -0.00012565 | 0.00330688 | 0.00035218 | 0.00359644 |
| 4 | 5.569591 | 5.656854 | -0.00031858 | 0.00741440 | -0.00042800 | 0.00674528 |
| 8 | 10.969477 | 11.313708 | -0.00139684 | 0.01542349 | 0.00045967 | 0.01389188 |

`sigma=1` 时，按 Round 1 对噪声底板的空间/时间拆分约定：

| 分量 | 平均空间 std (px) | 平均时间 std (px) | pooled 3-sigma (px) |
|---|---:|---:|---:|
| u | 0.00156759 | 0.00176791 | 0.00534624 |
| v | 0.00160150 | 0.00166536 | 0.00515101 |

随 sigma 增大，裁剪比例从 `0.527%`（sigma 0.25）增至 `3.206%`（sigma 8），所以高
sigma 的 difference std 低于未裁剪理论值；这不是随机数生成器方差不足。pooled 位移
std 在 sigma 4 尚低于 `0.01 px`，在 sigma 8 超过该值，但生产 ICGN 仍需单独验收。

## 5. 与 VIC “1e6 points/s”公开声明的公平协议

本机不能进行 VIC 对测：它是 4-vCPU Linux 云机，没有合法 VIC Windows
安装/许可证。VIC-3D 网页的原文是单颗 32 核 CPU “up to 1,000,000 points per
second”，但没有公开图像尺寸、subset、搜索、收敛、精度、点定义和计时边界。因此此
数字只能画成“VIC 官方公开上限；非同机、非同配置、不可直接排序”的参考线；本轮也
没有测吞吐，不能声称 HL3 比 VIC 快或慢。

只有满足以下协议，才允许写同机超过/未超过：

1. 在同一台 32 **物理**核机器上合法运行双方软件，固定频率策略，并公开 CPU 型号、
   RAM、NUMA、线程数、编译器/flags；若比较 GPU，另列设备、驱动、精度、传输边界。
2. 使用完全相同的图像、ROI/mask、请求 POI、subset/step、2D/3D 点含义、形函数、
   插值器、粗搜索/初值、收敛阈值、最大迭代、失败判据和输出精度。Stereo 的一个点
   是否包含左右相关及三角化必须写明。
3. 先在同一真值上达到相同 bias/std/RMSE、有效率和误匹配门槛；失败、mask 和仅完成
   整数搜索的点不计入吞吐分子。
4. 分报 kernel-resident、warm end-to-end、cold end-to-end 和至少 100 帧 steady
   state；粗搜索、质量检查和应变是否计时必须双方一致，不能只给一方排除。
5. 预热 5 次，正式至少 20 次，按“成功且通过质量门槛的 POI / wall-clock 秒”报告
   median、P5/P95、首帧延迟、每点迭代数和峰值内存，发布完整配置与原始结果。

在合法同机实验完成前，合规表述只能是“HL3 在所列硬件和公开工作负载达到 X
points/s”，不能是“比 VIC 快 Y 倍”。

## 6. 限制与后续门禁

- 插值脚本只测水平平移、一个纹理 seed、16 POI 和两种插值器；尚无 30-seed bootstrap、
  对角平移、不同 subset/speckle sigma、B-spline 预滤波或 ICGN 迭代影响。
- 噪声位移数字来自一步线性化 stub，不得冒充 ICGN 或 iDICs Challenge 成绩。
- `/tmp` JSON/CSV 是本次运行产物；脚本本身固定 seed，可用上面的命令重建。
- 下一门禁应由稳定的 CPU ICGN API 读取相同生成数据，复跑完整相位/噪声矩阵，并保留
  本轮独立标量估计器作为交叉检查。
