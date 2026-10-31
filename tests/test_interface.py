"""Interface: modo `snapshot` sem interface e a aplicação Textual.

A aplicação é exercitada com o `run_test` do Textual (terminal virtual), banco em
memória e o PowerShell falso.
"""

import asyncio
import copy
import io
import threading

import pytest
from tests.fakes import FixedClock, make_context, sample
from textual.widgets import DataTable, Select, Static, TabbedContent

from winzel.checks import get_check
from winzel.cli import cmd_snapshot, format_report, main
from winzel.diff import Change, ChangeKind
from winzel.snapshot import take_snapshot
from winzel.ui.app import ALL, WinzelApp, filter_changes

pytestmark = [pytest.mark.fase1, pytest.mark.interface]

CHECKS = [get_check("programs"), get_check("startup")]


def respostas(**mudancas):
    base = {"programs": copy.deepcopy(sample("programs")), "startup": sample("startup")}
    return base | mudancas


def com_obsidian():
    dados = copy.deepcopy(sample("programs"))
    dados.append({"Source": "HKCU", "DisplayName": "Obsidian", "DisplayVersion": "1.7.4"})
    return dados


def sem_7zip():
    return [p for p in sample("programs") if p["DisplayName"] != "7-Zip 24.08 (x64)"]


def linha_de_base(banco, clock=None):
    take_snapshot(banco, make_context(respostas(), clock=clock), CHECKS, "auto")


# --- modo snapshot (sem interface) --------------------------------------------


def test_comando_snapshot_grava_um_snapshot_manual_e_imprime_o_resumo(banco):
    """Dado o comando `snapshot`, então ele grava um snapshot manual e imprime o resumo."""
    saida = io.StringIO()

    codigo = cmd_snapshot(banco, make_context(respostas()), CHECKS, saida)

    assert codigo == 0
    assert banco.latest_snapshot().kind == "manual"
    texto = saida.getvalue()
    assert "winzel — snapshot #1 (manual) em 31/10/2026 14:30" in texto
    assert "🟢 Programas: 6 programas — linha de base registrada agora" in texto
    assert "Status geral: 🟢 ok" in texto


def test_resumo_lista_as_mudancas_com_simbolo_categoria_nome_e_versoes(banco):
    """Dado um programa novo e um removido, então o resumo lista ➕ e ➖ com nome e versão."""
    clock = FixedClock()
    linha_de_base(banco, clock)
    clock.advance(days=1)
    dados = [p for p in com_obsidian() if p["DisplayName"] != "7-Zip 24.08 (x64)"]
    saida = io.StringIO()

    cmd_snapshot(banco, make_context(respostas(programs=dados), clock=clock), CHECKS, saida)

    texto = saida.getvalue()
    assert "🟡 Programas: 6 programas — 1 novo, 1 removido desde a linha de base" in texto
    assert "  ➕ Programas: Obsidian  1.7.4" in texto
    assert "  ➖ Programas: 7-Zip 24.08 (x64)  24.08" in texto
    assert "Status geral: 🟡 atenção" in texto


def test_resumo_avisa_quando_o_snapshot_foi_feito_sem_admin(banco):
    """Dado um snapshot sem elevação, então o resumo traz o aviso; com elevação, não."""
    sem_admin = take_snapshot(banco, make_context(respostas()), CHECKS, "manual")
    com_admin = take_snapshot(banco, make_context(respostas(), is_admin=True), CHECKS, "manual")

    assert "sem privilégios de administrador" in format_report(sem_admin)
    assert "sem privilégios de administrador" not in format_report(com_admin)


def test_resumo_mostra_checagem_com_erro_e_sua_mensagem(banco):
    """Dado erro em startup, então o resumo mostra ❗ Inicialização com a mensagem de erro."""
    report = take_snapshot(
        banco, make_context(respostas(startup=RuntimeError("acesso negado"))), CHECKS, "manual"
    )

    assert "❗ Inicialização: erro: acesso negado" in format_report(report)


def test_resumo_em_texto_sem_emojis_quando_configurado(banco):
    """Dado display.emoji = false, então o resumo usa [OK], [!] e +/-, sem emojis."""
    linha_de_base(banco)
    report = take_snapshot(
        banco, make_context(respostas(programs=com_obsidian())), CHECKS, "manual"
    )

    texto = format_report(report, emoji=False)

    assert "[!] Programas:" in texto
    assert "  + Programas: Obsidian  1.7.4" in texto
    assert "🟡" not in texto and "➕" not in texto


