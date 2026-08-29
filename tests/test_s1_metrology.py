"""S1 metrology acceptance tests using the repository's synthetic fixtures."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest

np = pytest.importorskip("numpy", reason="NumPy is required for S1 metrology tests")


SYNTH_PATH = (
    Path(__file__).resolve().parents[1]
    / ".agent_workspace"
    / "round1"
    / "scripts"
    / "synth_speckle.py"
)
TRANSLATION = (0.37, -0.42)


def _load_synth() -> ModuleType:
    if not SYNTH_PATH.is_file():
        pytest.skip(f"existing synthetic generator is missing: {SYNTH_PATH}")
    spec = importlib.util.spec_from_file_location("hl3_s1_synth_speckle", SYNTH_PATH)
    if spec is None or spec.loader is None:
        pytest.skip(f"cannot load existing synthetic generator: {SYNTH_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_small_translation_mean_absolute_error(tmp_path: Path) -> None:
    """The first-order IC-GN reference kernel must clear the S1 0.05 px gate."""
    correlate = pytest.importorskip(
        "hl3.correlate", reason="hl3.correlate is not available"
    )
    required = ("ICGNParams", "Status", "icgn_first_order", "make_grid")
    missing = [name for name in required if not hasattr(correlate, name)]
    assert not missing, f"hl3.correlate is missing required API: {missing}"

    synth = _load_synth()
    args = synth.build_parser().parse_args(
        [
            "--output",
            str(tmp_path),
            "--width",
            "128",
            "--height",
            "128",
            "--tx",
            str(TRANSLATION[0]),
            "--ty",
            str(TRANSLATION[1]),
            "--oversample",
            "8",
        ]
    )
    synth.validate(args)
    raw_reference, raw_deformed, _ = synth.render_pair(args)
    reference, deformed, _ = synth.normalize_pair(
        raw_reference, raw_deformed, args.polarity
    )

    params = correlate.ICGNParams(subset_radius=10, step=16)
    points = correlate.make_grid(reference.shape, params, margin=32)
    result = correlate.icgn_first_order(reference, deformed, points, params)

    assert np.all(result.status == int(correlate.Status.CONVERGED))
    error_u = result.u - TRANSLATION[0]
    error_v = result.v - TRANSLATION[1]
    mean_abs_error = float(
        np.mean(np.abs(np.concatenate((error_u, error_v))))
    )
    max_abs_error = float(
        np.max(np.abs(np.concatenate((error_u, error_v))))
    )
    print(
        "S1 translation: "
        f"mean_abs_error_px={mean_abs_error:.9f}, "
        f"max_abs_error_px={max_abs_error:.9f}, points={result.n_points}"
    )

    assert mean_abs_error < 0.05, (
        f"mean |error| = {mean_abs_error:.6f} px, expected < 0.05 px"
    )


def _strain_callable(module: ModuleType) -> Callable[..., Any]:
    for name in ("compute_strain", "local_plane_fit", "strain_from_displacement"):
        function = getattr(module, name, None)
        if callable(function):
            return function
    pytest.fail(
        "hl3.strain exists but exposes none of compute_strain, local_plane_fit, "
        "or strain_from_displacement"
    )


def _invoke_strain(
    function: Callable[..., Any],
    module: ModuleType,
    x: Any,
    y: Any,
    u: Any,
    v: Any,
) -> Any:
    """Call the strain entry point using its public, named array parameters."""
    shape = u.shape
    values = {
        "x": x,
        "grid_x": x,
        "x_coords": x,
        "y": y,
        "grid_y": y,
        "y_coords": y,
        "u": u,
        "displacement_u": u,
        "v": v,
        "displacement_v": v,
        "valid": np.ones(shape, dtype=bool),
        "mask": np.zeros(shape, dtype=bool),
        "window_pts": 5,
        "window_points": 5,
        "window_size": 5,
        "step": 1.0,
        "step_px": 1.0,
        "spacing": 1.0,
        "subset_px": 21,
        "subset_size": 21,
        "tensor": "engineering",
        "method": "local_plane_fit",
    }

    params_class = getattr(module, "StrainParams", None)
    if callable(params_class):
        params_signature = inspect.signature(params_class)
        params_kwargs = {
            name: values[name]
            for name in params_signature.parameters
            if name in values
        }
        values["params"] = params_class(**params_kwargs)
        values["config"] = values["params"]

    signature = inspect.signature(function)
    kwargs: dict[str, Any] = {}
    unsupported: list[str] = []
    for name, parameter in signature.parameters.items():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if name in values:
            kwargs[name] = values[name]
        elif parameter.default is inspect.Parameter.empty:
            unsupported.append(name)
    assert not unsupported, (
        f"unsupported required parameters on {function.__name__}: {unsupported}"
    )
    return function(**kwargs)


def _strain_component(result: Any, name: str) -> Any:
    if isinstance(result, dict):
        return result[name]
    if hasattr(result, name):
        return getattr(result, name)
    strain = getattr(result, "strain", None)
    if isinstance(strain, dict):
        return strain[name]
    pytest.fail(f"strain result does not expose {name}")


def test_uniform_strain_smoke() -> None:
    """Recover a constant engineering strain when the optional module exists."""
    strain = pytest.importorskip("hl3.strain", reason="hl3.strain is not available")

    y, x = np.mgrid[0:9, 0:9].astype(np.float64)
    expected_exx = 0.01
    expected_eyy = -0.004
    u = expected_exx * x
    v = expected_eyy * y

    result = _invoke_strain(_strain_callable(strain), strain, x, y, u, v)
    exx = np.asarray(_strain_component(result, "exx"), dtype=np.float64)
    eyy = np.asarray(_strain_component(result, "eyy"), dtype=np.float64)
    exy = np.asarray(_strain_component(result, "exy"), dtype=np.float64)
    finite = np.isfinite(exx) & np.isfinite(eyy) & np.isfinite(exy)

    assert np.any(finite), "uniform strain result contains no finite values"
    measured_exx = float(np.mean(exx[finite]))
    measured_eyy = float(np.mean(eyy[finite]))
    measured_exy = float(np.mean(exy[finite]))
    print(
        "S1 uniform strain: "
        f"exx={measured_exx:.9f}, eyy={measured_eyy:.9f}, "
        f"exy={measured_exy:.9f}, finite={int(np.count_nonzero(finite))}"
    )

    assert measured_exx == pytest.approx(expected_exx, abs=5e-4)
    assert measured_eyy == pytest.approx(expected_eyy, abs=5e-4)
    assert measured_exy == pytest.approx(0.0, abs=5e-4)
