"""Shared logging infrastructure."""
import logging


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a given module name."""
    return logging.getLogger(name)
