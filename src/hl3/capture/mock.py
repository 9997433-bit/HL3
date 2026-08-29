"""Deterministic, hardware-free image capture for tests and development.

This module never enumerates or opens real cameras.  ``MockCapture`` generates
frames from NumPy alone and is therefore the capture source used by CPU-only CI.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterator, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt


UInt8Image = npt.NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class Frame:
    """One synthetic monochrome frame and its acquisition metadata."""

    image: UInt8Image
    frame_index: int
    timestamp_s: float
    trigger_id: int
    camera_id: str
    source: str = "synthetic"


@runtime_checkable
class CaptureSource(Protocol):
    """Small interface shared by mock and future hardware adapters."""

    def __iter__(self) -> Iterator[Frame]:
        """Yield acquired frames in timestamp order."""


class MockCapture:
    """Repeatable synthetic capture stream with controllable failure modes.

    Parameters are intentionally explicit so tests can reproduce a stream from
    its configuration. ``drop_indices`` simulates acquisition loss while
    retaining original frame and trigger numbering.
    """

    def __init__(
        self,
        *,
        frame_count: int = 8,
        shape: tuple[int, int] = (64, 64),
        fps: float = 30.0,
        seed: int = 0,
        camera_id: str = "mock-0",
        noise_sigma: float = 0.0,
        timestamp_jitter_s: float = 0.0,
        drop_indices: frozenset[int] | set[int] = frozenset(),
    ) -> None:
        height, width = shape
        if frame_count < 0:
            raise ValueError("frame_count must be non-negative")
        if height <= 0 or width <= 0:
            raise ValueError("shape dimensions must be positive")
        if seed < 0:
            raise ValueError("seed must be non-negative")
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("fps must be finite and positive")
        if not math.isfinite(noise_sigma) or noise_sigma < 0:
            raise ValueError("noise_sigma must be finite and non-negative")
        if not math.isfinite(timestamp_jitter_s) or timestamp_jitter_s < 0:
            raise ValueError(
                "timestamp_jitter_s must be finite and non-negative"
            )

        drops = frozenset(drop_indices)
        if any(index < 0 or index >= frame_count for index in drops):
            raise ValueError("drop_indices must refer to configured frames")

        self.frame_count = frame_count
        self.shape = shape
        self.fps = fps
        self.seed = seed
        self.camera_id = camera_id
        self.noise_sigma = noise_sigma
        self.timestamp_jitter_s = timestamp_jitter_s
        self.drop_indices = drops

    def __iter__(self) -> Iterator[Frame]:
        rng = np.random.default_rng(self.seed)
        base = self._base_image(rng)
        previous_timestamp = -math.inf

        for index in range(self.frame_count):
            ideal_timestamp = index / self.fps
            jitter = rng.uniform(
                -self.timestamp_jitter_s, self.timestamp_jitter_s
            )
            timestamp = max(
                0.0,
                ideal_timestamp + jitter,
                math.nextafter(previous_timestamp, math.inf),
            )
            previous_timestamp = timestamp

            image = np.roll(base, shift=(index, 2 * index), axis=(0, 1))
            if self.noise_sigma:
                noisy = image.astype(np.float64) + rng.normal(
                    0.0, self.noise_sigma, size=self.shape
                )
                image = np.clip(np.rint(noisy), 0, 255).astype(np.uint8)
            else:
                image = image.copy()

            if index in self.drop_indices:
                continue

            yield Frame(
                image=image,
                frame_index=index,
                timestamp_s=timestamp,
                trigger_id=index,
                camera_id=self.camera_id,
            )

    def _base_image(self, rng: np.random.Generator) -> UInt8Image:
        """Create a high-contrast synthetic texture without external assets."""

        impulses = rng.random(self.shape) < 0.08
        texture = np.zeros(self.shape, dtype=np.uint16)
        # A compact 3x3 blur makes the impulses speckle-like without SciPy.
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                texture += np.roll(impulses, shift=(dy, dx), axis=(0, 1))
        return np.rint(255.0 * texture / texture.max(initial=1)).astype(np.uint8)
