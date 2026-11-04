"""Painel de testes: como os resultados do pytest viram o docs/testes/index.html.

Estes testes exercitam as funções puras do gerador (tools/test_dashboard),
com resultados de exemplo montados à mão. Um *caso* é um teste coletado; uma *função*
é um `def test_…` (parametrizada, gera vários casos); funções são agrupadas por arquivo.
"""

import json
from datetime import datetime

import pytest
from tools.test_dashboard.model import FAILED, PASSED, SKIPPED, RunMeta, TestRecord
from tools.test_dashboard.render import render_html
from tools.test_dashboard.report import (
    area_columns,
    capabilities,
    file_area_matrix,
    group_by_file,
    history_entry,
    load_history,
    phase_summary,
    readable_name,
    summarize_message,
    write_history_entry,
)
from tools.test_dashboard.taxonomy import AREAS

pytestmark = [pytest.mark.fase0, pytest.mark.relatorio]

MOMENTO = datetime(2026, 10, 31, 14, 30, 5)


def um_teste(nodeid="tests/test_x.py::test_algo", **campos) -> TestRecord:
    """Um caso de teste com valores padrão, alterados só no que importa."""
    padrao = dict(
        nodeid=nodeid,
        name=readable_name(nodeid.split("::")[-1]),
        docstring="Dado algo, quando algo, então algo.",
        phase="fase0",
        area="relatorio",
        outcome=PASSED,
        duration_s=0.01,
        message="",
        source="def test_algo():\n    assert True\n",
        line=10,
    )
    return TestRecord(**(padrao | campos))


def uma_execucao(**campos) -> RunMeta:
    padrao = dict(
        generated_at=MOMENTO,
        duration_s=1.5,
        parent_hash="3f876ab0123456789abcdef0123456789abcdef0",
        parent_message="Initial commit",
        branch="main",
    )
    return RunMeta(**(padrao | campos))


def painel(testes, history=(), **execucao):
    return render_html(list(testes), uma_execucao(**execucao), history=list(history))


def linha(html, nodeid_funcao):
    """O HTML da linha (<tr>) de uma função, pelo id `t-<arquivo>-<função>`."""
    inicio = html.index(f'<tr data-row id="{nodeid_funcao}"')
    return html[inicio : html.index("</tr>", inicio)]


# --- nomes e mensagens --------------------------------------------------------


def test_nome_legivel_remove_prefixo_test_e_troca_sublinhados_por_espacos():
    """Dado `test_programa_novo_aparece`, quando gero o nome, então vira `programa novo aparece`."""
    nome = readable_name("test_programa_novo_aparece")

    assert nome == "programa novo aparece"


def test_nome_legivel_preserva_o_parametro_de_testes_parametrizados():
    """Dado um teste parametrizado, quando gero o nome, então o parâmetro vai entre colchetes."""
    nome = readable_name("test_dependencia_disponivel[psutil]")

    assert nome == "dependencia disponivel [psutil]"


def test_mensagem_de_falha_e_resumida_a_primeira_linha():
    """Dada uma falha com várias linhas, quando resumo, então fica só a primeira, sem o `E`."""
    falha = "E   assert 3 == 4\nE    +  where 3 = len([1, 2, 3])\n"

    resumo = summarize_message(falha)

    assert resumo == "assert 3 == 4"


def test_mensagem_muito_longa_e_truncada_com_reticencias():
    """Dada uma mensagem de 500 caracteres, quando resumo, então ela é cortada em 200 com `…`."""
    resumo = summarize_message("x" * 500)

    assert len(resumo) == 200
    assert resumo.endswith("…")


def test_motivo_de_teste_pulado_perde_o_prefixo_skipped():
    """Dado o motivo `Skipped: requer admin`, quando resumo, então fica `requer admin`."""
    resumo = summarize_message("Skipped: requer admin")

    assert resumo == "requer admin"


# --- agrupamento ----------------------------------------------------------------


def test_arquivo_funcao_e_parametro_vem_do_nodeid():
    """Dado `tests/test_a.py::test_b[x-1]`, então arquivo, função e parâmetro são extraídos."""
    caso = um_teste("tests/test_a.py::test_b[x-1]")

    assert (caso.file, caso.function, caso.params) == ("tests/test_a.py", "test_b", "x-1")


