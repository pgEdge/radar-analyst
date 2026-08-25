"""Sanity tests that the package can be imported and exposes a version."""

import radar_analyst


def test_package_imports() -> None:
    assert radar_analyst is not None


def test_package_has_version() -> None:
    assert isinstance(radar_analyst.__version__, str)
    assert radar_analyst.__version__
