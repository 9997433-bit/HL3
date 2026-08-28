ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast
<!-- SPDX-License-Identifier: Apache-2.0 -->

# IR1-G1：法律与 SPDX 复核

扫描基线：`e43e22281bca8e29f7cffbd93f164a65d0d86904`。

## 结论

| 检查项 | 结果 |
|---|---|
| VIC 二进制 | **CLEAN** |
| `src/` 显微镜实现 | **CLEAN（零实现）** |
| 根目录许可证 | Apache License 2.0 完整文本存在 |
| 包许可证元数据 | `pyproject.toml` 声明 `Apache-2.0` |
| 本任务新增文件 SPDX | 本报告已声明 `Apache-2.0` |

## 证据

- 对全部 Git 跟踪及未忽略候选文件执行 MIME 检查，未发现 DOS/PE 可执行文件、原生可执行文件、共享库或通用二进制流。
- 全工作树按常见可执行/安装包/归档后缀扫描，未发现 `.exe`、`.msi`、`.dll`、`.lib`、`.bin`、`.zip`、`.7z` 等候选；`src/` 也没有 VIC 产品名、专有格式、破解或许可证绕过字符串。
- `src/` 的显微镜相关命中仅有：
  - `hl3/stereo/{__init__,calibrate,triangulate}.py` 中明确说明非参数显微畸变场**未实现**；
  - `hl3/io/hdf5_schema.py` 中 `stereo_microscope` 与 `telecentric` 仅为 schema 枚举值和参数长度元数据。
- 复核 `src/hl3` 的类、函数及显微镜/远心/畸变/折射/物镜/倍率等标识符后，未发现显微镜标定、显微畸变场、折射校正、物镜模型或显微成像处理实现。ICGN 中的 B-spline 是通用图像插值，不是显微镜模型。

## 变更边界

按独占路径约束，未修改算法源码，也未给其他代理负责的新文件补写 SPDX；本任务只创建并暂存本报告。
