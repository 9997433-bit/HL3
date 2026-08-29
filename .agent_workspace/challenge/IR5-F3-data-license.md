# IR5-F3 数据许可（父调度器代行）

- 图像由 SEM/iDICs 在 https://idics.org/challenge/ 以 Google Drive 分发，论文写明免费用于算法比较。
- HL3 **缓存到 gitignored `benchmarks/challenge/cache/`**，不把像素 commit，不二次上传。
- 不 vendor OpenCorr / Ncorr / ALDIC / Pyvale 图像，不 vendor OSTI MATLAB 计分器。
- SEM-DIC Round Robin Drive 文件夹写入 manifest `denied`（RUL-04），下载器对 `sem` 抛 `PermissionError`。
- 引用：Reu 2018 doi:10.1007/s11340-017-0349-0；Ahmad 2024 doi:10.1007/s11340-024-01077-7。
