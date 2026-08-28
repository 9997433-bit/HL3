# HL3 DIC 产品计划骨架（Round 1 起填充）

## 产品定义

- **HL3-2D**：单相机二维数字图像相关，对标 VIC-2D 8，目标全面超过。
- **HL3-3D**：双目/多目立体三维 DIC，对标 VIC-3D 11，目标全面超过。

共享内核、共享可视化、共享采集抽象、共享 Python API。

## 推荐技术栈（待 Round 审定）

- 内核：C++20 + 可选 CUDA/Vulkan 计算
- 绑定：pybind11（Python-first，不是后加脚本）
- GUI：Qt 6 或 GPU 可视化（VisPy/wgpu）+ 科学绘图
- 数据：HDF5 / Zarr 为主，CSV/VTK/Exodus 导出
- 相机：GenICam/Harvester + 厂商 SDK 适配层（对标 VIC-Snap）
- 测试：合成散斑 + iDICs Challenge + 物理刚体夹具协议

## 工作包（WBS）

见后续 `round1/` 各子代理报告，由父调度器收敛为最终路线图。
