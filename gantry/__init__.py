"""Gantry: A local development environment manager."""

try:
    from importlib.metadata import version, PackageNotFoundError
except ImportError:
    # Python < 3.8
    from importlib_metadata import version, PackageNotFoundError

try:
    __version__ = version("gantry")
except PackageNotFoundError:
    # Package is not installed
    __version__ = "0.1.0"

__all__ = ["__version__"]
