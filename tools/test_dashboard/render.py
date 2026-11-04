"""Render the test dashboard as a single self-contained HTML file.

Layout: a sticky side bar (sections, files, search and filters) and a main column with
the overview (tiles, file × area heat map, phases), the capability map, one table per
test file (functions, with parametrized cases grouped) and the evolution per commit.
"""

from __future__ import annotations

from html import escape

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

from .model import (
    ICONS,
    OUTCOME_LABELS,
    FileGroup,
    FunctionGroup,
    RunMeta,
    TestRecord,
    Totals,
)
from .report import (
    area_columns,
    capabilities,
    file_area_matrix,
    group_by_file,
    phase_summary,
)
from .taxonomy import AREAS, PHASES, area_label, phase_label

_FORMATTER = HtmlFormatter(cssclass="highlight", nowrap=False)

CSS = """
:root {
  --bg: #fbfbfa; --surface: #ffffff; --surface-2: #f3f3f1; --text: #1d1d1b;
  --muted: #6b6b66; --border: #e3e3df; --accent: #2f5fb3; --accent-soft: #e6edf8;
  --ok: #24804a; --bad: #c0362c; --skip: #8a8a84; --heat: 47, 95, 179;
  --code-bg: #f6f6f4; --code-text: #1d1d1b;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161615; --surface: #1e1e1c; --surface-2: #262624; --text: #e9e9e5;
    --muted: #9a9a94; --border: #34342f; --accent: #8fb0ef; --accent-soft: #24304a;
    --ok: #5cc68a; --bad: #f07a6f; --skip: #8a8a84; --heat: 143, 176, 239;
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
code, .mono { font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 12.5px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.layout { display: grid; grid-template-columns: 240px minmax(0, 1fr); min-height: 100vh; }
nav { position: sticky; top: 0; align-self: start; height: 100vh; overflow-y: auto;
  padding: 20px 16px; border-right: 1px solid var(--border); background: var(--surface); }
nav h1 { font-size: 15px; margin: 0 0 2px; }
nav .meta { color: var(--muted); font-size: 12px; margin-bottom: 16px; }
nav ul { list-style: none; margin: 0 0 16px; padding: 0; }
nav li a { display: flex; justify-content: space-between; gap: 8px; padding: 3px 6px;
  border-radius: 4px; color: var(--text); }
nav li a:hover { background: var(--surface-2); text-decoration: none; }
nav li.sub a { padding-left: 18px; color: var(--muted); }
nav li.sub a.has-failures { color: var(--bad); }
nav .count { color: var(--muted); font-size: 12px; }
nav label { display: block; font-size: 12px; color: var(--muted); margin: 10px 0 4px; }
#q { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg); color: var(--text); font: inherit; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px;
  border: 1px solid var(--border); background: var(--surface-2); color: var(--text);
  white-space: nowrap; }
button.chip { cursor: pointer; font: inherit; font-size: 12px; }
button.chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent);
  color: var(--surface); }
main { padding: 24px 32px 64px; max-width: 1240px; }
h2 { font-size: 20px; margin: 36px 0 4px; padding-top: 8px; }
section:first-child h2 { margin-top: 0; }
h3 { font-size: 15px; margin: 22px 0 4px; }
.lead { color: var(--muted); margin: 0 0 14px; }
.run { display: grid; grid-template-columns: max-content 1fr; gap: 2px 16px; margin: 0 0 12px; }
.run dt { color: var(--muted); }
.run dd { margin: 0; overflow-wrap: anywhere; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px;
  margin: 12px 0 20px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 14px; }
.tile .v { font-size: 22px; font-weight: 600; }
.tile .l { color: var(--muted); font-size: 12px; }
.tile.bad .v { color: var(--bad); }
.tile.ok .v { color: var(--ok); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; background: var(--surface);
  border: 1px solid var(--border); border-radius: 8px; }
th, td { padding: 6px 10px; border-bottom: 1px solid var(--border); text-align: left;
  vertical-align: top; }
th { font-size: 12px; color: var(--muted); font-weight: 600; background: var(--surface-2); }
table.matrix { font-size: 12.5px; }
table.matrix td, table.matrix th { text-align: center; white-space: nowrap; padding: 4px 6px; }
table.matrix th { white-space: normal; min-width: 58px; font-size: 11px; vertical-align: bottom; }
table.matrix td:first-child, table.matrix th:first-child { text-align: left; }
table.matrix td.empty { color: var(--border); }
.fn { display: block; color: var(--muted); font-size: 11px; }
td.num, th.num { text-align: right; white-space: nowrap; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }
.dot.passed { background: var(--ok); } .dot.failed { background: var(--bad); }
.dot.skipped { background: var(--skip); }
.where { display: block; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
table.tests-table th:nth-child(1) { width: 30%; }
table.tests-table th:nth-child(2) { width: 48%; }
.doc { margin: 0; }
.message { margin: 6px 0 0; padding: 4px 8px; border-left: 3px solid var(--bad);
  background: var(--surface-2); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12.5px; }
.message.skipped { border-left-color: var(--skip); }
tr.failed td:first-child { box-shadow: inset 3px 0 0 var(--bad); }
details.code summary, details.cases summary { cursor: pointer; color: var(--accent);
  font-size: 12px; }
details.cases ul { list-style: none; margin: 4px 0 0; padding: 0; }
.highlight { background: var(--code-bg); color: var(--code-text); border-radius: 6px;
  overflow-x: auto; padding: 8px 12px; margin-top: 6px; font-size: 12.5px; }
.highlight pre { margin: 0; }
.capabilities ul { margin: 4px 0 12px; padding-left: 20px; }
.empty-note { color: var(--muted); font-style: italic; }
.hidden { display: none !important; }
@media (max-width: 800px) {
  .layout { grid-template-columns: 1fr; }
  nav { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }
  main { padding: 16px; }
}
"""

