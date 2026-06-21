from __future__ import annotations

import signal
import threading

from ai.common.config import cfg as default_cfg

try:
    import resource
except ImportError:  # pragma: no cover
    resource = None


class BudgetExceeded(RuntimeError):
    """Raised when an NLP request exceeds its allocated CPU or RSS budget."""


class RequestBudget:
    """Per-request CPU + RSS budget guard for the NLP pipeline."""

    def __init__(self, cfg=None, *, humanizer: bool = False) -> None:
        self._cfg = cfg or default_cfg
        self._humanizer = humanizer
        self._cpu_budget_ms = (
            getattr(
                self._cfg,
                "nlp_per_request_cpu_budget_with_humanizer_ms",
                default_cfg.nlp_per_request_cpu_budget_with_humanizer_ms,
            )
            if humanizer
            else getattr(
                self._cfg,
                "nlp_per_request_cpu_budget_ms",
                default_cfg.nlp_per_request_cpu_budget_ms,
            )
        )
        self._rss_budget_mb = getattr(
            self._cfg,
            "nlp_per_request_rss_budget_mb",
            default_cfg.nlp_per_request_rss_budget_mb,
        )
        self._old_handler = None
        self._old_timer = None
        self._old_as = None
        self._active = False

    def __enter__(self) -> RequestBudget:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError(
                "RequestBudget may only be used on the main thread because it uses signal.ITIMER_PROF"
            )
        self._active = True
        self._old_handler = signal.getsignal(signal.SIGPROF)
        signal.signal(signal.SIGPROF, self._on_prof)
        self._old_timer = signal.setitimer(signal.ITIMER_PROF, self._cpu_budget_ms / 1000.0)

        if not self._humanizer and getattr(self._cfg, "nlp_per_request_rss_budget_swap_grace_mb", default_cfg.nlp_per_request_rss_budget_swap_grace_mb):
            try:
                from nlp.lexicon_loader import lexicon_swap_grace_active

                swap_grace_mb = getattr(
                    self._cfg,
                    "nlp_per_request_rss_budget_swap_grace_mb",
                    default_cfg.nlp_per_request_rss_budget_swap_grace_mb,
                )
                if lexicon_swap_grace_active(swap_grace_mb):
                    self._rss_budget_mb += swap_grace_mb
            except Exception:
                pass

        if resource is not None:
            self._old_as = resource.getrlimit(resource.RLIMIT_AS)
            soft, hard = self._old_as
            added = int(self._rss_budget_mb) * 1024 * 1024
            if soft == resource.RLIM_INFINITY:
                new_soft = resource.RLIM_INFINITY
            elif hard == resource.RLIM_INFINITY:
                new_soft = soft + added
            else:
                new_soft = min(soft + added, hard)
            try:
                resource.setrlimit(resource.RLIMIT_AS, (new_soft, hard))
            except ValueError:
                pass

        return self

    def _on_prof(self, signum: int, frame) -> None:
        # Prevent recursive SIGPROF delivery while unwinding the exception.
        signal.signal(signal.SIGPROF, signal.SIG_IGN)
        try:
            signal.setitimer(signal.ITIMER_PROF, 0.0)
        except OSError:
            pass
        self._active = False
        raise BudgetExceeded(f"CPU budget exceeded ({self._cpu_budget_ms} ms)")

    def __exit__(self, exc_type, exc_value, traceback) -> bool | None:
        try:
            if self._old_timer is not None:
                signal.setitimer(signal.ITIMER_PROF, *self._old_timer)
            else:
                signal.setitimer(signal.ITIMER_PROF, 0.0)
            if self._old_handler is not None:
                signal.signal(signal.SIGPROF, self._old_handler)
            if resource is not None and self._old_as is not None:
                try:
                    resource.setrlimit(resource.RLIMIT_AS, self._old_as)
                except ValueError:
                    pass

            if exc_type is MemoryError:
                raise BudgetExceeded(f"RSS budget exceeded ({self._rss_budget_mb} MB)") from None
        finally:
            self._active = False
        return False
