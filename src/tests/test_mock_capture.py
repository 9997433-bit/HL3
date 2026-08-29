from __future__ import annotations

import numpy as np
import pytest

from hl3.capture import CaptureSource, MockCapture


def test_mock_capture_is_deterministic_and_hardware_free() -> None:
    first = list(MockCapture(frame_count=3, shape=(12, 16), seed=17))
    second = list(MockCapture(frame_count=3, shape=(12, 16), seed=17))

    assert len(first) == 3
    assert isinstance(MockCapture(), CaptureSource)
    for left, right in zip(first, second, strict=True):
        assert left.source == "synthetic"
        assert left.image.shape == (12, 16)
        assert left.image.dtype == np.uint8
        np.testing.assert_array_equal(left.image, right.image)
        assert left.timestamp_s == right.timestamp_s


def test_mock_capture_injects_drops_noise_and_monotonic_jitter() -> None:
    capture = MockCapture(
        frame_count=5,
        shape=(8, 9),
        fps=20.0,
        seed=3,
        noise_sigma=2.0,
        timestamp_jitter_s=0.2,
        drop_indices={1, 3},
    )

    frames = list(capture)

    assert [frame.frame_index for frame in frames] == [0, 2, 4]
    assert [frame.trigger_id for frame in frames] == [0, 2, 4]
    assert all(
        previous.timestamp_s < current.timestamp_s
        for previous, current in zip(frames, frames[1:])
    )


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("frame_count", -1),
        ("shape", (0, 8)),
        ("seed", -1),
        ("fps", 0.0),
        ("noise_sigma", -0.1),
        ("timestamp_jitter_s", -0.1),
        ("drop_indices", {2}),
    ],
)
def test_mock_capture_rejects_invalid_configuration(
    keyword: str, value: object
) -> None:
    kwargs: dict[str, object] = {"frame_count": 2}
    kwargs[keyword] = value
    with pytest.raises(ValueError):
        MockCapture(**kwargs)