def test_python_m_winzel_snapshot_usa_o_banco_indicado(tmp_path):
    """Dado `winzel --db <arquivo> snapshot`, então o snapshot é gravado nesse arquivo."""
    banco = tmp_path / "w.db"
    saida = io.StringIO()

    codigo = main(
        ["--db", str(banco), "--config", str(tmp_path / "nao-existe.toml"), "snapshot"],
        context_factory=lambda config: make_context(respostas(), config=config),
        out=saida,
    )

    assert codigo == 0
    assert banco.exists()
    assert "snapshot #1 (manual)" in saida.getvalue()


def test_config_invalido_encerra_com_codigo_2_e_mensagem(tmp_path, capsys):
    """Dado um config.toml inválido, então o winzel encerra com código 2 e explica o motivo."""
    config = tmp_path / "config.toml"
    config.write_text("[[", encoding="utf-8")

    codigo = main(["--db", str(tmp_path / "w.db"), "--config", str(config), "snapshot"])

    assert codigo == 2
    assert "configuração inválida" in capsys.readouterr().err


# --- filtros da aba Mudanças --------------------------------------------------


def mudanca(kind, category):
    return Change(kind, category, f"{category}-{kind}", "x", None, None)


def test_filtros_por_categoria_e_por_tipo():
    """Dadas mudanças variadas, quando filtro por categoria e tipo, então só ficam as escolhidas."""
    mudancas = [
        mudanca(ChangeKind.ADDED, "programs"),
        mudanca(ChangeKind.REMOVED, "programs"),
        mudanca(ChangeKind.ADDED, "startup"),
    ]

    assert len(filter_changes(mudancas)) == 3
    assert len(filter_changes(mudancas, category="programs")) == 2
    assert len(filter_changes(mudancas, kind="added")) == 2
    assert filter_changes(mudancas, "programs", "added") == [mudancas[0]]


# --- aplicação Textual --------------------------------------------------------


def texto(app, seletor):
    return str(app.query_one(seletor, Static).content)