def test_funcoes_sao_agrupadas_por_arquivo_em_ordem_alfabetica_e_na_ordem_do_codigo():
    """Dados testes de dois arquivos, então os arquivos vêm em ordem e as funções pela linha."""
    testes = [
        um_teste("tests/test_b.py::test_segunda", line=30),
        um_teste("tests/test_b.py::test_primeira", line=5),
        um_teste("tests/test_a.py::test_unica"),
    ]

    grupos = group_by_file(testes)

    assert [g.file for g in grupos] == ["tests/test_a.py", "tests/test_b.py"]
    assert [f.function for f in grupos[1].functions] == ["test_primeira", "test_segunda"]
    assert grupos[1].topic == "b"


def test_casos_de_uma_funcao_parametrizada_ficam_juntos():
    """Dados três casos de `test_dep[...]`, então há uma função com três casos."""
    testes = [um_teste(f"tests/test_a.py::test_dep[{p}]") for p in ("x", "y", "z")]

    (grupo,) = group_by_file(testes)

    (funcao,) = grupo.functions
    assert [c.params for c in funcao.cases] == ["x", "y", "z"]
    assert funcao.parametrized and funcao.name == "dep"


@pytest.mark.parametrize(
    ("resultados", "situacao"),
    [
        ([PASSED, PASSED], PASSED),
        ([PASSED, FAILED, SKIPPED], FAILED),
        ([SKIPPED, SKIPPED], SKIPPED),
        ([PASSED, SKIPPED], PASSED),
    ],
)
def test_situacao_da_funcao_resume_a_dos_seus_casos(resultados, situacao):
    """Dados os casos de uma função, então ela falha se algum falhou e é pulada se todos foram."""
    testes = [
        um_teste(f"tests/test_a.py::test_f[{i}]", outcome=r) for i, r in enumerate(resultados)
    ]

    (grupo,) = group_by_file(testes)

    assert grupo.functions[0].outcome == situacao


def test_matriz_conta_casos_e_funcoes_por_arquivo_e_area():
    """Dadas funções com 3 e 1 casos na mesma área, então a célula tem 4 casos e 2 fn."""
    testes = [um_teste(f"tests/test_a.py::test_p[{p}]", area="diff") for p in "xyz"]
    testes.append(um_teste("tests/test_a.py::test_q", area="diff"))

    matriz = file_area_matrix(group_by_file(testes))

    celula = matriz["tests/test_a.py"]["diff"]
    assert (celula.cases, celula.functions) == (4, 2)


def test_colunas_da_matriz_sao_todas_as_areas_da_spec():
    """Dada a taxonomia, então a matriz tem uma coluna por área, mesmo sem testes nela."""
    assert area_columns() == list(AREAS)


def test_resumo_por_fase_segue_a_ordem_da_spec():
    """Dados testes das fases 1 e 0, então o resumo vem na ordem 0, 1 com os totais de cada uma."""
    testes = [um_teste(phase="fase1"), um_teste(phase="fase0", outcome=FAILED)]

    resumo = phase_summary(testes)

    assert list(resumo) == ["fase0", "fase1"]
    assert (resumo["fase0"].failed, resumo["fase1"].passed) == (1, 1)


def test_mapa_de_capacidades_lista_so_docstrings_de_testes_aprovados_por_area():
    """Dados testes aprovados e falhos, quando monto o mapa, então só os aprovados aparecem."""
    testes = [
        um_teste(area="relatorio", docstring="Sabe resumir falhas."),
        um_teste(area="relatorio", docstring="Ainda não sabe isto.", outcome=FAILED),
        um_teste(area="execucao", docstring="Sabe importar o pacote."),
    ]

    mapa = capabilities(testes)

    assert mapa == {
        "execucao": ["Sabe importar o pacote."],
        "relatorio": ["Sabe resumir falhas."],
    }


# --- HTML: visão geral ------------------------------------------------------------


