"""
Negelir — Rich logging with emojis and structured output.
Used across all AI modules for consistent, readable logs.
"""

import logging
import os
import sys

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
})

_console = Console(theme=_THEME, force_terminal=True, file=sys.stderr)

# Map custom level names
_LEVEL_ICONS = {
    logging.DEBUG:    "🔍",
    logging.INFO:     "📋",
    logging.WARNING:  "⚠️",
    logging.ERROR:    "❌",
    logging.CRITICAL: "🔥",
}


class NegelirFormatter(logging.Formatter):
    """Prepends emoji to each log level."""

    def format(self, record: logging.LogRecord) -> str:
        icon = _LEVEL_ICONS.get(record.levelno, "")
        record.msg = f"{icon}  {record.msg}"
        return super().format(record)


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger with rich formatting."""
    level_str = os.getenv("AI_LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_str, logging.DEBUG)

    logger = logging.getLogger(f"negelir.{name}")
    if logger.handlers:
        return logger

    handler = RichHandler(
        console=_console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    handler.setLevel(level)
    logger.addHandler(handler)
    logger.setLevel(level)
    # Pre-Phase-6 audit C2: keep propagation enabled. Suppressing it
    # blinds pytest's `caplog` and any aggregator that listens at the
    # root logger; deduplication of root-handler output should be
    # solved at the root configuration layer, not by silencing
    # children.
    return logger


def section_banner(title: str):
    """Print a visible section separator."""
    _console.rule(f"[bold cyan]  {title}  ", style="cyan")


def success_banner(msg: str):
    """Print a success banner."""
    _console.print(f"\n[bold green]✅ {msg}[/bold green]\n")


def error_banner(msg: str):
    """Print an error banner."""
    _console.print(f"\n[bold red]❌ {msg}[/bold red]\n")
