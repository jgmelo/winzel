"""Painel de testes: como os resultados do pytest viram o docs/testes/index.html.

Estes testes exercitam as funções puras do gerador (tools/test_dashboard),
com resultados de exemplo montados à mão.
"""

import json
from datetime import datetime

import pytest
from tools.test_dashboard.model import FAILED, PASSED, SKIPPED, RunMeta, TestRecord
from tools.test_dashboard.render import render_html
from tools.test_dashboard.report import (
    capabilities,
    group_records,
    history_entry,
    load_history,
    readable_name,
    summarize_message,
    write_history_entry,
)

pytestmark = [pytest.mark.fase0, pytest.mark.relatorio]

MOMENTO = datetime(2026, 10, 31, 14, 30, 5)


def um_teste(**campos) -> TestRecord:
    """Um resultado de teste com valores padrão, alterados só no que importa."""
    padrao = dict(
        nodeid="tests/test_x.py::test_algo",
        name="algo",
        docstring="Dado algo, quando algo, então algo.",
        phase="fase0",
        area="relatorio",
        outcome=PASSED,
        duration_s=0.01,
        message="",
        source="def test_algo():\n    assert True\n",
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


# --- agrupamento e capacidades ------------------------------------------------


def test_testes_sao_agrupados_por_fase_e_depois_por_area_na_ordem_da_spec():
    """Dados testes de fases e áreas misturadas, quando agrupo, então seguem a ordem da SPEC."""
    testes = [
        um_teste(phase="fase1", area="diff"),
        um_teste(phase="fase0", area="relatorio"),
        um_teste(phase="fase1", area="inventario"),
        um_teste(phase="fase0", area="execucao"),
    ]

    grupos = group_records(testes)

    assert [g.phase for g in grupos] == ["fase0", "fase1"]
    assert [a.area for a in grupos[0].areas] == ["execucao", "relatorio"]
    assert [a.area for a in grupos[1].areas] == ["inventario", "diff"]


def test_cada_grupo_tem_seu_sumario_de_aprovados_falhos_e_pulados():
    """Dada uma área com 2 aprovados, 1 falho e 1 pulado, então o sumário conta cada um."""
    testes = [
        um_teste(outcome=PASSED),
        um_teste(outcome=PASSED),
        um_teste(outcome=FAILED),
        um_teste(outcome=SKIPPED),
    ]

    totais = group_records(testes)[0].areas[0].totals

    assert (totais.passed, totais.failed, totais.skipped, totais.total) == (2, 1, 1, 4)


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


# --- HTML ---------------------------------------------------------------------


def test_teste_falho_aparece_com_x_vermelho_e_mensagem_resumida():
    """Dado um teste falho, quando gero o painel, então ele aparece com ❌ e a mensagem resumida."""
    falho = um_teste(name="soma confere", outcome=FAILED, message="assert 3 == 4")

    html = render_html([falho], uma_execucao(), history=[])

    assert '<article class="test failed"' in html
    assert "❌" in html
    assert '<div class="message">assert 3 == 4</div>' in html


def test_teste_aprovado_aparece_com_check_e_pulado_com_seta():
    """Dados um teste aprovado e um pulado, quando gero o painel, então aparecem ✅ e ⏭️."""
    testes = [um_teste(name="aprovado"), um_teste(name="pulado", outcome=SKIPPED)]

    html = render_html(testes, uma_execucao(), history=[])

    assert '<span class="status" title="aprovado">✅</span>' in html
    assert '<span class="status" title="pulado">⏭️</span>' in html


def test_cabecalho_mostra_commit_anterior_branch_data_totais_e_duracao():
    """Dada uma execução após o commit 3f876ab na main, então o cabeçalho traz esses dados."""
    testes = [um_teste(), um_teste(outcome=FAILED), um_teste(outcome=SKIPPED)]

    html = render_html(testes, uma_execucao(), history=[])

    assert "<code>3f876ab</code> Initial commit" in html
    assert "<dt>Branch</dt><dd>main</dd>" in html
    assert "31/10/2026 14:30:05" in html
    assert "✅ 1 aprovados" in html and "❌ 1 falhos" in html and "⏭️ 1 pulados" in html
    assert "<dt>Duração</dt><dd>1.50 s</dd>" in html


def test_cabecalho_do_primeiro_commit_indica_que_nao_ha_commit_anterior():
    """Dado um repositório sem commits, quando gero o painel, então o cabeçalho diz isso."""
    html = render_html([um_teste()], uma_execucao(parent_hash=None), history=[])

    assert "nenhum (primeiro commit)" in html


def test_painel_mostra_rotulos_de_fase_e_area_em_portugues():
    """Dado um teste da fase 0 na área relatorio, então o painel usa os rótulos em português."""
    html = render_html([um_teste()], uma_execucao(), history=[])

    assert "Fase 0 — infraestrutura" in html
    assert "Painel de testes" in html


def test_teste_sem_markers_aparece_em_sem_fase_e_sem_area():
    """Dado um teste sem markers de fase e área, então ele aparece em `Sem fase` / `Sem área`."""
    html = render_html([um_teste(phase="sem-fase", area="sem-area")], uma_execucao(), [])

    assert "Sem fase" in html and "Sem área" in html


def test_docstring_aparece_e_e_escapada_como_texto():
    """Dada uma docstring com `<` e `&`, quando gero o painel, então ela aparece escapada."""
    teste = um_teste(docstring="Dado a < b & c, então ok.")

    html = render_html([teste], uma_execucao(), history=[])

    assert '<p class="doc">Dado a &lt; b &amp; c, então ok.</p>' in html


def test_codigo_do_teste_fica_recolhivel_e_com_destaque_de_sintaxe():
    """Dado o código de um teste, então ele fica num <details> com destaque do pygments."""
    html = render_html([um_teste()], uma_execucao(), history=[])

    assert '<details class="code"><summary>Código do teste</summary>' in html
    assert '<div class="highlight">' in html
    assert '<span class="k">def</span>' in html


def test_painel_contem_mapa_de_capacidades_com_as_docstrings():
    """Dado um teste aprovado, então sua docstring aparece na seção Mapa de capacidades."""
    html = render_html([um_teste(docstring="Sabe gerar o painel.")], uma_execucao(), [])

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

    html = render_html([um_teste()], uma_execucao(), history=[antigo, novo])

    secao = html.split('id="evolucao"')[1]
    assert secao.count("<tr><td>") == 2
    assert secao.index("feat: diferenças") < secao.index("chore: início")
    assert "<th>fase1</th>" in secao and "<th>Diferenças</th>" in secao


def test_evolucao_sem_historico_avisa_que_ainda_nao_ha_dados():
    """Dado um histórico vazio, quando gero o painel, então a Evolução diz `Sem histórico ainda`."""
    html = render_html([um_teste()], uma_execucao(), history=[])

    assert "Sem histórico ainda." in html
