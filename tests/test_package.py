"""Minimal sanity tests for the package foundation."""

import real_estate_agent


def test_package_is_importable():
    """The package can be imported without side effects."""
    assert real_estate_agent is not None


def test_package_version():
    """The package exposes the expected version."""
    assert real_estate_agent.__version__ == "0.1.0"
