ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# R3-G2 CPU 计量实跑

## 结论

本轮在 Linux CPU-only 环境复跑完整测试，并把 ICGN、可导入的 stereo
合成实验及噪声底板 stub 的机器可读结果写入
`benchmarks/metrology/metrics.json`。

- 全测试：`87 passed`，无失败、无 skip。
- ICGN 合成平移 `(+0.37, -0.42) px`：
  `bias(u,v)=(+4.3763424e-4, -2.0852387e-4) px`，
  合并 RMSE `1.0973212e-3 px`，196/196 POI 收敛。
- `hl3.stereo` 可导入。每相机注入 `0.02 px` 独立像点噪声后，60 次、
  1681 点非线性三角化的 3D RMS 为 `4.8970979 µm`，离面 RMS 为
  `4.7137280 µm`。无噪声 3D RMS 为 `3.3105921e-11 µm`。
- 噪声底板脚本在 `sigma=1 gray` 时测得帧差标准差 `1.4032312 gray`，
  位移 stub 的 pooled `std(u,v)=(0.00178208, 0.00171700) px`，
  pooled `3σ=(0.00534624, 0.00515101) px`。

ICGN 项通过现有测试断言。Stereo 数字是精确针孔标定下的闭环合成几何结果，
不是端到端 Stereo-DIC/Challenge 成绩；噪声位移数字来自一步线性化平移诊断，
不是生产 ICGN，因此后二者不附会正式产品 Gate。

## 运行环境

| 项 | 值 |
|---|---|
| 设备 | CPU only；`CUDA_VISIBLE_DEVICES=''` |
| OS | Linux `6.12.94+` x86_64 |
| Python | 3.12.3 |
| NumPy | 2.4.4 |
| 运行后观测到的 HEAD | `1bcc1deef3d6247d2fa1cbf4d7d6719d1d2d608c` |
| 固定 seed | `20260828` |

精确源码 blob ID 已保存在 `metrics.json`，避免仅靠共享工作区的移动 HEAD
标识实验输入。

## 执行命令

```bash
python3 -m pytest tests src/tests -q

CUDA_VISIBLE_DEVICES='' PYTHONPATH=src:tests python3 -c \
  '# import speckle_pair + hl3.correlate; run the 192², 21² subset,
  # step-8 (+0.37,-0.42) benchmark and emit JSON statistics'

CUDA_VISIBLE_DEVICES='' PYTHONPATH=src python3 -c \
  'from hl3.stereo.calibrate import main; main()'

CUDA_VISIBLE_DEVICES='' PYTHONPATH=src python3 -c \
  '# call run_synthetic_experiment() and emit the exact sigma=0.02
  # nonlinear-triangulation values'

CUDA_VISIBLE_DEVICES='' python3 \
  .agent_workspace/round2/scripts/noise_floor_stub.py \
  --noise-sigmas 0 0.25 0.5 1 2 4 8 \
  --output-json /tmp/r3-g2-noise.json
```

测试输出：

```text
........................................................................ [ 82%]
...............                                                          [100%]
87 passed in 8.66s
```

## ICGN 实测

配置：`192×192`，subset `21×21`，step `8`，196 POI，8× 过采样，
散斑 `sigma=1.4 px`、密度 `0.08/px²`，无图像噪声。生成器使用独立的
过采样傅里叶平移；被测求解器为一阶仿射 IC-GN、ZNSSD、预滤波三次
B-spline 插值。

| 指标 | 实测 |
|---|---:|
| bias u (px) | +0.000437634239650399 |
| bias v (px) | -0.000208523868249167 |
| std u (px) | 0.000975634873926439 |
| std v (px) | 0.00111018161663130 |
| mean absolute error (px) | 0.000807759768784158 |
| RMSE (px) | 0.00109732124575529 |
| max absolute error (px) | 0.00525271353897122 |
| valid / requested | 196 / 196 |
| minimum / mean ZNCC | 0.9992724236 / 0.9999148578 |
| mean / max iterations | 4.17857 / 7 |

## Stereo 实测

`hl3.stereo.calibrate.run_synthetic_experiment()` 成功导入并执行。配置为
254 mm 基线、648 mm 工作距、22.1774° 立体角、精确针孔相机；每台相机的
像点独立加入 `sigma=0.02 px` 噪声。下列统计汇合 60 次 Monte-Carlo ×
1681 个点。

| 指标 | 实测 |
|---|---:|
| noisy 3D RMS (µm) | 4.897097935230754 |
| noisy z RMS (µm) | 4.713728036207430 |
| noisy 3D P95 (µm) | 9.348296085825048 |
| noisy 3D max (µm) | 20.242542444607174 |
| noise-free 3D RMS (µm) | 3.310592134289438e-11 |
| noise-free reprojection RMS (px) | 1.160090527450227e-13 |

## 噪声底板 stub

配置：静态 `96×96` 合成散斑的两次独立含噪观测，subset `31×31`，
step `16`，16 POI，每档 30 次。表中位移是已知零位移处的一步线性化
translation-only 最小二乘诊断。

| 输入 sigma (gray) | 帧差 std (gray) | u pooled std (px) | v pooled std (px) | u 3σ (px) | v 3σ (px) |
|---:|---:|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 | 0 | 0 |
| 0.25 | 0.352309809 | 0.000441363 | 0.000459927 | 0.001324090 | 0.001379781 |
| 0.5 | 0.703590464 | 0.000908668 | 0.000892628 | 0.002726004 | 0.002677884 |
| 1 | 1.403231244 | 0.001782080 | 0.001717004 | 0.005346240 | 0.005151012 |
| 2 | 2.799603453 | 0.003306881 | 0.003596438 | 0.009920642 | 0.010789313 |
| 4 | 5.569590914 | 0.007414401 | 0.006745284 | 0.022243204 | 0.020235853 |
| 8 | 10.969477440 | 0.015423486 | 0.013891883 | 0.046270459 | 0.041675650 |

在 `sigma=1 gray` 时，平均空间
`std(u,v)=(0.00156759, 0.00160150) px`，平均时间
`std(u,v)=(0.00176791, 0.00166536) px`。完整未舍入扫描值、饱和比例、
bias 和源码版本见 `metrics.json`。
