"""Entry points.

python -m winzel                          interface (takes an automatic snapshot)
python -m winzel snapshot [--referencia]  manual snapshot, prints the summary
python -m winzel milestones               lists milestones
python -m winzel milestone NOME [--nota]  pins the latest snapshot as a milestone
python -m winzel milestone --apagar NOME  deletes a milestone (asks for confirmation)
"""

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
from .reference import reference_by_name
from .snapshot import SnapshotReport, take_snapshot
from .status import format_date
from .store import MilestoneError, Store, default_db_path

ADMIN_WARNING = (
    "Snapshot feito sem privilégios de administrador: "
    "checagens que exigem elevação aparecem como puladas."
)
KIND_LABELS = {"auto": "automático", "manual": "manual"}

InputFn = Callable[[str], str]


def change_symbol(change: Change, emoji: bool) -> str:
    return change.kind.symbol if emoji else change.kind.text_symbol


def approval_mark(change: Change, emoji: bool) -> str:
    if not change.approved:
        return ""
    return "✔ aprovado" if emoji else "[aprovado]"


def format_change(change: Change, category_label: str, emoji: bool) -> str:
    if change.old_version is not None and change.new_version is not None:
        versions = f"{change.old_version} → {change.new_version}"
    else:
        versions = change.new_version or change.old_version or ""
    line = f"  {change_symbol(change, emoji)} {category_label}: {change.name}  {versions}"
    mark = approval_mark(change, emoji)
    return f"{line.rstrip()}  {mark}" if mark else line.rstrip()


def format_report(report: SnapshotReport, emoji: bool = True) -> str:
    snap = report.snapshot
    lines = [
        f"winzel — snapshot #{snap.id} ({KIND_LABELS.get(snap.kind, snap.kind)}) "
        f"em {format_date(snap.created_at)}",
        f"Referência: {report.reference_label}",
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
    if report.pruned:
        lines.append(f"Retenção: {len(report.pruned)} snapshots automáticos antigos removidos.")
    return "\n".join(lines)


def cmd_snapshot(
    store: Store,
    ctx: Context,
    checks: list[Check],
    out: TextIO,
    reference_name: str | None = None,
) -> int:
    reference = None
    if reference_name:
        reference = reference_by_name(store, reference_name)
        if reference is None:
            print(f"winzel: referência desconhecida: {reference_name}", file=sys.stderr)
            return 2
    report = take_snapshot(store, ctx, checks, kind="manual", reference=reference)
    print(format_report(report, use_emoji(ctx.config)), file=out)
    return 0


def cmd_milestones(store: Store, out: TextIO) -> int:
    milestones = store.milestones()
    if not milestones:
        print("Nenhum milestone (ainda não há snapshots).", file=out)
        return 0
    for m in milestones:
        note = f" — {m.note}" if m.note else ""
        print(
            f"{m.name}  snapshot #{m.snapshot.id} de {format_date(m.snapshot.created_at)}{note}",
            file=out,
        )
    return 0


def cmd_milestone_create(store: Store, ctx: Context, name: str, note: str, out: TextIO) -> int:
    latest = store.latest_snapshot()
    if latest is None:
        print("winzel: não há snapshot para fixar; rode `winzel snapshot` antes.", file=sys.stderr)
        return 2
    try:
        milestone = store.create_milestone(latest.id, name, note, ctx.now())
    except MilestoneError as exc:
        print(f"winzel: {exc}", file=sys.stderr)
        return 2
    print(
        f"Milestone {milestone.name} criado no snapshot #{latest.id} "
        f"({format_date(latest.created_at)}).",
        file=out,
    )
    return 0


def cmd_milestone_delete(store: Store, name: str, out: TextIO, ask: InputFn) -> int:
    found = store.milestone(name)
    if found is None:
        print(f"winzel: milestone {name} não existe", file=sys.stderr)
        return 2
    answer = ask(f"Apagar o milestone {found.name}? Esta ação não pode ser desfeita. [s/N] ")
    if answer.strip().lower() not in ("s", "sim"):
        print("Nada foi apagado.", file=out)
        return 1
    try:
        store.delete_milestone(found.name)
    except MilestoneError as exc:
        print(f"winzel: {exc}", file=sys.stderr)
        return 2
    print(f"Milestone {found.name} apagado.", file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="winzel",
        description="Observa, registra e compara o estado da instalação do Windows.",
    )
    parser.add_argument("--db", type=Path, help=f"banco SQLite (padrão: {default_db_path()})")
    parser.add_argument("--config", type=Path, help="config.toml do usuário")
    sub = parser.add_subparsers(dest="command")
    snap = sub.add_parser("snapshot", help="roda as checagens, grava o snapshot e imprime o resumo")
    snap.add_argument(
        "--referencia",
        metavar="NOME|ultimo",
        help="milestone de referência ou `ultimo` (padrão: o milestone mais recente)",
    )
    sub.add_parser("milestones", help="lista os milestones")
    mile = sub.add_parser("milestone", help="fixa o último snapshot como milestone, ou apaga um")
    mile.add_argument("nome", nargs="?", help="nome do novo milestone")
    mile.add_argument("--nota", default="", help="nota do novo milestone")
    mile.add_argument("--apagar", metavar="NOME", help="apaga o milestone (pede confirmação)")
    return parser


def main(
    argv: list[str] | None = None,
    context_factory: Callable[[dict], Context] = production_context,
    out: TextIO | None = None,
    ask: InputFn = input,
) -> int:
    out = out or sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "milestone" and bool(args.nome) == bool(args.apagar):
        parser.error("informe um NOME para criar ou --apagar NOME")
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"winzel: {exc}", file=sys.stderr)
        return 2
    ctx = context_factory(config)
    store = Store.open(args.db or default_db_path())
    try:
        if args.command == "snapshot":
            return cmd_snapshot(store, ctx, all_checks(), out, args.referencia)
        if args.command == "milestones":
            return cmd_milestones(store, out)
        if args.command == "milestone":
            if args.apagar:
                return cmd_milestone_delete(store, args.apagar, out, ask)
            return cmd_milestone_create(store, ctx, args.nome, args.nota, out)
        from .ui.app import WinzelApp

        WinzelApp(store=store, ctx=ctx, checks=all_checks()).run()
        return 0
    finally:
        store.close()