async def esperar_snapshot(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


def rodar(coro):
    return asyncio.run(coro)


def test_interface_abre_grava_snapshot_automatico_e_mostra_a_visao_geral(banco):
    """Dado o winzel aberto, então ele grava um snapshot auto e mostra os cartões por área."""
    app = WinzelApp(banco, make_context(respostas()), CHECKS)

    async def cenario():
        async with app.run_test() as pilot:
            await esperar_snapshot(app, pilot)
            assert app.query_one("#tabs", TabbedContent).active == "overview"
            assert "Snapshot #1 (automático) em 31/10/2026 14:30" in texto(app, "#overview-header")
            assert "Referência: linha de base" in texto(app, "#overview-header")
            assert "Programas" in texto(app, "#card-programs")
            assert "6 programas — linha de base registrada agora" in texto(app, "#card-programs")
            assert "7 itens (3 desligados)" in texto(app, "#card-startup")

    rodar(cenario())
    assert banco.latest_snapshot().kind == "auto"


def test_interface_mostra_o_progresso_das_checagens_enquanto_rodam(banco):
    """Dada uma checagem demorada, então ela aparece com ⏳ e muda para o status ao terminar."""
    libera = threading.Event()

    def startup_lento():
        libera.wait(5)
        return sample("startup")

    app = WinzelApp(banco, make_context(respostas(startup=startup_lento)), CHECKS)

    async def cenario():
        async with app.run_test() as pilot:
            for _ in range(50):
                await pilot.pause(0.02)
                if texto(app, "#progress-programs").startswith("🟢"):
                    break
            assert texto(app, "#progress-programs").startswith("🟢 Programas")
            assert texto(app, "#progress-startup") == "⏳ Inicialização"
            assert app.query_one("#tabs").display is False
            libera.set()
            await esperar_snapshot(app, pilot)
            assert app.query_one("#tabs").display is True

    rodar(cenario())


def test_visao_geral_avisa_snapshot_sem_admin(banco):
    """Dado o winzel sem elevação, então a Visão geral mostra o aviso de administrador."""
    app = WinzelApp(banco, make_context(respostas()), CHECKS)

    async def cenario():
        async with app.run_test() as pilot:
            await esperar_snapshot(app, pilot)
            assert "sem privilégios de administrador" in texto(app, "#admin-warning")

    rodar(cenario())


def test_cartao_mostra_status_amarelo_e_resumo_com_as_mudancas(banco):
    """Dado um programa novo desde a linha de base, então o cartão Programas fica 🟡, "1 novo"."""
    linha_de_base(banco)
    app = WinzelApp(banco, make_context(respostas(programs=com_obsidian())), CHECKS)

    async def cenario():
        async with app.run_test() as pilot:
            await esperar_snapshot(app, pilot)
            cartao = texto(app, "#card-programs")
            assert "🟡" in cartao
            assert "1 novo desde a linha de base" in cartao
            assert app.query_one("#card-programs").has_class("status-warn")

    rodar(cenario())


def test_aba_mudancas_lista_tipo_categoria_item_e_versoes(banco):
    """Dado um programa novo e um removido, então a aba Mudanças tem duas linhas."""
    linha_de_base(banco)
    dados = [p for p in com_obsidian() if p["DisplayName"] != "7-Zip 24.08 (x64)"]
    app = WinzelApp(banco, make_context(respostas(programs=dados)), CHECKS)

    async def cenario():
        async with app.run_test() as pilot:
            await esperar_snapshot(app, pilot)
            await pilot.press("tab")
            assert app.query_one("#tabs", TabbedContent).active == "changes"
            tabela = app.query_one("#changes-table", DataTable)
            linhas = [tabela.get_row_at(i) for i in range(tabela.row_count)]
            assert linhas == [
                ["➕ adicionado", "Programas", "Obsidian", "1.7.4", ""],
                ["➖ removido", "Programas", "7-Zip 24.08 (x64)", "24.08", ""],
            ]

    rodar(cenario())


def test_filtro_de_tipo_na_aba_mudancas_reduz_a_tabela(banco):
    """Dado o filtro "Removidos", então só a linha do 7-Zip fica na tabela."""
    linha_de_base(banco)
    dados = [p for p in com_obsidian() if p["DisplayName"] != "7-Zip 24.08 (x64)"]
    app = WinzelApp(banco, make_context(respostas(programs=dados)), CHECKS)

    async def cenario():
        async with app.run_test() as pilot:
            await esperar_snapshot(app, pilot)
            app.query_one("#filter-kind", Select).value = "removed"
            await pilot.pause()
            tabela = app.query_one("#changes-table", DataTable)
            assert tabela.row_count == 1
            assert tabela.get_row_at(0)[2] == "7-Zip 24.08 (x64)"
            app.query_one("#filter-category", Select).value = "startup"
            await pilot.pause()
            assert tabela.row_count == 0
            assert "Nenhuma mudança com estes filtros." in texto(app, "#changes-empty")
            app.query_one("#filter-kind", Select).value = ALL
            app.query_one("#filter-category", Select).value = ALL
            await pilot.pause()
            assert tabela.row_count == 2

    rodar(cenario())


def test_sem_mudancas_a_aba_informa_que_nada_mudou(banco):
    """Dado o primeiro snapshot (linha de base), então a aba Mudanças diz que não há mudanças."""
    app = WinzelApp(banco, make_context(respostas()), CHECKS)

    async def cenario():
        async with app.run_test() as pilot:
            await esperar_snapshot(app, pilot)
            assert "Nenhuma mudança em relação à linha de base." in texto(app, "#changes-empty")

    rodar(cenario())


def test_tecla_r_grava_novo_snapshot_e_q_sai(banco):
    """Dado o winzel aberto, quando pressiono r, então um 2º snapshot é gravado; q encerra."""
    app = WinzelApp(banco, make_context(respostas()), CHECKS)

    async def cenario():
        async with app.run_test() as pilot:
            await esperar_snapshot(app, pilot)
            await pilot.press("r")
            await esperar_snapshot(app, pilot)
            assert "Snapshot #2" in texto(app, "#overview-header")
            await pilot.press("q")

    rodar(cenario())
    assert len(banco.snapshots()) == 2


def test_tab_alterna_entre_as_abas(banco):
    """Dado o winzel na Visão geral, quando pressiono Tab, então percorro as abas e volto."""
    app = WinzelApp(banco, make_context(respostas()), CHECKS)

    async def cenario():
        async with app.run_test() as pilot:
            await esperar_snapshot(app, pilot)
            tabs = app.query_one("#tabs", TabbedContent)
            await pilot.press("tab")
            assert tabs.active == "changes"
            await pilot.press("tab")
            assert tabs.active == "timeline"
            await pilot.press("tab")
            assert tabs.active == "overview"

    rodar(cenario())


def test_falha_ao_gravar_o_snapshot_aparece_na_tela_sem_derrubar_a_interface(banco):
    """Dado um erro ao gravar o snapshot, então a mensagem aparece e r permite tentar de novo."""

    def falha(*args, **kwargs):
        raise RuntimeError("disco cheio")

    app = WinzelApp(banco, make_context(respostas()), CHECKS, snapshot_fn=falha)

    async def cenario():
        async with app.run_test() as pilot:
            await esperar_snapshot(app, pilot)
            assert "Falha ao gravar o snapshot: disco cheio" in texto(app, "#progress-title")

    rodar(cenario())