SCRIPT = """
const q = document.getElementById('q');
const groups = ['area', 'phase', 'status'];
function pressed(kind) {
  return [...document.querySelectorAll(`button[data-${kind}]`)]
    .filter(b => b.getAttribute('aria-pressed') === 'true')
    .map(b => b.dataset[kind]);
}
function apply() {
  const text = q.value.trim().toLowerCase();
  const wanted = Object.fromEntries(groups.map(g => [g, pressed(g)]));
  document.querySelectorAll('tr[data-row]').forEach(tr => {
    const ok = (!text || tr.dataset.text.includes(text)) &&
      groups.every(g => !wanted[g].length || wanted[g].includes(tr.dataset[g]));
    tr.classList.toggle('hidden', !ok);
  });
  document.querySelectorAll('section.topic').forEach(sec => {
    sec.classList.toggle('hidden', !sec.querySelector('tr[data-row]:not(.hidden)'));
  });
}
q.addEventListener('input', apply);
document.querySelectorAll('nav button.chip').forEach(b => b.addEventListener('click', () => {
  b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
  apply();
}));
"""


def _fmt_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.2f} s"


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _dot(outcome: str) -> str:
    return f'<span class="dot {outcome}" title="{OUTCOME_LABELS[outcome]}"></span>'


def short_phase(phase: str) -> str:
    """'fase3' -> 'F3'; anything else -> '—'."""
    return f"F{phase.removeprefix('fase')}" if phase in PHASES else "—"


# --- side bar ---------------------------------------------------------------------


