"""Interface na fase 3: referência escolhida, milestones (m, d) e aprovações (a).

Exercitada com o terminal virtual do Textual, banco em memória e PowerShell falso.
O banco já tem a linha de base; o snapshot aberto tem o Obsidian novo e o Git atualizado.
"""

import asyncio
import copy
from datetime import datetime

import pytest
from tests.fakes import FixedClock, make_context, sample
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Select, Static

from winzel.checks import get_check
from winzel.snapshot import take_snapshot
from winzel.ui.app import WinzelApp

pytestmark = [pytest.mark.fase3, pytest.mark.interface]

CHECKS = [get_check("programs"), get_check("startup")]


def programas_alterados():
    dados = copy.deepcopy(sample("programs"))
    dados.append({"Source": "HKCU", "DisplayName": "Obsidian", "DisplayVersion": "1.7.4"})
    for p in dados:
        if p["DisplayName"] == "Git":
            p["DisplayVersion"] = "2.48.1"
    return dados


def preparar(banco):
    """Linha de base no banco; devolve o app que abrirá o 2º snapshot (com mudanças)."""
    clock = FixedClock()
    base = {"programs": sample("programs"), "startup": sample("startup")}
    take_snapshot(banco, make_context(base, clock=clock), CHECKS, "auto")
    clock.advance(days=1)
    ctx = make_context(
        {"programs": programas_alterados(), "startup": sample("startup")}, clock=clock
    )
    return WinzelApp(banco, ctx, CHECKS)


def texto(app, seletor):
    return str(app.query_one(seletor, Static).content)


def linhas(app):
    tabela = app.query_one("#changes-table", DataTable)
    return [tabela.get_row_at(i) for i in range(tabela.row_count)]


async def abrir(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


async def ir_para_mudancas(app, pilot):
    await pilot.press("tab")
    await pilot.pause()


async def selecionar(app, pilot, nome):
    tabela = app.query_one("#changes-table", DataTable)
    indice = next(i for i, linha in enumerate(linhas(app)) if linha[2] == nome)
    tabela.focus()
    tabela.move_cursor(row=indice)
    await pilot.pause()


async def digitar(pilot, texto_):
    await pilot.press(*texto_)


def rodar(app, cenario):
    async def principal():
        async with app.run_test(size=(140, 45)) as pilot:
            await abrir(app, pilot)
            await cenario(app, pilot)

    asyncio.run(principal())


# --- referência -----------------------------------------------------------------


def test_cabecalho_mostra_a_referencia_atual(banco):
    """Dado um snapshot comparado com a linha de base, então o cabeçalho diz qual é a referência."""

    async def cenario(app, pilot):
        assert "Referência: linha de base (31/10/2026 14:30)" in texto(app, "#overview-header")

    rodar(preparar(banco), cenario)


def test_seletor_lista_milestones_e_ultimo_snapshot(banco):
    """Dados linha-de-base e "limpo", então o seletor os lista, mais "último snapshot"."""
    app = preparar(banco)
    banco.create_milestone(1, "limpo", "máquina recém-formatada", datetime(2026, 11, 1))

    async def cenario(app, pilot):
        assert [rotulo for rotulo, _ in app.reference_options()] == [
            "milestone limpo (31/10/2026 14:30)",
            "linha de base (31/10/2026 14:30)",
            "último snapshot",
        ]
        assert texto(app, "#reference-note") == "Nota: máquina recém-formatada"

    rodar(app, cenario)


def test_trocar_a_referencia_recalcula_mudancas_e_cartoes(banco):
    """Dado o seletor em "último snapshot" após snapshots iguais, então nada muda (🟢)."""
    clock = FixedClock()
    base = {"programs": programas_alterados(), "startup": sample("startup")}
    take_snapshot(
        banco,
        make_context({"programs": sample("programs"), "startup": sample("startup")}, clock=clock),
        CHECKS,
        "auto",
    )
    clock.advance(days=1)
    take_snapshot(banco, make_context(base, clock=clock), CHECKS, "auto")
    clock.advance(days=1)
    app = WinzelApp(banco, make_context(base, clock=clock), CHECKS)

    async def cenario(app, pilot):
        assert len(linhas(app)) == 2
        app.query_one("#filter-reference", Select).value = "previous"
        await pilot.pause()
        assert linhas(app) == []
        assert "Referência: último snapshot" in texto(app, "#overview-header")
        assert texto(app, "#card-programs").startswith("🟢")
        assert "Nenhuma mudança em relação a: último snapshot." in texto(app, "#changes-empty")

    rodar(app, cenario)


# --- milestones -----------------------------------------------------------------


def test_tecla_m_cria_milestone_no_snapshot_exibido_e_passa_a_compara_com_ele(banco):
    """Dado o 2º snapshot na tela, quando crio "com-obsidian", então ele vira a referência."""

    async def cenario(app, pilot):
        await pilot.press("m")
        await pilot.pause()
        assert isinstance(app.screen, ModalScreen)
        await digitar(pilot, "com-obsidian")
        app.screen.query_one("#milestone-note", Input).value = "depois do Obsidian"
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, ModalScreen)
        marco = banco.milestone("com-obsidian")
        assert (marco.snapshot.id, marco.note) == (2, "depois do Obsidian")
        assert "Referência: milestone com-obsidian" in texto(app, "#overview-header")
        assert linhas(app) == []

    rodar(preparar(banco), cenario)


