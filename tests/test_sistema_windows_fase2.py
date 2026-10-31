"""Integração com o Windows real para as checagens da fase 2 (`pytest -m sistema`)."""

import sys

import pytest

from winzel.checks import get_check
from winzel.config import load_default_config
from winzel.context import production_context
from winzel.models import Status
from winzel.runner import run_checks

pytestmark = [
    pytest.mark.fase2,
    pytest.mark.inventario,
    pytest.mark.sistema,
    pytest.mark.skipif(sys.platform != "win32", reason="requer Windows"),
]

FASE2 = ["store_apps", "scheduled_tasks", "services", "pip_global", "wsl_distros"]


@pytest.fixture(scope="module")
def resultados():
    ctx = production_context(load_default_config())
    return {r.check_id: r for r in run_checks([get_check(c) for c in FASE2], ctx)}


@pytest.mark.parametrize("check_id", FASE2)
def test_checagem_roda_no_windows_real_sem_erro(resultados, check_id):
    """Dado o Windows real, quando a checagem roda, então ela não termina em erro (❗)."""
    r = resultados[check_id]

    assert r.status is not Status.ERROR, r.error


@pytest.mark.parametrize("check_id", FASE2)
def test_chaves_sao_unicas_no_windows_real(resultados, check_id):
    """Dado o Windows real, então nenhuma chave se repete dentro da categoria."""
    chaves = [i.key for i in resultados[check_id].items]

    assert len(chaves) == len(set(chaves))


def test_servicos_listados_estao_fora_de_c_windows(resultados):
    """Dado o Windows real, então nenhum serviço listado tem executável em C:\\Windows."""
    for item in resultados["services"].items:
        assert not item.details["executable"].lower().startswith("c:\\windows\\")


def test_python_global_nao_e_um_venv(resultados):
    """Dado o Windows real, então o Python checado é o global (ou a checagem fica ⚪)."""
    r = resultados["pip_global"]

    assert r.status is not Status.ERROR, r.error
    assert ".venv" not in r.summary
