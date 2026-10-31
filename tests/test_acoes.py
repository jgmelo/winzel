"""Ações: lista fechada, sempre em duas etapas (plano só de leitura → confirmação → execução).

Os testes de interface garantem, para cada ação, que nada é executado sem confirmação.
"""

import asyncio

import pytest
from tests.fakes import FakeFileSystem, make_context, ok
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from winzel.actions import (
    ACTIONS,
    EmptySandboxesAction,
    EmptyTempAction,
    RestorePointAction,
    WingetUpgradeAction,
)
from winzel.checks import get_check
from winzel.commands import CommandResult
from winzel.filesystem import GB, ClearResult, DirSize
from winzel.snapshot import take_snapshot
from winzel.ui.app import WinzelApp

pytestmark = [pytest.mark.fase5, pytest.mark.interface]

TEMP = "C:\\Users\\jg\\AppData\\Local\\Temp"
START = "C:\\Program Files\\Sandboxie-Plus\\Start.exe"
CAIXAS = "C:\\Sandbox\\jg"
WINGET = {
    "packages": [
        {"Id": "Git.Git", "Name": "Git", "Installed": "2.47.0", "Available": "2.48.1"},
        {"Id": "Obsidian.Obsidian", "Name": "Obsidian", "Installed": "1.7.4", "Available": "1.7.7"},
    ]
}


def maquina():
    """Sistema de arquivos com Temp cheio, Sandboxie instalado e duas caixas."""
    fs = FakeFileSystem()
    fs.dirs[TEMP] = DirSize(2 * GB, 1200)
    fs.clear_results[TEMP] = ClearResult(removed=1190, failed=10)
    fs.existing.add(START)
    fs.subdirs[CAIXAS] = ["DefaultBox", "Navegador"]
    return fs


def relatorio_com_winget(banco, fs=None):
    ctx = make_context({"winget_updates": WINGET}, fs=fs)
    return take_snapshot(banco, ctx, [get_check("winget_updates")], "auto")


# --- planos (só leitura) -------------------------------------------------------------


def test_a_lista_de_acoes_e_fechada():
    """Dado o winzel, então existem exatamente estas cinco ações."""
    assert [a.id for a in ACTIONS] == [
        "winget_upgrade",
        "empty_temp",
        "empty_sandboxes",
        "restore_point",
        "milestone",
    ]


def test_plano_do_winget_lista_cada_pacote_e_o_comando(banco):
    """Dados dois pacotes com atualização no snapshot, então o plano cita os dois e o comando."""
    report = relatorio_com_winget(banco)
    ctx = make_context({})

    plano = WingetUpgradeAction().plan(ctx, report)

    assert plano.steps == [
        "Git (Git.Git): 2.47.0 → 2.48.1",
        "Obsidian (Obsidian.Obsidian): 1.7.4 → 1.7.7",
    ]
    assert plano.commands[0][:5] == ["winget", "upgrade", "--id", "Git.Git", "--exact"]
    assert ctx.commands.calls == []


def test_plano_do_winget_sem_atualizacoes_nao_tem_nada_a_fazer(banco):
    """Dado um snapshot sem pacotes para atualizar, então o plano diz que não há nada a fazer."""
    report = take_snapshot(
        banco,
        make_context({"winget_updates": {"packages": []}}),
        [get_check("winget_updates")],
        "auto",
    )

    plano = WingetUpgradeAction().plan(make_context({}), report)

    assert plano.nothing_to_do == "Nenhum pacote do winget com atualização no snapshot exibido."


def test_execucao_do_winget_roda_exatamente_os_comandos_do_plano(banco):
    """Dado o plano confirmado, então cada pacote é atualizado e o resultado diz quais falharam."""
    plano = WingetUpgradeAction().plan(make_context({}), relatorio_com_winget(banco))
    respostas = iter([ok(), CommandResult(1, b"", b"Instalador em uso\r\n")])
    ctx = make_context({"winget_upgrade": lambda args: next(respostas)})

    resultado = WingetUpgradeAction().execute(ctx, plano)

    assert [c["args"] for c in ctx.commands.calls] == plano.commands
    assert resultado.ok is False
    assert resultado.lines == ["✔ Git", "✖ Obsidian: Instalador em uso"]


