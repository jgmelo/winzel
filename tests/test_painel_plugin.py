"""Plugin do pytest: uma execução real do pytest gera o painel e o histórico.

Cada teste roda uma suíte de exemplo (com o `pytester`) e examina os arquivos gerados.
"""

import json

import pytest

pytestmark = [pytest.mark.fase0, pytest.mark.relatorio]

SUITE_DE_EXEMPLO = '''
"""Suíte de exemplo do painel."""

import pytest

pytestmark = [pytest.mark.fase1, pytest.mark.inventario]


def test_programa_novo_aparece():
    """Dado um programa novo, então ele aparece."""
    assert True


def test_soma_errada():
    """Dado 1 + 1, então dá 3."""
    assert 1 + 1 == 3


@pytest.mark.skip(reason="requer admin")
def test_ssd():
    """Dado o SSD, então lê o desgaste."""


@pytest.mark.fase0
@pytest.mark.relatorio
def test_marker_da_funcao_prevalece_sobre_o_do_modulo():
    """Dado marker na função, então ele vale."""
'''


@pytest.fixture
def sem_git(monkeypatch):
    """Isola a suíte de exemplo de variáveis do Git herdadas (ex.: dentro do pre-commit)."""
    import os

    for nome in list(os.environ):
        if nome.startswith("GIT_"):
            monkeypatch.delenv(nome)


def rodar_suite(pytester, *opcoes):
    pytester.makepyfile(test_exemplo=SUITE_DE_EXEMPLO)
    painel = pytester.path / "saida" / "index.html"
    resultado = pytester.runpytest(
        "-p", "tools.test_dashboard.plugin", f"--painel={painel}", *opcoes
    )
    return resultado, painel


def test_rodar_o_pytest_gera_o_painel_com_cada_teste_e_seu_status(pytester, sem_git):
    """Dada uma suíte com aprovado, falho e pulado, quando rodo o pytest, então o painel os traz."""
    resultado, painel = rodar_suite(pytester)

    resultado.assert_outcomes(passed=2, failed=1, skipped=1)
    html = painel.read_text(encoding="utf-8")
    assert "<strong>programa novo aparece</strong>" in html
    assert '<tr data-row id="t-exemplo-test_soma_errada" class="failed"' in html
    assert '<div class="message failed">❌ assert (1 + 1) == 3</div>' in html
    assert '<div class="message skipped">⏭️ requer admin</div>' in html
    assert "Dado um programa novo, então ele aparece." in html
    assert "<code>test_exemplo.py</code> · 4 funções · 4 casos" in html
    assert "— Suíte de exemplo do painel." in html
    resultado.stdout.fnmatch_lines([f"painel de testes: {painel}"])


def test_fase_e_area_vem_dos_markers_e_o_da_funcao_prevalece(pytester, sem_git):
    """Dado marker de fase/área no módulo e outro na função, então o da função define o grupo."""
    _, painel = rodar_suite(pytester)

    html = painel.read_text(encoding="utf-8")
    marcada = html.split('id="t-exemplo-test_marker_da_funcao_prevalece_sobre_o_do_modulo"')[1]
    modulo = html.split('id="t-exemplo-test_programa_novo_aparece"')[1]
    assert marcada.startswith(' class="passed" data-area="relatorio" data-phase="fase0"')
    assert modulo.startswith(' class="passed" data-area="inventario" data-phase="fase1"')


def test_historico_so_e_gravado_quando_todos_os_testes_passam(pytester, sem_git):
    """Dada uma suíte com falha, quando rodo com --painel-historico, então nenhum JSON é gravado."""
    _, painel = rodar_suite(pytester, "--painel-historico")

    historico = painel.parent / "historico"
    assert not historico.exists() or not list(historico.glob("*.json"))


def test_com_todos_aprovados_o_historico_ganha_um_json_e_entra_na_evolucao(pytester, sem_git):
    """Dada uma suíte toda aprovada, quando rodo com --painel-historico, então grava um JSON."""
    resultado, painel = rodar_suite(pytester, "--painel-historico", "-k", "programa_novo")

    resultado.assert_outcomes(passed=1, deselected=3)
    jsons = list((painel.parent / "historico").glob("*.json"))
    assert len(jsons) == 1
    entrada = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert entrada["totals"]["total"] == 1
    assert entrada["by_phase"] == {"fase1": 1}
    html = painel.read_text(encoding="utf-8")
    assert html.split('id="evolucao"')[1].count("<tr><td>") == 1


def test_opcao_sem_painel_nao_gera_arquivo(pytester, sem_git):
    """Dada a opção --sem-painel, quando rodo o pytest, então nenhum painel é gerado."""
    _, painel = rodar_suite(pytester, "--sem-painel")

    assert not painel.exists()


def test_markers_desconhecidos_sao_rejeitados_e_os_da_spec_sao_aceitos(pytester, sem_git):
    """Dado um marker fora da SPEC, quando rodo com --strict-markers, então a coleta falha."""
    pytester.makepyfile(
        test_markers="""
        import pytest

        @pytest.mark.fase0
        @pytest.mark.sistema
        @pytest.mark.banco
        def test_ok():
            pass

        @pytest.mark.fase9
        def test_invalido():
            pass
        """
    )

    resultado = pytester.runpytest(
        "-p", "tools.test_dashboard.plugin", "--sem-painel", "--strict-markers"
    )

    resultado.stdout.fnmatch_lines(["*'fase9' not found in `markers`*"])


def test_casos_parametrizados_sao_agrupados_com_linha_e_parametros(pytester, sem_git):
    """Dada uma função parametrizada em 3 casos, então o painel mostra uma linha com os 3."""
    pytester.makepyfile(
        test_param="""
        import pytest

        pytestmark = [pytest.mark.fase0, pytest.mark.relatorio]


        @pytest.mark.parametrize("valor", [1, 2, 3])
        def test_dobro(valor):
            \"\"\"Dado um valor, então o dobro é par.\"\"\"
            assert (valor * 2) % 2 == 0
        """
    )
    painel = pytester.path / "saida" / "index.html"

    pytester.runpytest("-p", "tools.test_dashboard.plugin", f"--painel={painel}")

    html = painel.read_text(encoding="utf-8")
    trecho = html.split('id="t-param-test_dobro"')[1].split("</tr>")[0]
    assert html.count('<tr data-row id="t-param-test_dobro"') == 1
    assert "<summary>3 casos</summary>" in trecho
    assert "<code>test_dobro</code> · test_param.py:6" in trecho  # linha do decorador
