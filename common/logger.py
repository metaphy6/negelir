"""Shared logging infrastructure."""
import logging


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a given module name."""
    return logging.getLogger(name)


def section_banner(title: str) -> None:
    """Print a formatted banner for a section."""
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width + "\n")


def success_banner(message: str) -> None:
    """Print a formatted success banner."""
    width = 60
    print("\n" + "✓" * width)
    print(f"  {message}")
    print("✓" * width + "\n")


def error_banner(message: str) -> None:
    """Print a formatted error banner."""
    width = 60
    print("\n" + "✗" * width)
    print(f"  {message}")
    print("✗" * width + "\n")