def test_plano_do_temp_mostra_quantidade_tamanho_e_pasta():
    """Dado o Temp com 1200 arquivos (2 GB), então o plano mostra isso, sem apagar nada."""
    fs = maquina()

    plano = EmptyTempAction().plan(make_context({}, fs=fs), None)

    assert plano.steps == [f"Apagar 1200 arquivos (2,0 GB) de {TEMP}"]
    assert fs.cleared == []


def test_temp_vazio_nao_tem_nada_a_fazer():
    """Dado o Temp sem arquivos, então o plano diz que a pasta já está vazia."""
    fs = FakeFileSystem()
    fs.dirs[TEMP] = DirSize(0, 0)

    plano = EmptyTempAction().plan(make_context({}, fs=fs), None)

    assert plano.nothing_to_do == f"{TEMP} já está vazia."


def test_esvaziar_temp_informa_itens_apagados_e_mantidos():
    """Dado o plano confirmado, então o Temp é esvaziado e os arquivos em uso são informados."""
    fs = maquina()
    ctx = make_context({}, fs=fs)

    resultado = EmptyTempAction().execute(ctx, EmptyTempAction().plan(ctx, None))

    assert fs.cleared == [TEMP]
    assert resultado.lines == [
        f"✔ 1190 itens apagados de {TEMP}",
        "• 10 itens em uso foram mantidos",
    ]


def test_plano_das_sandboxes_usa_o_proprio_sandboxie_para_cada_caixa():
    """Dadas duas caixas, então o plano usa `Start.exe /box:<caixa> delete_sandbox_silent`."""
    plano = EmptySandboxesAction().plan(make_context({}, fs=maquina()), None)

    assert plano.commands == [
        [START, "/box:DefaultBox", "delete_sandbox_silent"],
        [START, "/box:Navegador", "delete_sandbox_silent"],
    ]
    assert "não esvazia caixas com programas abertos" in plano.note


def test_sem_sandboxie_instalado_nao_ha_nada_a_fazer():
    """Dado que o Start.exe do Sandboxie-Plus não existe, então o plano explica e não faz nada."""
    plano = EmptySandboxesAction().plan(make_context({}, fs=FakeFileSystem()), None)

    assert plano.nothing_to_do.startswith("Sandboxie-Plus não encontrado")


def test_ponto_de_restauracao_exige_admin_e_avisa_do_limite_de_24_horas():
    """Dado o ponto de restauração, então a ação exige admin e o plano cita o limite do Windows."""
    plano = RestorePointAction().plan(make_context({}), None)

    assert RestorePointAction.requires_admin is True
    assert "um ponto a cada 24 horas" in plano.note


# --- interface: nada é executado sem confirmação --------------------------------------


def app_com_acoes(banco, fs, is_admin=True, respostas=None):
    take_snapshot(
        banco,
        make_context({"winget_updates": WINGET}, fs=fs),
        [get_check("winget_updates")],
        "auto",
    )
    respostas = {"winget_updates": WINGET, **(respostas or {})}
    ctx = make_context(respostas, fs=fs, is_admin=is_admin)
    return WinzelApp(banco, ctx, [get_check("winget_updates")]), ctx


async def abrir_acao(app, pilot, action_id):
    await app.workers.wait_for_complete()
    await pilot.pause()
    for _ in range(3):
        await pilot.press("tab")
    tabela = app.query_one("#actions-table", DataTable)
    tabela.move_cursor(row=tabela.get_row_index(action_id))
    await pilot.press("enter")
    await pilot.pause()


def saida(app):
    return str(app.query_one("#action-output", Static).content)