def test_visao_geral_mostra_commit_anterior_branch_data_e_duracao():
    """Dada uma execução após o commit 3f876ab na main, então a visão geral traz esses dados."""
    html = painel([um_teste()])

    assert "<dt>Commit anterior</dt><dd><code>3f876ab</code> Initial commit</dd>" in html
    assert "<dt>Branch</dt><dd>main</dd>" in html
    assert "<dt>Gerado em</dt><dd>31/10/2026 14:30:05</dd>" in html
    assert "<dt>Duração</dt><dd>1.50 s</dd>" in html


def test_primeiro_commit_e_indicado_quando_nao_ha_commit_anterior():
    """Dado um repositório sem commits, quando gero o painel, então a visão geral diz isso."""
    assert "nenhum (primeiro commit)" in painel([um_teste()], parent_hash=None)


def test_blocos_contam_funcoes_casos_arquivos_e_resultados():
    """Dada uma função com 2 casos (1 falho) e outra com 1 pulado, então os blocos batem."""
    testes = [
        um_teste("tests/test_a.py::test_p[x]"),
        um_teste("tests/test_a.py::test_p[y]", outcome=FAILED, message="boom"),
        um_teste("tests/test_b.py::test_q", outcome=SKIPPED),
    ]

    html = painel(testes)

    for valor, rotulo in [
        (2, "funções de teste"),
        (3, "casos de teste"),
        (2, "arquivos"),
        (1, "✅ aprovados"),
        (1, "❌ falhos"),
        (1, "⏭️ pulados"),
    ]:
        assert f'<div class="v">{valor}</div><div class="l">{rotulo}</div>' in html


def test_matriz_mostra_casos_e_funcoes_e_ponto_nas_areas_vazias():
    """Dados 4 casos em 2 funções na área Diferenças, então a célula mostra "4" e "2 fn"."""
    testes = [um_teste(f"tests/test_a.py::test_p[{p}]", area="diff") for p in "xyz"]
    testes.append(um_teste("tests/test_a.py::test_q", area="diff"))

    html = painel(testes)

    matriz = html.split('<table class="matrix">')[1].split("</table>")[0]
    assert '4<span class="fn">2 fn</span></td>' in matriz
    assert '<td class="empty">·</td>' in matriz
    assert '<a href="#arquivo-a">a</a>' in matriz
    assert "<th>Painel de testes</th>" in matriz


def test_resumo_por_fase_usa_os_rotulos_em_portugues():
    """Dado um teste da fase 0, então a tabela por fase mostra "Fase 0 — infraestrutura"."""
    assert "<td>Fase 0 — infraestrutura</td>" in painel([um_teste()])


def test_titulo_da_pagina_avisa_quando_ha_falhas():
    """Dado um teste falho, então o título da página diz quantos falharam."""
    html = painel([um_teste(outcome=FAILED, message="x")])

    assert "<title>winzel — painel de testes (1 falhos)</title>" in html


# --- HTML: tabelas por arquivo --------------------------------------------------------


def test_cada_arquivo_tem_secao_com_caminho_contagens_e_docstring_do_modulo():
    """Dado um arquivo com docstring de módulo, então a seção traz caminho, contagens e resumo."""
    html = painel([um_teste(file_doc="Checagem de programas.")])

    assert '<section class="topic" id="arquivo-x"><h2>x</h2>' in html
    assert "<code>tests/test_x.py</code> · 1 função · 1 caso — Checagem de programas." in html


def test_linha_da_funcao_traz_nome_codigo_arquivo_linha_fase_e_area():
    """Dada a função `test_algo` na linha 10, então a linha mostra tudo isso e as etiquetas."""
    trecho = linha(painel([um_teste()]), "t-x-test_algo")

    assert "<strong>algo</strong>" in trecho
    assert "<code>test_algo</code> · tests/test_x.py:10" in trecho
    assert 'title="Fase 0 — infraestrutura">F0</span>' in trecho
    assert '<span class="chip">Painel de testes</span>' in trecho


def test_funcao_falha_fica_marcada_e_mostra_a_mensagem_resumida():
    """Dado um teste falho, então a linha fica vermelha e mostra ❌ com a mensagem."""
    falho = um_teste(outcome=FAILED, message="assert 3 == 4")

    trecho = linha(painel([falho]), "t-x-test_algo")

    assert 'class="failed"' in trecho
    assert '<span class="dot failed" title="falhou"></span>' in trecho
    assert '<div class="message failed">❌ assert 3 == 4</div>' in trecho


