"""Render the test dashboard as a single self-contained HTML file."""

from __future__ import annotations

from html import escape

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

from .model import ICONS, OUTCOME_LABELS, AreaGroup, PhaseGroup, RunMeta, TestRecord, Totals
from .report import capabilities, group_records
from .taxonomy import AREAS, PHASES, area_label, phase_label

_FORMATTER = HtmlFormatter(cssclass="highlight", nowrap=False)

CSS = """
:root {
  --bg: #fafaf9; --fg: #1c1917; --muted: #57534e; --card: #ffffff; --line: #e7e5e4;
  --ok: #15803d; --bad: #b91c1c; --skip: #a16207; --accent: #1d4ed8; --code: #f5f5f4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1c1917; --fg: #f5f5f4; --muted: #a8a29e; --card: #292524; --line: #44403c;
    --ok: #4ade80; --bad: #f87171; --skip: #facc15; --accent: #93c5fd; --code: #f5f5f4;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.5 "Segoe UI", system-ui, sans-serif; }
main { max-width: 1000px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { margin: 0 0 4px; font-size: 1.6rem; }
h2 { margin: 40px 0 12px; font-size: 1.3rem; border-bottom: 1px solid var(--line);
  padding-bottom: 6px; }
h3 { margin: 24px 0 8px; font-size: 1.05rem; }
h4 { margin: 16px 0 6px; font-size: .95rem; color: var(--muted); }
nav a { color: var(--accent); margin-right: 16px; }
.meta { display: grid; grid-template-columns: max-content 1fr; gap: 2px 16px; margin: 16px 0;
  background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px; }
.meta dt { color: var(--muted); }
.meta dd { margin: 0; overflow-wrap: anywhere; }
code { font-family: Consolas, "Cascadia Mono", monospace; }
.totals .passed { color: var(--ok); } .totals .failed { color: var(--bad); }
.totals .skipped { color: var(--skip); }
.summary { color: var(--muted); font-weight: normal; font-size: .9rem; margin-left: 8px; }
.test { background: var(--card); border: 1px solid var(--line); border-left-width: 4px;
  border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
.test.passed { border-left-color: var(--ok); } .test.failed { border-left-color: var(--bad); }
.test.skipped { border-left-color: var(--skip); }
.test-head { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.test-name { font-weight: 600; flex: 1; }
.duration { color: var(--muted); font-size: .85rem; }
.doc { margin: 4px 0; }
.message { margin: 6px 0; padding: 6px 10px; border-radius: 4px; background: var(--code);
  color: #7f1d1d; white-space: pre-wrap; overflow-wrap: anywhere; font-size: .85rem; }
.test.skipped .message { color: #713f12; }
details.code summary { cursor: pointer; color: var(--accent); font-size: .9rem; }
.highlight { background: var(--code); color: #1c1917; border-radius: 4px; overflow-x: auto;
  padding: 8px 12px; margin-top: 6px; font-size: .85rem; }
.highlight pre { margin: 0; }
.capabilities ul { margin: 4px 0 12px; padding-left: 20px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; font-size: .85rem; background: var(--card); }
th, td { border: 1px solid var(--line); padding: 4px 8px; text-align: right; white-space: nowrap; }
th:first-child, td:first-child, td.commit { text-align: left; }
.empty { color: var(--muted); font-style: italic; }
"""


def _fmt_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.2f} s"


def _totals_html(totals: Totals) -> str:
    return (
        f'<span class="totals">'
        f'<span class="passed">{ICONS["passed"]} {totals.passed} aprovados</span> · '
        f'<span class="failed">{ICONS["failed"]} {totals.failed} falhos</span> · '
        f'<span class="skipped">{ICONS["skipped"]} {totals.skipped} pulados</span>'
        f"</span>"
    )


def _summary(totals: Totals) -> str:
    parts = [f"{totals.total} testes", f"{ICONS['passed']} {totals.passed}"]
    if totals.failed:
        parts.append(f"{ICONS['failed']} {totals.failed}")
    if totals.skipped:
        parts.append(f"{ICONS['skipped']} {totals.skipped}")
    return f'<span class="summary">{" · ".join(parts)}</span>'


def render_header(meta: RunMeta, totals: Totals) -> str:
    if meta.parent_hash:
        parent = f"<code>{escape(meta.parent_hash[:7])}</code> {escape(meta.parent_message or '')}"
    else:
        parent = '<span class="empty">nenhum (primeiro commit)</span>'
    rows = [
        ("Commit anterior", parent),
        ("Branch", escape(meta.branch or "—")),
        ("Gerado em", escape(meta.generated_at.strftime("%d/%m/%Y %H:%M:%S"))),
        ("Totais", f"{_totals_html(totals)} (total {totals.total})"),
        ("Duração", escape(_fmt_duration(meta.duration_s))),
    ]
    items = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows)
    return (
        "<header><h1>winzel — painel de testes</h1>"
        '<nav><a href="#capacidades">Mapa de capacidades</a>'
        '<a href="#testes">Testes</a><a href="#evolucao">Evolução</a></nav>'
        f'<dl class="meta">{items}</dl></header>'
    )


