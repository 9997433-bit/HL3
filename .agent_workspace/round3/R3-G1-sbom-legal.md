ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# R3-G1：SBOM 与法律扫描（补录）

本文件由父调度器根据 R3-G1 子代理已完成、但未成功单独落库的结论补录；扫描在 Round 3 集成时复核。

## 结论

| 检查项 | 结果 |
|--------|------|
| 根目录 `LICENSE` | 存在，Apache-2.0 |
| `pyproject.toml` license 元数据 | Apache-2.0 |
| Schema 文档 | CC-BY-4.0（见 docs/schema-hdf5.md） |
| Vendored OpenCorr / CUDA `.lib` | **无** |
| Windows MSI/EXE（VIC 安装包） | **无** |
| 运行时硬依赖 | `numpy>=1.24` |
| 可选依赖 | pytest；h5py；blake3 |
| 显微镜畸变实现 | **无**（仅 schema 枚举槽位） |

## 依赖 allowlist（当前）

- numpy（内核）
- pytest（测试）
- h5py（HDF5 容器，可选）
- blake3（规范哈希，可选，缺失则 blake2b）

禁止：FFTW GPL 作为默认依赖、OpenCorr 源码/二进制、无许可证 DL 权重。

与 R3-F2 法务扫描一致：PASS。
