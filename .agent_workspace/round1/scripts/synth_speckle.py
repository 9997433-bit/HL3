#!/usr/bin/env python3
"""生成高斯散斑及已知刚体平移，供 HL3 ICGN 冒烟测试使用。

只依赖 NumPy。连续纹理由高分辨率随机脉冲经频域高斯卷积得到；
变形使用傅里叶相移，再以块平均模拟像素面积积分。这样不会用被测
ICGN 的低分辨率插值器来生成其自己的测试图。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="输出目录")
    parser.add_argument("--width", type=positive_int, default=256)
    parser.add_argument("--height", type=positive_int, default=256)
    parser.add_argument("--tx", type=float, default=0.37, help="x 向右的平移，px")
    parser.add_argument("--ty", type=float, default=-0.42, help="y 向下的平移，px")
    parser.add_argument(
        "--speckle-sigma",
        type=float,
        default=1.25,
        help="高斯斑点标准差，输出像素",
    )
    parser.add_argument(
        "--density",
        type=float,
        default=0.08,
        help="斑点中心密度，个/输出像素²",
    )
    parser.add_argument(
        "--oversample",
        type=positive_int,
        default=4,
        help="连续纹理近似的线性过采样倍数；严谨基准建议 8 或 16",
    )
    parser.add_argument(
        "--margin",
        type=positive_int,
        default=24,
        help="输出图四周的高分辨率护栏，单位为输出像素",
    )
    parser.add_argument(
        "--noise-sigma",
        type=float,
        default=0.0,
        help="参考/变形图独立高斯噪声的标准差，8-bit gray counts",
    )
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument(
        "--polarity",
        choices=("dark", "bright"),
        default="dark",
        help="dark=白底黑斑，bright=黑底亮斑",
    )
    return parser


def validate(args: argparse.Namespace) -> None:
    if not math.isfinite(args.tx) or not math.isfinite(args.ty):
        raise ValueError("tx/ty 必须为有限数")
    if args.speckle_sigma <= 0 or not math.isfinite(args.speckle_sigma):
        raise ValueError("speckle-sigma 必须为有限正数")
    if args.density <= 0 or not math.isfinite(args.density):
        raise ValueError("density 必须为有限正数")
    if args.noise_sigma < 0 or not math.isfinite(args.noise_sigma):
        raise ValueError("noise-sigma 必须为有限非负数")
    required_margin = max(abs(args.tx), abs(args.ty)) + 4.0 * args.speckle_sigma
    if args.margin <= required_margin:
        raise ValueError(
            f"margin={args.margin} 太小；本配置至少应大于 {required_margin:.2f} px"
        )


def bilinear_impulses(
    height: int,
    width: int,
    count: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """把连续随机中心双线性散射到高分辨率周期画布。"""
    ys = rng.uniform(0.0, height, count)
    xs = rng.uniform(0.0, width, count)
    amplitudes = rng.uniform(0.75, 1.25, count)

    y0 = np.floor(ys).astype(np.int64)
    x0 = np.floor(xs).astype(np.int64)
    dy = ys - y0
    dx = xs - x0
    y1 = (y0 + 1) % height
    x1 = (x0 + 1) % width

    image = np.zeros((height, width), dtype=np.float64)
    np.add.at(image, (y0, x0), amplitudes * (1.0 - dy) * (1.0 - dx))
    np.add.at(image, (y0, x1), amplitudes * (1.0 - dy) * dx)
    np.add.at(image, (y1, x0), amplitudes * dy * (1.0 - dx))
    np.add.at(image, (y1, x1), amplitudes * dy * dx)
    return image


def render_pair(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, int]:
    scale = args.oversample
    canvas_height = (args.height + 2 * args.margin) * scale
    canvas_width = (args.width + 2 * args.margin) * scale
    physical_area = (canvas_height / scale) * (canvas_width / scale)
    speckle_count = max(1, round(args.density * physical_area))

    pattern_seed = np.random.SeedSequence(args.seed).spawn(1)[0]
    rng = np.random.default_rng(pattern_seed)
    impulses = bilinear_impulses(
        canvas_height,
        canvas_width,
        speckle_count,
        rng,
    )

    fy = np.fft.fftfreq(canvas_height)[:, None]
    fx = np.fft.fftfreq(canvas_width)[None, :]
    sigma_hr = args.speckle_sigma * scale
    gaussian = np.exp(-2.0 * math.pi**2 * sigma_hr**2 * (fx * fx + fy * fy))
    texture_spectrum = np.fft.fft2(impulses) * gaussian

    shift_phase = np.exp(
        -2.0j
        * math.pi
        * (fx * (args.tx * scale) + fy * (args.ty * scale))
    )
    reference_hr = np.fft.ifft2(texture_spectrum).real
    deformed_hr = np.fft.ifft2(texture_spectrum * shift_phase).real

    top = args.margin * scale
    left = args.margin * scale
    bottom = top + args.height * scale
    right = left + args.width * scale
    reference_hr = reference_hr[top:bottom, left:right]
    deformed_hr = deformed_hr[top:bottom, left:right]

    def integrate(sensor_field: np.ndarray) -> np.ndarray:
        return sensor_field.reshape(
            args.height,
            scale,
            args.width,
            scale,
        ).mean(axis=(1, 3))

    return integrate(reference_hr), integrate(deformed_hr), speckle_count


def normalize_pair(
    reference: np.ndarray,
    deformed: np.ndarray,
    polarity: str,
) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    low, high = np.percentile(reference, (0.5, 99.5))
    if not high > low:
        raise RuntimeError("生成纹理的动态范围为零")

    def normalize(image: np.ndarray) -> np.ndarray:
        value = 255.0 * np.clip((image - low) / (high - low), 0.0, 1.0)
        if polarity == "dark":
            value = 255.0 - value
        return value.astype(np.float32)

    return normalize(reference), normalize(deformed), (float(low), float(high))


def add_noise(
    clean: np.ndarray,
    sigma: float,
    seed_sequence: np.random.SeedSequence,
) -> np.ndarray:
    if sigma == 0:
        return clean.copy()
    rng = np.random.default_rng(seed_sequence)
    noisy = clean.astype(np.float64) + rng.normal(0.0, sigma, clean.shape)
    return np.clip(noisy, 0.0, 255.0).astype(np.float32)


def write_pgm(path: Path, image: np.ndarray) -> None:
    quantized = np.rint(np.clip(image, 0.0, 255.0)).astype(np.uint8)
    header = f"P5\n{quantized.shape[1]} {quantized.shape[0]}\n255\n".encode("ascii")
    path.write_bytes(header + quantized.tobytes(order="C"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_outputs(
    args: argparse.Namespace,
    reference_clean: np.ndarray,
    deformed_clean: np.ndarray,
    reference: np.ndarray,
    deformed: np.ndarray,
    normalization: tuple[float, float],
    speckle_count: int,
) -> None:
    args.output.mkdir(parents=True, exist_ok=True)
    arrays = {
        "reference_clean.npy": reference_clean,
        "deformed_clean.npy": deformed_clean,
        "reference.npy": reference,
        "deformed.npy": deformed,
    }
    for name, array in arrays.items():
        np.save(args.output / name, array, allow_pickle=False)
    write_pgm(args.output / "reference.pgm", reference)
    write_pgm(args.output / "deformed.pgm", deformed)

    guard = math.ceil(
        args.margin / 2.0
        if args.margin / 2.0
        > max(abs(args.tx), abs(args.ty)) + 3.0 * args.speckle_sigma
        else max(abs(args.tx), abs(args.ty)) + 3.0 * args.speckle_sigma
    )
    valid_roi = {
        "x_min_inclusive": guard,
        "x_max_exclusive": args.width - guard,
        "y_min_inclusive": guard,
        "y_max_exclusive": args.height - guard,
        "note": "ICGN 还应叠加半个 subset 宽度；协议中的最终 ROI 更保守。",
    }
    if (
        valid_roi["x_min_inclusive"] >= valid_roi["x_max_exclusive"]
        or valid_roi["y_min_inclusive"] >= valid_roi["y_max_exclusive"]
    ):
        raise ValueError("图像相对 margin/位移过小，没有有效内部 ROI")

    artifact_names = [*arrays, "reference.pgm", "deformed.pgm"]
    metadata: dict[str, Any] = {
        "schema": "hl3.synthetic-speckle.translation.v1",
        "generator": {
            "method": "oversampled impulses + Fourier Gaussian convolution/shift",
            "numpy_version": np.__version__,
            "seed": args.seed,
            "oversample": args.oversample,
            "margin_px": args.margin,
        },
        "image": {
            "width": args.width,
            "height": args.height,
            "dtype_npy": "float32",
            "range": [0.0, 255.0],
            "pgm_quantization_bits": 8,
            "coordinate_convention": "pixel centers; origin top-left; x right; y down",
            "valid_roi": valid_roi,
        },
        "pattern": {
            "profile": "isotropic Gaussian",
            "speckle_sigma_px": args.speckle_sigma,
            "center_density_per_px2": args.density,
            "center_count_on_padded_canvas": speckle_count,
            "polarity": args.polarity,
            "reference_normalization_percentiles": [0.5, 99.5],
            "reference_normalization_raw_values": list(normalization),
        },
        "deformation": {
            "type": "rigid_translation",
            "u_px": args.tx,
            "v_px": args.ty,
            "forward_mapping": "x_deformed=x_reference+u; y_deformed=y_reference+v",
            "inverse_sampling": "I_deformed(x,y)=I_continuous(x-u,y-v)",
            "strain_ground_truth": 0.0,
        },
        "noise": {
            "model": "independent additive Gaussian then clip",
            "sigma_gray_counts": args.noise_sigma,
            "reference_and_deformed_are_independent": True,
        },
        "artifacts_sha256": {
            name: sha256(args.output / name) for name in artifact_names
        },
        "limitations": [
            "这是平移冒烟测试原型，不替代 iDICs Challenge 的官方生成器。",
            "严谨插值偏差研究应使用 oversample=8/16 并验证过采样收敛。",
            "频域画布是周期的；输出 crop 和 margin 用于隔离周期边界。",
        ],
    }
    (args.output / "ground_truth.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = build_parser().parse_args()
    validate(args)
    reference_raw, deformed_raw, speckle_count = render_pair(args)
    reference_clean, deformed_clean, normalization = normalize_pair(
        reference_raw,
        deformed_raw,
        args.polarity,
    )
    noise_seeds = np.random.SeedSequence(args.seed).spawn(3)
    reference = add_noise(reference_clean, args.noise_sigma, noise_seeds[1])
    deformed = add_noise(deformed_clean, args.noise_sigma, noise_seeds[2])
    save_outputs(
        args,
        reference_clean,
        deformed_clean,
        reference,
        deformed,
        normalization,
        speckle_count,
    )
    print(f"已写入 {args.output}")
    print(f"真值位移: u={args.tx:.9g} px, v={args.ty:.9g} px")


if __name__ == "__main__":
    main()