def test_nome_de_milestone_repetido_mostra_erro_e_mantem_a_janela(banco):
    """Dado o nome reservado "linha-de-base", quando tento criar, então a janela mostra o erro."""

    async def cenario(app, pilot):
        await pilot.press("m")
        await pilot.pause()
        await digitar(pilot, "linha-de-base")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ModalScreen)
        erro = str(app.screen.query_one("#milestone-error", Static).content)
        assert erro == "O nome linha-de-base é reservado."
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ModalScreen)
        assert [m.name for m in banco.milestones()] == ["linha-de-base"]

    rodar(preparar(banco), cenario)


def test_tecla_d_apaga_o_milestone_escolhido_apos_confirmacao(banco):
    """Dado "limpo" como referência, quando pressiono d e confirmo, então ele é apagado."""
    app = preparar(banco)
    banco.create_milestone(1, "limpo", "", datetime(2026, 11, 1))

    async def cenario(app, pilot):
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ModalScreen)
        await pilot.click("#ok")
        await pilot.pause()
        assert banco.milestone("limpo") is None
        assert "Referência: linha de base" in texto(app, "#overview-header")

    rodar(app, cenario)


def test_cancelar_a_confirmacao_nao_apaga_o_milestone(banco):
    """Dado o pedido de apagar "limpo", quando cancelo, então ele continua existindo."""
    app = preparar(banco)
    banco.create_milestone(1, "limpo", "", datetime(2026, 11, 1))

    async def cenario(app, pilot):
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert banco.milestone("limpo") is not None

    rodar(app, cenario)


def test_linha_de_base_nao_pode_ser_apagada_pela_interface(banco):
    """Dada a linha de base como referência, quando pressiono d, então nada é aberto."""

    async def cenario(app, pilot):
        await pilot.press("d")
        await pilot.pause()
        assert not isinstance(app.screen, ModalScreen)
        assert banco.milestone("linha-de-base") is not None

    rodar(preparar(banco), cenario)


# --- aprovações -----------------------------------------------------------------


def test_tecla_a_aprova_a_mudanca_selecionada_com_motivo(banco):
    """Dado o Obsidian novo selecionado, quando aprovo com motivo, então fica ✔ e o cartão 🟢."""

    async def cenario(app, pilot):
        await ir_para_mudancas(app, pilot)
        await selecionar(app, pilot, "Obsidian")
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, ModalScreen)
        await digitar(pilot, "uso diário")
        await pilot.press("enter")
        await pilot.pause()
        obsidian = next(linha for linha in linhas(app) if linha[2] == "Obsidian")
        assert obsidian[4] == "✔ aprovado"
        assert texto(app, "#card-programs").startswith("🟢")
        (aprovacao,) = banco.approvals().values()
        assert (aprovacao.key, aprovacao.change, aprovacao.reason) == (
            "obsidian|",
            "added",
            "uso diário",
        )

    rodar(preparar(banco), cenario)


def test_cancelar_a_aprovacao_nao_grava_nada(banco):
    """Dada a janela de aprovação aberta, quando cancelo, então nada é aprovado."""

    async def cenario(app, pilot):
        await ir_para_mudancas(app, pilot)
        await selecionar(app, pilot, "Obsidian")
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert banco.approvals() == {}

    rodar(preparar(banco), cenario)


def test_tecla_a_numa_mudanca_aprovada_pede_confirmacao_para_revogar(banco):
    """Dado o Obsidian já aprovado, quando pressiono a e confirmo, então a aprovação é revogada."""
    banco.approve("programs", "obsidian|", "added", "", datetime(2026, 11, 1))

    async def cenario(app, pilot):
        await ir_para_mudancas(app, pilot)
        await selecionar(app, pilot, "Obsidian")
        await pilot.press("a")
        await pilot.pause()
        assert str(app.screen.query_one("#ok", Button).label) == "Revogar"
        await pilot.click("#ok")
        await pilot.pause()
        assert banco.approvals() == {}
        assert texto(app, "#card-programs").startswith("🟡")

    rodar(preparar(banco), cenario)


def test_mudanca_de_versao_nao_abre_janela_de_aprovacao(banco):
    """Dado o Git atualizado (🔄) selecionado, quando pressiono a, então nada é aberto."""

    async def cenario(app, pilot):
        await ir_para_mudancas(app, pilot)
        await selecionar(app, pilot, "Git")
        await pilot.press("a")
        await pilot.pause()
        assert not isinstance(app.screen, ModalScreen)
        assert banco.approvals() == {}

    rodar(preparar(banco), cenario)


def test_filtro_pendentes_esconde_as_mudancas_aprovadas(banco):
    """Dado o Obsidian aprovado, quando filtro por "Pendentes", então só o Git aparece."""
    banco.approve("programs", "obsidian|", "added", "", datetime(2026, 11, 1))

    async def cenario(app, pilot):
        app.query_one("#filter-situation", Select).value = "pending"
        await pilot.pause()
        assert [linha[2] for linha in linhas(app)] == ["Git"]

    rodar(preparar(banco), cenario)


def test_tecla_a_fora_da_aba_mudancas_nao_faz_nada(banco):
    """Dada a Visão geral na tela, quando pressiono a, então nada é aprovado."""

    async def cenario(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        assert not isinstance(app.screen, ModalScreen)
        assert banco.approvals() == {}

    rodar(preparar(banco), cenario)