def render_test(record: TestRecord) -> str:
    icon = ICONS[record.outcome]
    label = OUTCOME_LABELS[record.outcome]
    parts = [
        f'<article class="test {record.outcome}" id="{escape(record.nodeid)}">',
        '<div class="test-head">',
        f'<span class="status" title="{label}">{icon}</span>',
        f'<span class="test-name">{escape(record.name)}</span>',
        f'<span class="duration">{escape(_fmt_duration(record.duration_s))}</span>',
        "</div>",
    ]
    if record.docstring:
        parts.append(f'<p class="doc">{escape(record.docstring)}</p>')
    if record.message:
        parts.append(f'<div class="message">{escape(record.message)}</div>')
    if record.source:
        code = highlight(record.source, PythonLexer(), _FORMATTER)
        parts.append(f'<details class="code"><summary>Código do teste</summary>{code}</details>')
    parts.append("</article>")
    return "".join(parts)


def render_area(group: AreaGroup) -> str:
    tests = "".join(render_test(r) for r in group.records)
    return f"<h4>{escape(area_label(group.area))}{_summary(group.totals)}</h4>{tests}"


def render_phase(group: PhaseGroup) -> str:
    areas = "".join(render_area(a) for a in group.areas)
    return (
        f'<section class="phase" id="{escape(group.phase)}">'
        f"<h3>{escape(phase_label(group.phase))}{_summary(group.totals)}</h3>{areas}</section>"
    )


def render_capabilities(records: list[TestRecord]) -> str:
    caps = capabilities(records)
    if not caps:
        body = '<p class="empty">Nenhum teste aprovado ainda.</p>'
    else:
        body = "".join(
            f"<h4>{escape(area_label(area))}</h4><ul>"
            + "".join(f"<li>{escape(s)}</li>" for s in sentences)
            + "</ul>"
            for area, sentences in caps.items()
        )
    return (
        '<section class="capabilities" id="capacidades"><h2>Mapa de capacidades</h2>'
        "<p>O que o winzel sabe fazer hoje, segundo os testes aprovados.</p>"
        f"{body}</section>"
    )


def render_evolution(history: list[dict]) -> str:
    if not history:
        body = '<p class="empty">Sem histórico ainda.</p>'
    else:
        phases = [p for p in PHASES if any(e["by_phase"].get(p) for e in history)]
        areas = [a for a in AREAS if any(e["by_area"].get(a) for e in history)]
        head = (
            "<tr><th>Data</th><th>Commit anterior</th><th>Total</th>"
            + "".join(f"<th>{escape(p)}</th>" for p in phases)
            + "".join(f"<th>{escape(area_label(a))}</th>" for a in areas)
            + "</tr>"
        )
        rows = []
        for entry in reversed(history):
            parent = (entry.get("parent_hash") or "")[:7] or "—"
            rows.append(
                f"<tr><td>{escape(entry['generated_at'].replace('T', ' '))}</td>"
                f'<td class="commit"><code>{escape(parent)}</code> '
                f"{escape(entry.get('parent_message') or '')}</td>"
                f"<td>{entry['totals']['total']}</td>"
                + "".join(f"<td>{entry['by_phase'].get(p, 0)}</td>" for p in phases)
                + "".join(f"<td>{entry['by_area'].get(a, 0)}</td>" for a in areas)
                + "</tr>"
            )
        body = f'<div class="table-wrap"><table>{head}{"".join(rows)}</table></div>'
    return (
        '<section id="evolucao"><h2>Evolução</h2>'
        "<p>Contagem de testes por fase e por área ao longo dos commits (mais recente no topo).</p>"
        f"{body}</section>"
    )


def render_html(records: list[TestRecord], meta: RunMeta, history: list[dict]) -> str:
    totals = Totals.of(records)
    phases = "".join(render_phase(g) for g in group_records(records))
    pygments_css = _FORMATTER.get_style_defs(".highlight")
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>winzel — painel de testes</title>"
        f"<style>{CSS}{pygments_css}</style></head><body><main>"
        f"{render_header(meta, totals)}"
        f"{render_capabilities(records)}"
        f'<section id="testes"><h2>Testes por fase e área</h2>{phases}</section>'
        f"{render_evolution(history)}"
        "</main></body></html>\n"
    )
