"""Robustez: uma checagem com dados inesperados não impede o snapshot nem trava a interface.

Regressão: chaves duplicadas numa checagem faziam o banco recusar o snapshot inteiro, e a
interface ficava presa na tela de progresso, sem acesso às abas.
"""

import asyncio
from dataclasses import dataclass

import pytest
from tests.fakes import make_context, sample
from textual.widgets import Static, TabbedContent

from winzel.checks import get_check
from winzel.models import CheckResult, Item, Status
from winzel.runner import run_checks
from winzel.snapshot import take_snapshot
from winzel.ui.app import WinzelApp

pytestmark = [pytest.mark.fase5, pytest.mark.execucao]


@dataclass
class ChecagemComDuplicatas:
    id: str = "duplicada"
    label: str = "Duplicada"
    area: str = "atualizacoes"
    requires_admin: bool = False
    timeout_s: float = 5.0

    def run(self, ctx):
        itens = [Item(self.id, "KB1", None), Item(self.id, "KB1", None)]
        return CheckResult(self.id, Status.OK, "2 itens", items=itens)


def test_checagem_com_chaves_duplicadas_vira_erro_e_nao_afeta_as_demais():
    """Dada uma checagem que devolve a chave KB1 duas vezes, então ela fica ❗ citando a chave."""
    duplicada, programas = run_checks(
        [ChecagemComDuplicatas(), get_check("programs")],
        make_context({"programs": sample("programs")}),
    )

    assert duplicada.status is Status.ERROR
    assert duplicada.error == "chaves duplicadas: KB1"
    assert programas.status is Status.OK


def test_snapshot_e_gravado_mesmo_com_uma_checagem_com_chaves_duplicadas(banco):
    """Dada uma checagem com chaves duplicadas, quando gravo o snapshot, então ele é gravado."""
    report = take_snapshot(
        banco,
        make_context({"programs": sample("programs")}),
        [ChecagemComDuplicatas(), get_check("programs")],
        "auto",
    )

    assert banco.snapshot(report.snapshot.id) is not None
    assert banco.check_runs(report.snapshot.id)["duplicada"].status is Status.ERROR


def test_falha_ao_gravar_mostra_o_ultimo_snapshot_e_libera_as_abas(banco):
    """Dado um snapshot anterior no banco e uma falha ao gravar o novo, então as abas funcionam."""
    checks = [get_check("programs")]
    take_snapshot(banco, make_context({"programs": sample("programs")}), checks, "auto")

    def falha(*args, **kwargs):
        raise RuntimeError("disco cheio")

    app = WinzelApp(banco, make_context({}), checks, snapshot_fn=falha)

    async def cenario():
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            tabs = app.query_one("#tabs", TabbedContent)
            assert tabs.display is True
            header = str(app.query_one("#overview-header", Static).content)
            assert header.startswith("Snapshot #1")
            await pilot.press("tab")
            assert tabs.active == "changes"

    asyncio.run(cenario())