def test_teste_pulado_mostra_o_motivo():
    """Dado um teste pulado, então a linha mostra ⏭️ e o motivo."""
    pulado = um_teste(outcome=SKIPPED, message="requer admin")

    trecho = linha(painel([pulado]), "t-x-test_algo")

    assert '<span class="dot skipped" title="pulado"></span>' in trecho
    assert '<div class="message skipped">⏭️ requer admin</div>' in trecho


def test_casos_parametrizados_ficam_num_item_recolhivel_com_a_situacao_de_cada_um():
    """Dada uma função com 2 casos (um falho), então eles aparecem recolhidos, com sua cor."""
    testes = [
        um_teste("tests/test_x.py::test_algo[psutil]"),
        um_teste("tests/test_x.py::test_algo[textual]", outcome=FAILED, message="sem módulo"),
    ]

    trecho = linha(painel(testes), "t-x-test_algo")

    assert '<details class="cases"><summary>2 casos</summary>' in trecho
    assert '<span class="dot passed" title="aprovado"></span>psutil' in trecho
    assert '<span class="dot failed" title="falhou"></span>textual' in trecho
    assert "❌ [textual] sem módulo" in trecho


def test_docstring_aparece_e_e_escapada_como_texto():
    """Dada uma docstring com `<` e `&`, quando gero o painel, então ela aparece escapada."""
    html = painel([um_teste(docstring="Dado a < b & c, então ok.")])

    assert '<p class="doc">Dado a &lt; b &amp; c, então ok.</p>' in html


def test_codigo_do_teste_fica_recolhivel_e_com_destaque_de_sintaxe():
    """Dado o código de um teste, então ele fica num <details> com destaque do pygments."""
    html = painel([um_teste()])

    assert '<details class="code"><summary>Código do teste</summary>' in html
    assert '<span class="k">def</span>' in html


def test_teste_sem_markers_aparece_em_sem_fase_e_sem_area():
    """Dado um teste sem markers de fase e área, então ele aparece como "Sem área" e fase "—"."""
    trecho = linha(painel([um_teste(phase="sem-fase", area="sem-area")]), "t-x-test_algo")

    assert 'title="Sem fase">—</span>' in trecho
    assert '<span class="chip">Sem área</span>' in trecho


# --- HTML: navegação e filtros ---------------------------------------------------------


def test_barra_lateral_lista_os_arquivos_com_contagem_e_destaca_os_com_falhas():
    """Dados dois arquivos, um com falha, então a barra lateral lista ambos e destaca o falho."""
    testes = [
        um_teste("tests/test_a.py::test_ok"),
        um_teste("tests/test_b.py::test_ruim", outcome=FAILED, message="x"),
    ]

    nav = painel(testes).split("<nav>")[1].split("</nav>")[0]

    assert '<a href="#arquivo-a"><span>a</span><span class="count">1</span></a>' in nav
    assert '<a href="#arquivo-b" class="has-failures">' in nav


def test_filtros_oferecem_so_as_areas_e_fases_que_tem_testes():
    """Dados testes das áreas Diferenças e Banco, então só elas viram botões de filtro."""
    testes = [um_teste(area="diff", phase="fase1"), um_teste(area="banco", phase="fase1")]

    nav = painel(testes).split("<nav>")[1].split("</nav>")[0]

    assert 'data-area="diff"' in nav and 'data-area="banco"' in nav
    assert 'data-area="relatorio"' not in nav
    assert 'data-phase="fase1"' in nav and 'data-phase="fase0"' not in nav
    assert '<button class="chip" data-status="failed"' in nav
    assert '<input id="q" type="search"' in nav


def test_linhas_trazem_os_dados_usados_pela_busca_e_pelos_filtros():
    """Dada uma função, então a linha tem área, fase, situação e o texto de busca em minúsculas."""
    teste = um_teste(area="diff", phase="fase1", docstring="Dado X, então Y.")

    trecho = linha(painel([teste]), "t-x-test_algo")

    assert 'data-area="diff" data-phase="fase1" data-status="passed"' in trecho
    assert "dado x, então y." in trecho.split('data-text="')[1]


