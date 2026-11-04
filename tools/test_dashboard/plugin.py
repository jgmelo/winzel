"""pytest plugin: collects results and writes the HTML test dashboard.

Options:
  --painel PATH          where to write the dashboard (default: docs/testes/index.html)
  --sem-painel           do not write the dashboard
  --painel-historico     also write this run's JSON to <painel dir>/historico/
                         (only when every test passed; used by the pre-commit hook)
"""

from __future__ import annotations

import inspect
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

from .model import FAILED, PASSED, SKIPPED, RunMeta, TestRecord
from .render import render_html
from .report import (
    history_entry,
    load_history,
    readable_name,
    summarize_message,
    write_history_entry,
)
from .taxonomy import (
    AREAS,
    NO_AREA,
    NO_PHASE,
    PHASES,
    SYSTEM_LABEL,
    SYSTEM_MARKER,
    area_label,
    phase_label,
)

DEFAULT_PATH = Path("docs") / "testes" / "index.html"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("painel", "painel de testes do winzel")
    group.addoption("--painel", default=None, help="caminho do painel HTML")
    group.addoption("--sem-painel", action="store_true", help="não gera o painel")
    group.addoption(
        "--painel-historico",
        action="store_true",
        help="grava também o JSON do histórico (somente se todos os testes passarem)",
    )


def pytest_configure(config: pytest.Config) -> None:
    for name in PHASES:
        config.addinivalue_line("markers", f"{name}: {phase_label(name)}")
    for name in AREAS:
        config.addinivalue_line("markers", f"{name}: área {area_label(name)}")
    config.addinivalue_line("markers", f"{SYSTEM_MARKER}: {SYSTEM_LABEL}")
    if not config.getoption("--sem-painel"):
        config.pluginmanager.register(DashboardPlugin(config), "winzel-dashboard")


def item_metadata(item: pytest.Item) -> TestRecord:
    """Everything the dashboard needs from a collected test, before it runs."""
    names = [m.name for m in item.iter_markers()]
    phase = next((n for n in names if n in PHASES), NO_PHASE)
    area = next((n for n in names if n in AREAS), NO_AREA)
    func = getattr(item, "obj", None)
    try:
        source = inspect.getsource(func) if func is not None else ""
    except OSError, TypeError:
        source = ""
    module = getattr(item, "module", None)
    module_doc = (inspect.getdoc(module) or "") if module is not None else ""
    callspec = getattr(item, "callspec", None)
    try:
        line = func.__code__.co_firstlineno if func is not None else 0
    except AttributeError:
        line = (item.location[1] or 0) + 1
    return TestRecord(
        nodeid=item.nodeid,
        name=readable_name(item.name),
        docstring=(inspect.getdoc(func) or "") if func is not None else "",
        phase=phase,
        area=area,
        outcome=PASSED,
        source=source,
        file=item.nodeid.split("::")[0],
        function=getattr(item, "originalname", None) or item.name.split("[")[0],
        params=callspec.id if callspec is not None else "",
        line=line,
        file_doc=module_doc.strip().splitlines()[0] if module_doc.strip() else "",
    )


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except OSError, subprocess.SubprocessError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def git_meta(root: Path) -> tuple[str | None, str | None, str | None]:
    """(parent hash, parent message, branch). HEAD is the parent of the commit being made."""
    log = _git(root, "log", "-1", "--format=%H%x00%s")
    parent_hash, parent_message = log.split("\x00", 1) if log else (None, None)
    branch = _git(root, "symbolic-ref", "--short", "HEAD")
    return parent_hash, parent_message, branch


class DashboardPlugin:
    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        root = Path(config.rootpath)
        option = config.getoption("--painel")
        self.path = Path(option) if option else root / DEFAULT_PATH
        self.history_dir = self.path.parent / "historico"
        self.write_history = config.getoption("--painel-historico")
        self.records: dict[str, TestRecord] = {}
        self.started = time.perf_counter()
        self.written: list[Path] = []

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        for item in session.items:
            self.records[item.nodeid] = item_metadata(item)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        record = self.records.get(report.nodeid)
        if record is None:
            return
        record.duration_s += report.duration
        if record.outcome == FAILED:
            return
        if report.failed:
            record.outcome = FAILED
            crash = getattr(report.longrepr, "reprcrash", None)
            text = crash.message if crash is not None else str(report.longrepr)
            record.message = summarize_message(text)
        elif report.skipped:
            record.outcome = SKIPPED
            if isinstance(report.longrepr, tuple):
                record.message = summarize_message(str(report.longrepr[2]))

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if not self.records:
            return
        root = Path(self.config.rootpath)
        parent_hash, parent_message, branch = git_meta(root)
        meta = RunMeta(
            generated_at=datetime.now().replace(microsecond=0),
            duration_s=time.perf_counter() - self.started,
            parent_hash=parent_hash,
            parent_message=parent_message,
            branch=branch,
        )
        records = list(self.records.values())
        history = load_history(self.history_dir)
        if self.write_history and exitstatus == 0:
            entry = history_entry(records, meta)
            self.written.append(write_history_entry(self.history_dir, entry))
            history.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(render_html(records, meta, history), encoding="utf-8")
        self.written.insert(0, self.path)

    def pytest_terminal_summary(self, terminalreporter) -> None:
        for path in self.written:
            terminalreporter.write_line(f"painel de testes: {path}")