def render_nav(meta: RunMeta, files: list[FileGroup], records: list[TestRecord]) -> str:
    when = meta.generated_at.strftime("%d/%m/%Y %H:%M")
    commit = escape((meta.parent_hash or "")[:7]) or "primeiro commit"
    file_links = "".join(
        f'<li class="sub"><a href="#{g.anchor}"'
        f"{' class="has-failures"' if g.totals.failed else ''}>"
        f'<span>{escape(g.topic)}</span><span class="count">{g.totals.total}</span></a></li>'
        for g in files
    )
    areas = [a for a in AREAS if any(r.area == a for r in records)]
    phases = [p for p in PHASES if any(r.phase == p for r in records)]
    area_chips = "".join(
        f'<button class="chip" data-area="{a}" aria-pressed="false">'
        f"{escape(area_label(a))}</button>"
        for a in areas
    )
    phase_chips = "".join(
        f'<button class="chip" data-phase="{p}" aria-pressed="false" '
        f'title="{escape(phase_label(p))}">{short_phase(p)}</button>'
        for p in phases
    )
    return (
        "<nav>"
        "<h1>winzel — painel de testes</h1>"
        f'<div class="meta">{commit} · {escape(when)}</div>'
        "<ul>"
        '<li><a href="#visao-geral"><span>Visão geral</span></a></li>'
        '<li><a href="#capacidades"><span>Mapa de capacidades</span></a></li>'
        f'<li><a href="#arquivos"><span>Arquivos</span><span class="count">'
        f"{len(records)}</span></a></li>"
        f"{file_links}"
        '<li><a href="#evolucao"><span>Evolução</span></a></li>'
        "</ul>"
        '<label for="q">Filtrar testes</label>'
        '<input id="q" type="search" placeholder="nome, docstring, arquivo…">'
        "<label>Situação</label>"
        '<div class="chips"><button class="chip" data-status="failed" aria-pressed="false">'
        "Só falhos</button></div>"
        f'<label>Área</label><div class="chips">{area_chips}</div>'
        f'<label>Fase</label><div class="chips">{phase_chips}</div>'
        "</nav>"
    )


# --- overview ---------------------------------------------------------------------


def render_run(meta: RunMeta) -> str:
    if meta.parent_hash:
        parent = f"<code>{escape(meta.parent_hash[:7])}</code> {escape(meta.parent_message or '')}"
    else:
        parent = '<span class="empty-note">nenhum (primeiro commit)</span>'
    rows = [
        ("Commit anterior", parent),
        ("Branch", escape(meta.branch or "—")),
        ("Gerado em", escape(meta.generated_at.strftime("%d/%m/%Y %H:%M:%S"))),
        ("Duração", escape(_fmt_duration(meta.duration_s))),
    ]
    items = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows)
    return f'<dl class="run">{items}</dl>'


def render_tiles(records: list[TestRecord], files: list[FileGroup]) -> str:
    totals = Totals.of(records)
    functions = sum(len(g.functions) for g in files)
    tiles = [
        ("", functions, "funções de teste"),
        ("", totals.total, "casos de teste"),
        ("", len(files), "arquivos"),
        ("ok", totals.passed, f"{ICONS['passed']} aprovados"),
        ("bad" if totals.failed else "", totals.failed, f"{ICONS['failed']} falhos"),
        ("", totals.skipped, f"{ICONS['skipped']} pulados"),
    ]
    body = "".join(
        f'<div class="tile {cls}"><div class="v">{value}</div><div class="l">{label}</div></div>'
        for cls, value, label in tiles
    )
    return f'<div class="tiles">{body}</div>'


