ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# R2-G3：CPU-only CI、Mock 采集与环境边界

## 交付结论

- `.github/workflows/ci.yml` 固定使用 GitHub `ubuntu-latest` 和 Python 3.11，
  同时执行 `tests/` 与 `src/tests/`。
- `tests/test_env_guards.py` 把公开参考 CI 冻结为 Linux、CPU-only 路径：
  Windows/VIC 环境、VIC 安装变量和可见 NVIDIA 设备都会使该 lane 失败。
- `src/hl3/capture/mock.py` 提供无硬件 `CaptureSource`、`Frame` 与
  `MockCapture`。模块不枚举设备、不打开相机、不导入任何厂商 SDK。
- `src/tests/test_mock_capture.py` 覆盖确定性、图像形状/类型、掉帧、噪声、
  时戳抖动、时戳单调性和非法参数。

## Mock 接口

```python
from hl3.capture import MockCapture

capture = MockCapture(
    frame_count=5,
    shape=(64, 64),
    fps=30.0,
    seed=20260828,
    drop_indices={3},
    noise_sigma=1.0,
    timestamp_jitter_s=0.001,
)
for frame in capture:
    consume(frame.image, frame.frame_index, frame.timestamp_s)
```

每次迭代都从配置和种子重建同一序列。帧是 `uint8` 单通道 NumPy 数组；
掉帧后保留原始 `frame_index`/`trigger_id`，因此消费者能检测编号空洞。抖动后
时戳仍严格单调。默认纹理由 NumPy 随机脉冲和 3×3 紧凑卷积生成，未使用
VIC 生成器、安装包、图像或私有格式。

这是 P5 采集抽象的 CI 基座，不冒充实机验证。未来 GenICam/厂商适配器只需
实现同一个可迭代 `CaptureSource`；相机枚举、同步精度和高速落盘仍需独立的
合法实机测试矩阵。

## CI 与环境边界

工作流显式设置：

```text
HL3_CI_CPU_ONLY=1
CUDA_VISIBLE_DEVICES=""
PYTHONPATH=<checkout>/src
```

本 lane 只证明 CPU 参考路径。它不证明 CUDA/Vulkan 性能、真实相机兼容性、
硬触发精度或 VIC 行为。GPU 后端应进入另一个明确配置 GPU 的 lane，不能把
CPU 结果包装成 GPU 吞吐结论。

环境守卫采用强于“不是 Windows-with-VIC”的条件：公开参考 CI 不允许
Windows。这样不会意外把需许可的 VIC 安装、PC key 或 Windows 评估环境带入
开放 CI。仓库与工作流均未下载、安装、调用或逆向 VIC 二进制。

## 验证状态

实现快照提交后执行本地等价命令，并在最终提交中记录结果。
