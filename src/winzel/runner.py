"""Runs checks in parallel threads, each with its own timeout.

- `requires_admin` without elevation -> SKIPPED, not executed.
- Exception or timeout -> ERROR with a message; other checks are unaffected.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from .config import check_timeout
from .context import Context
from .models import Check, CheckResult, Status

ProgressCallback = Callable[[CheckResult], None]


def skipped(check: Check) -> CheckResult:
    return CheckResult(
        check_id=check.id,
        status=Status.SKIPPED,
        summary="pulada: requer administrador",
    )


def failed(check: Check, message: str, duration_ms: int) -> CheckResult:
    return CheckResult(
        check_id=check.id,
        status=Status.ERROR,
        summary=f"erro: {message}",
        error=message,
        duration_ms=duration_ms,
    )


def _run_one(check: Check, ctx: Context) -> CheckResult:
    started = time.perf_counter()
    try:
        result = check.run(ctx)
    except Exception as exc:  # any failure in a check becomes an ERROR result
        message = str(exc) or type(exc).__name__
        return failed(check, message, int((time.perf_counter() - started) * 1000))
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result


def run_checks(
    checks: list[Check],
    ctx: Context,
    on_progress: ProgressCallback | None = None,
) -> list[CheckResult]:
    """Run all checks; results come back in the same order as `checks`."""
    results: dict[str, CheckResult] = {}

    def done(result: CheckResult) -> None:
        results[result.check_id] = result
        if on_progress is not None:
            on_progress(result)

    runnable = []
    for check in checks:
        if check.requires_admin and not ctx.is_admin:
            done(skipped(check))
        else:
            runnable.append(check)

    if runnable:
        executor = ThreadPoolExecutor(max_workers=len(runnable), thread_name_prefix="winzel-check")
        start = time.monotonic()
        pending: dict[Future, tuple[Check, float]] = {}
        for check in runnable:
            timeout = check_timeout(ctx.config, check.id, check.timeout_s)
            pending[executor.submit(_run_one, check, ctx)] = (check, start + timeout)
        try:
            while pending:
                next_deadline = min(deadline for _, deadline in pending.values())
                finished, _ = wait(
                    pending,
                    timeout=max(0.0, next_deadline - time.monotonic()),
                    return_when=FIRST_COMPLETED,
                )
                for future in finished:
                    pending.pop(future)
                    done(future.result())
                now = time.monotonic()
                for future, (check, deadline) in list(pending.items()):
                    if now >= deadline:
                        pending.pop(future)
                        timeout_s = deadline - start
                        done(
                            failed(
                                check, f"tempo esgotado ({timeout_s:g} s)", int(timeout_s * 1000)
                            )
                        )
        finally:
            # Timed-out threads cannot be killed; do not wait for them.
            executor.shutdown(wait=False, cancel_futures=True)

    return [results[check.id] for check in checks]
