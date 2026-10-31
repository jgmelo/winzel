"""Integração com o Windows real (marker `sistema`; rode com `pytest -m sistema`).

Executa as checagens contra o registro e as pastas desta máquina, sem gravar nada.
"""

import sys

import pytest

from winzel.checks import get_check
from winzel.config import load_default_config
from winzel.context import production_context
from winzel.models import Status
from winzel.runner import run_checks

pytestmark = [
    pytest.mark.fase1,
    pytest.mark.inventario,
    pytest.mark.sistema,
    pytest.mark.skipif(sys.platform != "win32", reason="requer Windows"),
]


@pytest.fixture(scope="module")
def resultados():
    ctx = production_context(load_default_config())
    checks = [get_check("programs"), get_check("startup")]
    return {r.check_id: r for r in run_checks(checks, ctx)}


def test_programas_rodam_no_windows_real_sem_erro(resultados):
    """Dado o Windows real, quando a checagem programs roda, então ela termina 🟢 com itens."""
    r = resultados["programs"]

    assert r.status is Status.OK, r.error
    assert r.items, "nenhum programa encontrado"
    assert all("|" in i.key and i.details["name"] for i in r.items)


def test_inicializacao_roda_no_windows_real_sem_erro(resultados):
    """Dado o Windows real, quando a checagem startup roda, então ela termina 🟢."""
    r = resultados["startup"]

    assert r.status is Status.OK, r.error
    assert all(isinstance(i.details["enabled"], bool) for i in r.items)


def test_chaves_sao_unicas_no_windows_real(resultados):
    """Dado o Windows real, então nenhuma chave se repete dentro de uma categoria."""
    for r in resultados.values():
        chaves = [i.key for i in r.items]
        assert len(chaves) == len(set(chaves)), r.check_id
