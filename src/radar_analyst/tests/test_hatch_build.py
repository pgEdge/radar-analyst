"""The Astro bundle build hook and its wheel force-include wiring.

``src/radar_analyst/webdist`` is generated at build time and is not
tracked, so a clean checkout has no such directory. The wheel must
still build there, in API-only mode.
"""

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOK_PATH = _REPO_ROOT / "hatch_build.py"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

pytestmark = pytest.mark.skipif(
    not _HOOK_PATH.is_file(),
    reason="build hook is only present in a source checkout",
)


class _StubHookBase:
    """Stand-in for hatchling's BuildHookInterface."""

    def __init__(self, root: str, app: Any) -> None:
        self.root = root
        self.app = app


def _load_hook() -> ModuleType:
    """Import ``hatch_build`` without hatchling installed."""
    pkg = ModuleType("hatchling")
    iface = ModuleType(
        "hatchling.builders.hooks.plugin.interface"
    )
    setattr(iface, "BuildHookInterface", _StubHookBase)
    injected = {
        "hatchling": pkg,
        "hatchling.builders": ModuleType("hatchling.builders"),
        "hatchling.builders.hooks": ModuleType(
            "hatchling.builders.hooks"
        ),
        "hatchling.builders.hooks.plugin": ModuleType(
            "hatchling.builders.hooks.plugin"
        ),
        "hatchling.builders.hooks.plugin.interface": iface,
    }
    saved = {k: sys.modules.get(k) for k in injected}
    sys.modules.update(injected)
    try:
        spec = importlib.util.spec_from_file_location(
            "_radar_hatch_build", _HOOK_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


def _run_hook(root: Path) -> dict[str, Any]:
    """Run the hook against *root* and return its build_data."""
    module = _load_hook()
    messages: list[str] = []
    app = SimpleNamespace(display_info=messages.append)
    hook = module.AstroBundleHook(str(root), app)
    build_data: dict[str, Any] = {"force_include": {}}
    hook.initialize("standard", build_data)
    return build_data


def test_missing_web_dist_forces_no_include(
    tmp_path: Path,
) -> None:
    """No Astro output means no force-include of a missing path."""
    build_data = _run_hook(tmp_path)

    target = tmp_path / "src" / "radar_analyst" / "webdist"
    assert not target.exists()
    for source in build_data["force_include"]:
        assert Path(source).exists(), (
            f"force-include points at missing {source}"
        )


def test_present_web_dist_is_bundled(tmp_path: Path) -> None:
    """A built console is copied in and force-included."""
    web_dist = tmp_path / "web" / "dist"
    web_dist.mkdir(parents=True)
    (web_dist / "index.html").write_text("<html></html>")

    build_data = _run_hook(tmp_path)

    target = tmp_path / "src" / "radar_analyst" / "webdist"
    assert (target / "index.html").read_text() == "<html></html>"
    assert (
        build_data["force_include"][str(target)]
        == "radar_analyst/webdist"
    )


def test_stale_webdist_removed_when_web_dist_absent(
    tmp_path: Path,
) -> None:
    """A leftover bundle does not survive into an API-only wheel."""
    target = tmp_path / "src" / "radar_analyst" / "webdist"
    target.mkdir(parents=True)
    (target / "stale.html").write_text("old")

    _run_hook(tmp_path)

    assert not target.exists()


def test_pyproject_has_no_static_webdist_include() -> None:
    """The force-include must be set by the hook, not statically.

    A static entry makes hatchling fail on any tree without a
    prior Astro build.
    """
    with _PYPROJECT.open("rb") as fh:
        config = tomllib.load(fh)

    wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert "force-include" not in wheel
