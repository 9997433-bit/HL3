ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast
<!-- SPDX-License-Identifier: Apache-2.0 -->

# IR2-G1：S2/S3 法律边界扫描

扫描基线：Git `42d04327c3840c63b6be6e8d0961686bc567094c`，并检查扫描时工作树中的未跟踪 S2/S3 smoke test。

## 结论

| 检查项 | 判定 |
|---|---|
| VIC 二进制、安装包、专有库 | **PASS — 未发现** |
| OpenCorr 源码、二进制或 vendor 依赖 | **PASS — 未发现** |
| 显微镜/SEM 畸变实现 | **PASS — 零实现** |

## 证据

### 1. VIC 二进制

- 全工作树按常见二进制、安装包、库和归档后缀扫描，未发现 `.exe`、`.dll`、`.msi`、`.msix`、`.lib`、`.bin`、`.so`、`.dylib`、`.zip`、`.7z`、`.rar`、`.tar` 或 `.gz` 候选。
- Git 全历史对象扫描中最大 blob 为 90,226 bytes（`.agent_workspace/round1/R1-O1-hl3-2d-spec.md`），超过 100 KB 的 blob 为 0；不存在与约 184/225 MB VIC 安装包相符的历史对象。
- 代码中的 VIC 环境变量仅位于 `tests/test_env_guards.py` 的 fail-closed 防御测试；产品名其余命中均为公开对标、法律边界或审计文档，不是二进制、专有格式解析或逆向材料。

### 2. OpenCorr vendor

- `src/`、`tests/`、`src/tests/`、`benchmarks/` 及项目配置中 `OpenCorr`/`opencorr` 零命中。
- 仓库无 `vendor`、`third_party`、`external` 或 `extern` 目录，无 C/C++/CUDA 源文件，也无 OpenCorr 库文件。
- `pyproject.toml` 运行时依赖仅为 NumPy；可选依赖为 pytest、h5py、blake3，没有 OpenCorr、MPL/copyleft DIC 包或外部 DIC 二进制依赖。
- OpenCorr 命中仅存在于 README 和内部规划/审计文档，语境为公开文献参照或明确禁止复制、改写、翻译、vendor 与链接其代码/闭源 GPU 库。

### 3. 显微镜实现

- Python 源码中显微镜相关命中仅为 `src/hl3/stereo/{__init__,calibrate,triangulate}.py` 的明确“不实现”范围声明，以及 `src/hl3/io/hdf5_schema.py` 的 `telecentric` / `stereo_microscope` schema 枚举与参数长度元数据。
- `stereo_microscope` 没有实现绑定或计算分支；当前立体实现是纯 pinhole 模型，不含显微镜非参数畸变场、显微标定、物镜模型、折射校正、SEM 校正、原型或测试向量。
- `tests/test_stereo_synth.py::test_stereo_package_ships_no_distortion_implementation` 检查立体包不得定义或导出畸变/显微镜入口，并要求保留 patent-clearance 范围声明。
- 扫描时新增的 `tests/test_s2_s3_smoke.py` 仅做可选模块导入探针，不含上述三类受限内容。

## 总判定

当前基线满足 `LEGAL.md`、RUL-01/RUL-04 与 Impl-R2“禁止显微镜畸变实现”约束；三项扫描均为 **PASS**。本任务仅创建并暂存本报告，不修改算法源码。
