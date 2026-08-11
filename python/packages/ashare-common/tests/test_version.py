from ashare_common import __version__


def test_version() -> None:
    """smoke test: package is importable and has a non-empty version string."""
    assert __version__ == "0.0.0"
    assert isinstance(__version__, str)
