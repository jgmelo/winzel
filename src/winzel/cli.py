"""Entry points: `python -m winzel` (interface) and `python -m winzel snapshot`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from .checks import all_checks
from .config import ConfigError, load_config, use_emoji
from .context import Context, production_context
from .diff import Change
from .models import Check
from .snapshot import SnapshotReport, take_snapshot
from .status import format_date
from .store import Store, default_db_path

ADMIN_WARNING = (
    "Snapshot feito sem privilégios de administrador: "
    "checagens que exigem elevação aparecem como puladas."
)
KIND_LABELS = {"auto": "automático", "manual": "manual"}


def change_symbol(change: Change, emoji: bool) -> str:
    return change.kind.symbol if emoji else change.kind.text_symbol


def format_change(change: Change, category_label: str, emoji: bool) -> str:
    if change.old_version is not None and change.new_version is not None:
        versions = f"{change.old_version} → {change.new_version}"
    else:
        versions = change.new_version or change.old_version or ""
    return f"  {change_symbol(change, emoji)} {category_label}: {change.name}  {versions}".rstrip()


def format_report(report: SnapshotReport, emoji: bool = True) -> str:
    snap = report.snapshot
    lines = [
        f"winzel — snapshot #{snap.id} ({KIND_LABELS.get(snap.kind, snap.kind)}) "
        f"em {format_date(snap.created_at)}",
        "Referência: linha de base",
    ]
    if not snap.is_admin:
        lines.append(f"{'⚠ ' if emoji else '[!] '}{ADMIN_WARNING}")
    lines.append("")
    for o in report.outcomes:
        lines.append(
            f"{o.status.symbol(emoji)} {o.label}: {o.result.summary}  [{o.result.duration_ms} ms]"
        )
    labels = {o.check_id: o.label for o in report.outcomes}
    if report.changes:
        lines += ["", "Mudanças:"]
        lines += [format_change(c, labels[c.category], emoji) for c in report.changes]
    overall = report.overall_status
    lines += ["", f"Status geral: {overall.symbol(emoji)} {overall.label}"]
    return "\n".join(lines)


def cmd_snapshot(store: Store, ctx: Context, checks: list[Check], out: TextIO) -> int:
    report = take_snapshot(store, ctx, checks, kind="manual")
    print(format_report(report, use_emoji(ctx.config)), file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="winzel",
        description="Observa, registra e compara o estado da instalação do Windows.",
    )
    parser.add_argument("--db", type=Path, help=f"banco SQLite (padrão: {default_db_path()})")
    parser.add_argument("--config", type=Path, help="config.toml do usuário")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("snapshot", help="roda as checagens, grava o snapshot e imprime o resumo")
    return parser


def main(
    argv: list[str] | None = None,
    context_factory: Callable[[dict], Context] = production_context,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"winzel: {exc}", file=sys.stderr)
        return 2
    ctx = context_factory(config)
    store = Store.open(args.db or default_db_path())
    try:
        if args.command == "snapshot":
            return cmd_snapshot(store, ctx, all_checks(), out)
        from .ui.app import WinzelApp

        WinzelApp(store=store, ctx=ctx, checks=all_checks()).run()
        return 0
    finally:
        store.close()