def test_pagina_inclui_o_script_dos_filtros():
    """Dado o painel, então ele traz o script que aplica a busca e os filtros nas linhas."""
    html = painel([um_teste()])

    assert "document.querySelectorAll('tr[data-row]')" in html
    assert "section.topic" in html


def test_painel_contem_mapa_de_capacidades_com_as_docstrings():
    """Dado um teste aprovado, então sua docstring aparece na seção Mapa de capacidades."""
    html = painel([um_teste(docstring="Sabe gerar o painel.")])

    secao = html.split('id="capacidades"')[1].split("</section>")[0]
    assert "<li>Sabe gerar o painel.</li>" in secao


# --- histórico e evolução -----------------------------------------------------


def test_historico_resume_a_execucao_com_totais_e_contagens_por_fase_e_area():
    """Dada uma execução com 3 testes, quando resumo para o histórico, então os totais batem."""
    testes = [
        um_teste(phase="fase0", area="relatorio"),
        um_teste(phase="fase0", area="execucao"),
        um_teste(phase="fase1", area="diff", outcome=SKIPPED),
    ]

    entrada = history_entry(testes, uma_execucao())

    assert entrada["totals"] == {"passed": 2, "failed": 0, "skipped": 1, "total": 3}
    assert entrada["by_phase"] == {"fase0": 2, "fase1": 1}
    assert entrada["by_area"] == {"diff": 1, "execucao": 1, "relatorio": 1}
    assert entrada["parent_hash"].startswith("3f876ab")


def test_historico_grava_um_json_por_commit_com_data_e_hash_no_nome(tmp_path):
    """Dadas execuções sobre dois commits, então há dois JSONs, nomeados por data e hash."""
    primeira = history_entry([um_teste()], uma_execucao())
    segunda = history_entry(
        [um_teste(), um_teste()],
        uma_execucao(generated_at=datetime(2026, 11, 1, 9, 0, 0), parent_hash="abcdef1" * 5),
    )

    write_history_entry(tmp_path, primeira)
    write_history_entry(tmp_path, segunda)

    nomes = sorted(p.name for p in tmp_path.iterdir())
    assert nomes == ["20261031T143005_3f876ab.json", "20261101T090000_abcdef1.json"]
    assert json.loads((tmp_path / nomes[1]).read_text(encoding="utf-8"))["totals"]["total"] == 2


def test_historico_e_lido_do_mais_antigo_para_o_mais_recente_ignorando_arquivos_invalidos(
    tmp_path,
):
    """Dados JSONs válidos e um corrompido, quando leio o histórico, então vêm os válidos."""
    write_history_entry(tmp_path, history_entry([um_teste()], uma_execucao()))
    write_history_entry(
        tmp_path,
        history_entry([um_teste()], uma_execucao(generated_at=datetime(2025, 1, 1))),
    )
    (tmp_path / "99999999T999999_lixo.json").write_text("{não é json", encoding="utf-8")

    historico = load_history(tmp_path)

    assert [e["generated_at"] for e in historico] == ["2025-01-01T00:00:00", "2026-10-31T14:30:05"]


def test_evolucao_mostra_contagem_por_fase_e_area_ao_longo_dos_commits():
    """Dado um histórico de dois commits, então a seção Evolução tem uma linha por commit."""
    antigo = history_entry([um_teste()], uma_execucao(parent_message="chore: início"))
    novo = history_entry(
        [um_teste(), um_teste(phase="fase1", area="diff")],
        uma_execucao(parent_message="feat: diferenças"),
    )

    html = painel([um_teste()], history=[antigo, novo])

    secao = html.split('id="evolucao"')[1]
    assert secao.count("<tr><td>") == 2
    assert secao.index("feat: diferenças") < secao.index("chore: início")
    assert "<th>fase1</th>" in secao and "<th>Diferenças</th>" in secao


def test_evolucao_sem_historico_avisa_que_ainda_nao_ha_dados():
    """Dado um histórico vazio, quando gero o painel, então a Evolução diz `Sem histórico ainda`."""
    assert "Sem histórico ainda." in painel([um_teste()])