def render_matrix(files: list[FileGroup]) -> str:
    matrix = file_area_matrix(files)
    columns = area_columns()
    top = max((c.cases for row in matrix.values() for c in row.values()), default=1)
    head = (
        "<tr><th>Arquivo</th>"
        + "".join(f"<th>{escape(area_label(a))}</th>" for a in columns)
        + "<th>Total</th></tr>"
    )
    rows = []
    for group in files:
        row = matrix.get(group.file, {})
        cells = []
        for area in columns:
            cell = row.get(area)
            if cell is None:
                cells.append('<td class="empty">·</td>')
                continue
            alpha = 0.10 + 0.30 * cell.cases / top
            cells.append(
                f'<td style="background: rgba(var(--heat), {alpha:.2f})">{cell.cases}'
                f'<span class="fn">{cell.functions} fn</span></td>'
            )
        functions = len(group.functions)
        rows.append(
            f'<tr><td><a href="#{group.anchor}">{escape(group.topic)}</a></td>{"".join(cells)}'
            f'<td><b>{group.totals.total}</b><span class="fn">{functions} fn</span></td></tr>'
        )
    return (
        "<h3>Casos por arquivo e área</h3>"
        '<p class="lead">Célula: casos (funções). Colunas vazias mostram áreas que nenhum '
        "teste exercita ainda.</p>"
        f'<div class="scroll"><table class="matrix"><thead>{head}</thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_phases(records: list[TestRecord]) -> str:
    rows = "".join(
        f'<tr><td>{escape(phase_label(phase))}</td><td class="num">{t.total}</td>'
        f'<td class="num">{t.passed}</td><td class="num">{t.failed}</td>'
        f'<td class="num">{t.skipped}</td></tr>'
        for phase, t in phase_summary(records).items()
    )
    return (
        "<h3>Por fase</h3>"
        '<div class="scroll"><table><thead><tr><th>Fase</th><th class="num">Casos</th>'
        f'<th class="num">{ICONS["passed"]}</th><th class="num">{ICONS["failed"]}</th>'
        f'<th class="num">{ICONS["skipped"]}</th></tr></thead><tbody>{rows}</tbody>'
        "</table></div>"
    )


def render_overview(records: list[TestRecord], meta: RunMeta, files: list[FileGroup]) -> str:
    return (
        '<section id="visao-geral"><h2>Visão geral</h2>'
        '<p class="lead">Gerado a partir da execução do pytest. Uma <em>função</em> é um '
        "<code>def test_…</code>; funções parametrizadas se desdobram em vários "
        "<em>casos</em>.</p>"
        f"{render_run(meta)}{render_tiles(records, files)}{render_matrix(files)}"
        f"{render_phases(records)}</section>"
    )


# --- capability map ---------------------------------------------------------------


def render_capabilities(records: list[TestRecord]) -> str:
    caps = capabilities(records)
    if not caps:
        body = '<p class="empty-note">Nenhum teste aprovado ainda.</p>'
    else:
        body = "".join(
            f"<h3>{escape(area_label(area))}</h3><ul>"
            + "".join(f"<li>{escape(s)}</li>" for s in sentences)
            + "</ul>"
            for area, sentences in caps.items()
        )
    return (
        '<section class="capabilities" id="capacidades"><h2>Mapa de capacidades</h2>'
        '<p class="lead">O que o winzel sabe fazer hoje, segundo os testes aprovados.</p>'
        f"{body}</section>"
    )


# --- one table per test file --------------------------------------------------------


def _message(case: TestRecord) -> str:
    if not case.message or case.outcome == "passed":
        return ""
    prefix = f"{ICONS[case.outcome]} "
    label = f"[{case.params}] " if case.params else ""
    return f'<div class="message {case.outcome}">{prefix}{escape(label + case.message)}</div>'


def _cases_cell(function: FunctionGroup) -> str:
    if not function.parametrized:
        return "1"
    items = "".join(
        f'<li class="mono">{_dot(c.outcome)}{escape(c.params or "—")}</li>' for c in function.cases
    )
    return (
        f'<details class="cases"><summary>{_plural(len(function.cases), "caso", "casos")}'
        f"</summary><ul>{items}</ul></details>"
    )


def _search_text(function: FunctionGroup, group: FileGroup) -> str:
    parts = [
        function.function,
        function.name,
        function.docstring,
        group.file,
        area_label(function.area),
        phase_label(function.phase),
        *(c.params for c in function.cases),
    ]
    return " ".join(p for p in parts if p).lower()


def render_function(function: FunctionGroup, group: FileGroup) -> str:
    outcome = function.outcome
    doc = f'<p class="doc">{escape(function.docstring)}</p>' if function.docstring else ""
    messages = "".join(_message(c) for c in function.cases)
    code = ""
    if function.source:
        lexed = highlight(function.source, PythonLexer(), _FORMATTER)
        code = f'<details class="code"><summary>Código do teste</summary>{lexed}</details>'
    row_id = f"t-{group.topic}-{function.function}"
    return (
        f'<tr data-row id="{escape(row_id)}" class="{outcome}" data-area="{escape(function.area)}"'
        f' data-phase="{escape(function.phase)}" data-status="{outcome}"'
        f' data-text="{escape(_search_text(function, group))}">'
        f"<td>{_dot(outcome)}<strong>{escape(function.name)}</strong>"
        f'<span class="where"><code>{escape(function.function)}</code> · '
        f"{escape(group.file)}:{function.line}</span></td>"
        f"<td>{doc}{messages}{code}</td>"
        f'<td><span class="chip" title="{escape(phase_label(function.phase))}">'
        f"{short_phase(function.phase)}</span></td>"
        f'<td><span class="chip">{escape(area_label(function.area))}</span></td>'
        f"<td>{_cases_cell(function)}</td>"
        f'<td class="num">{escape(_fmt_duration(function.duration_s))}</td>'
        "</tr>"
    )


def render_file(group: FileGroup) -> str:
    totals = group.totals
    summary = (
        f"<code>{escape(group.file)}</code> · "
        f"{_plural(len(group.functions), 'função', 'funções')} · "
        f"{_plural(totals.total, 'caso', 'casos')}"
    )
    if totals.failed:
        summary += (
            f" · {ICONS['failed']} {totals.failed} {'falho' if totals.failed == 1 else 'falhos'}"
        )
    if group.lead:
        summary += f" — {escape(group.lead)}"
    rows = "".join(render_function(f, group) for f in group.functions)
    return (
        f'<section class="topic" id="{escape(group.anchor)}"><h2>{escape(group.topic)}</h2>'
        f'<p class="lead">{summary}</p>'
        '<div class="scroll"><table class="tests-table"><thead><tr><th>Teste</th>'
        "<th>O que verifica</th><th>Fase</th><th>Área</th><th>Casos</th>"
        f'<th class="num">Duração</th></tr></thead><tbody>{rows}</tbody></table></div>'
        "</section>"
    )


# --- evolution ----------------------------------------------------------------------


def render_evolution(history: list[dict]) -> str:
    if not history:
        body = '<p class="empty-note">Sem histórico ainda.</p>'
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
                f"<td><code>{escape(parent)}</code> "
                f"{escape(entry.get('parent_message') or '')}</td>"
                f"<td>{entry['totals']['total']}</td>"
                + "".join(f"<td>{entry['by_phase'].get(p, 0)}</td>" for p in phases)
                + "".join(f"<td>{entry['by_area'].get(a, 0)}</td>" for a in areas)
                + "</tr>"
            )
        body = f'<div class="scroll"><table>{head}{"".join(rows)}</table></div>'
    return (
        '<section id="evolucao"><h2>Evolução</h2>'
        '<p class="lead">Contagem de casos por fase e por área ao longo dos commits '
        "(mais recente no topo).</p>"
        f"{body}</section>"
    )


# --- page -------------------------------------------------------------------------


def render_html(records: list[TestRecord], meta: RunMeta, history: list[dict]) -> str:
    files = group_by_file(records)
    topics = "".join(render_file(g) for g in files)
    pygments_css = _FORMATTER.get_style_defs(".highlight")
    failed = Totals.of(records).failed
    title = "winzel — painel de testes" + (f" ({failed} falhos)" if failed else "")
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f"<style>{CSS}{pygments_css}</style></head><body>"
        f'<div class="layout">{render_nav(meta, files, records)}<main>'
        f"{render_overview(records, meta, files)}"
        f"{render_capabilities(records)}"
        '<section id="arquivos"><h2>Arquivos</h2><p class="lead">Uma seção por arquivo de '
        "teste.</p></section>"
        f"{topics}"
        f"{render_evolution(history)}"
        f"</main></div><script>{SCRIPT}</script></body></html>\n"
    )
