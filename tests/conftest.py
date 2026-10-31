"""Shared fixtures and project conventions for the winzel test suite."""

from __future__ import annotations

import pytest
from tools.test_dashboard.taxonomy import AREAS, PHASES


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Every test must declare one phase marker and one area marker (SPEC, seção 9)."""
    missing = []
    for item in items:
        names = {m.name for m in item.iter_markers()}
        if not names & PHASES.keys() or not names & AREAS.keys():
            missing.append(item.nodeid)
    if missing:
        listing = "\n  ".join(missing)
        raise pytest.UsageError(f"testes sem marker de fase e/ou de área:\n  {listing}")
