ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast
<!-- SPDX-License-Identifier: Apache-2.0 -->

# IR3-G1：S4 法律与实施边界扫描

扫描基线：Git `b141aadb4f339516fc00ad312c0eafaf5d15520d`；同时检查扫描时工作树中可见的 S4 smoke 文件和 `pyproject.toml` 的可选 `viz` 依赖变更。

## 结论

| 检查项 | 判定 |
|---|---|
| VIC 安装包、二进制、专有库或逆向材料 | **PASS — 未发现** |
| OpenCorr 源码、二进制或 vendor 依赖 | **PASS — 未发现** |
| GPU 内核或相机 SDK 集成 | **PASS — 零实现** |
| 显微镜/SEM 畸变实现 | **PASS — 零实现** |
| S4 可见依赖许可边界 | **PASS** |

## 证据

### 1. VIC 与 OpenCorr

- 全工作树按常见可执行文件、安装包、原生库和归档后缀扫描，未发现 `.exe`、`.dll`、`.msi`、`.msix`、`.lib`、`.bin`、`.so`、`.dylib`、`.zip`、`.7z`、`.rar`、`.tar` 或 `.gz` 候选。
- Git 全历史对象的最大 blob 为 90,226 bytes（`.agent_workspace/round1/R1-O1-hl3-2d-spec.md`），超过 100 KB 的 blob 为 0；没有与公开所述约 184/225 MB VIC 安装包相符的历史对象。
- `src/`、`tests/`、`src/tests/`、`benchmarks/` 与项目依赖中没有 OpenCorr 源码、库或依赖。`src/hl3.egg-info/PKG-INFO` 中的唯一 OpenCorr 字样来自 README 的“不 vendor、不改写、不翻译”边界声明，不是代码复用。
- VIC 字样仅用于公开对标、免责声明和 fail-closed 环境护栏；未发现专有格式解析、反编译、密钥生成、许可证绕过或专有 UI 仿制材料。

### 2. S4 禁止实现

- 工作树中没有 C/C++、CUDA、PTX、OpenCL 或其他 GPU 内核源文件；`src/` 也没有 CuPy、PyTorch、JAX、Numba 或 GPU 后端导入。
- `src/` 未发现 GenICam/GenTL、Basler pylon、FLIR Spinnaker、Harvesters 或其他相机厂商 SDK 绑定。现有 `hl3.capture.mock` 仍是纯软件模拟采集，不接触硬件 SDK。
- Python 源码中未发现以畸变、Brown–Conrady、远心、显微镜、物镜、折射、倍率或 SEM 命名的函数/类定义。`stereo_microscope` / `telecentric` 仍仅是 HDF5 schema 枚举与元数据槽位；立体计算路径仍声明并实现纯 pinhole L0。
- `tests/test_stereo_synth.py::test_stereo_package_ships_no_distortion_implementation` 持续对 `hl3.stereo` 的相关定义和公开导出执行 fail-closed 检查。

### 3. 依赖与扫描范围

- 项目自身许可证仍为根目录 Apache License 2.0 完整文本，`pyproject.toml` 包元数据声明 `Apache-2.0`。
- 扫描时可见的 S4 依赖变化仅为可选 extra `viz = ["matplotlib"]`；Matplotlib 未被 vendor，未进入核心运行时依赖，也未引入 VIC/OpenCorr、GPU 内核或相机 SDK。
- 扫描时新增的 `tests/test_s4_smoke.py` 和 `IR3-G2-smoke.md` 只探测 `hl3.cli.run`、`hl3.viz`、`hl3.fea` 的可选导入，不包含受限实现。

## 总判定

扫描时可见树满足 `LEGAL.md` 与 Impl-R3“禁止 GPU 内核、禁止相机 SDK、禁止显微镜”约束；全部检查项 **PASS**。这是对上述提交及扫描时工作树快照的判定，不为扫描后才加入的文件提供前向豁免；后续新增 S4 实现仍须受相同 fail-closed 门约束。本任务只创建并暂存本报告，不修改产品源码。