@pytest.mark.parametrize(
    "action_id", ["winget_upgrade", "empty_temp", "empty_sandboxes", "restore_point"]
)
def test_cancelar_a_confirmacao_nao_executa_nada(banco, action_id):
    """Dada cada ação, quando cancelo a confirmação, então nenhum comando roda e nada é apagado."""
    fs = maquina()
    app, ctx = app_com_acoes(banco, fs)

    async def cenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await abrir_acao(app, pilot, action_id)
            assert isinstance(app.screen, ModalScreen)
            await pilot.press("escape")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert "cancelada; nada foi feito" in saida(app)

    asyncio.run(cenario())
    assert ctx.commands.calls == []
    assert fs.cleared == []
    assert [c["label"] for c in ctx.powershell.calls] == ["winget_updates"]


def test_confirmar_executa_e_mostra_o_resultado(banco):
    """Dada a ação "Esvaziar a pasta Temp", quando confirmo, então o Temp é esvaziado."""
    fs = maquina()
    app, _ = app_com_acoes(banco, fs)

    async def cenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await abrir_acao(app, pilot, "empty_temp")
            detalhes = str(app.screen.query_one("#confirm-details", Static).content)
            assert detalhes.startswith(f"• Apagar 1200 arquivos (2,0 GB) de {TEMP}")
            await pilot.click("#ok")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert saida(app).startswith("Esvaziar a pasta Temp: concluída.")

    asyncio.run(cenario())
    assert fs.cleared == [TEMP]


def test_confirmar_atualizacao_do_winget_roda_os_comandos(banco):
    """Dada a atualização do winget confirmada, então o winget é chamado para cada pacote."""
    fs = maquina()
    app, ctx = app_com_acoes(banco, fs, respostas={"winget_upgrade": ok()})

    async def cenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await abrir_acao(app, pilot, "winget_upgrade")
            await pilot.click("#ok")
            await pilot.pause()
            await app.workers.wait_for_complete()

    asyncio.run(cenario())
    ids = [c["args"][3] for c in ctx.commands.calls]
    assert ids == ["Git.Git", "Obsidian.Obsidian"]


def test_acao_que_exige_admin_sem_elevacao_nem_pede_confirmacao(banco):
    """Dado o winzel sem admin, quando escolho o ponto de restauração, então nada é executado."""
    fs = maquina()
    app, ctx = app_com_acoes(banco, fs, is_admin=False)

    async def cenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await abrir_acao(app, pilot, "restore_point")
            assert not isinstance(app.screen, ModalScreen)
            assert "requer executar o winzel como administrador" in saida(app)

    asyncio.run(cenario())
    assert [c["label"] for c in ctx.powershell.calls] == ["winget_updates"]


def test_acao_sem_nada_a_fazer_nao_pede_confirmacao(banco):
    """Dado o Temp vazio, quando escolho esvaziá-lo, então só aparece "nada a fazer"."""
    fs = maquina()
    fs.dirs[TEMP] = DirSize(0, 0)
    app, _ = app_com_acoes(banco, fs)

    async def cenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await abrir_acao(app, pilot, "empty_temp")
            assert not isinstance(app.screen, ModalScreen)
            assert "nada a fazer" in saida(app)

    asyncio.run(cenario())
    assert fs.cleared == []


def test_acao_criar_milestone_abre_a_janela_do_milestone(banco):
    """Dada a ação "Criar milestone", então abre a mesma janela da tecla m (com nome e nota)."""
    app, _ = app_com_acoes(banco, maquina())

    async def cenario():
        async with app.run_test(size=(140, 40)) as pilot:
            await abrir_acao(app, pilot, "milestone")
            assert app.screen.query_one("#milestone-name") is not None

    asyncio.run(cenario())


def test_dados_do_winget_vem_do_snapshot_e_nao_de_nova_consulta(banco):
    """Dado o plano do winget, então ele usa o snapshot exibido, sem consultar o winget de novo."""
    report = relatorio_com_winget(banco)
    ctx = make_context({})

    WingetUpgradeAction().plan(ctx, report)

    assert ctx.powershell.calls == []
    assert ctx.commands.calls == []
