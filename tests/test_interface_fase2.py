"""Interface com todas as categorias do inventário (fase 2)."""

import asyncio
import io

import pytest
from tests.fakes import all_responses, make_context
from textual.widgets import Select, Static

from winzel.checks import all_checks
from winzel.cli import cmd_snapshot
from winzel.ui.app import WinzelApp

pytestmark = [pytest.mark.fase2, pytest.mark.interface]


def checagens_do_inventario():
    """As 7 checagens do inventário (as métricas da fase 4 ficam de fora)."""
    return [c for c in all_checks() if c.area == "inventario"]


ROTULOS = [
    "Programas",
    "Apps da Store",
    "Inicialização",
    "Tarefas agendadas",
    "Serviços",
    "Python global (pip)",
    "Distribuições WSL",
]


def test_visao_geral_tem_um_cartao_por_categoria_e_filtro_com_todas(banco):
    """Dadas as 7 checagens, então a Visão geral tem 7 cartões e o filtro, as 7 categorias."""
    app = WinzelApp(banco, make_context(all_responses()), checagens_do_inventario())

    async def cenario():
        async with app.run_test(size=(120, 50)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            cartoes = [str(c.content) for c in app.query(".card").results(Static)]
            assert [next(r for r in ROTULOS if f"[b]{r}[/b]" in c) for c in cartoes] == ROTULOS
            assert [rotulo for rotulo, _ in app.category_options()][1:] == ROTULOS
            app.query_one("#filter-category", Select).value = "services"

    asyncio.run(cenario())


def test_resumo_sem_interface_lista_as_7_categorias(banco):
    """Dado `winzel snapshot` com todas as checagens, então o resumo tem uma linha por categoria."""
    saida = io.StringIO()

    cmd_snapshot(banco, make_context(all_responses()), checagens_do_inventario(), saida)

    texto = saida.getvalue()
    for rotulo in ROTULOS:
        assert f"🟢 {rotulo}:" in texto
    assert "1 pacote (só o pip) em C:\\Python314\\python.exe" in texto
