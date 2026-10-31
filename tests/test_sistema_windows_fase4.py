"""Integração com o Windows real para as métricas da fase 4 (`pytest -m sistema`)."""

import sys

import pytest

from winzel.checks import get_check
from winzel.config import load_config
from winzel.context import production_context
from winzel.models import Status
from winzel.runner import run_checks

pytestmark = [
    pytest.mark.fase4,
    pytest.mark.armazenamento,
    pytest.mark.sistema,
    pytest.mark.skipif(sys.platform != "win32", reason="requer Windows"),
]

FASE4 = ["disk_c", "dev_drive", "clutter", "battery", "ssd"]


@pytest.fixture(scope="module")
def resultados():
    ctx = production_context(load_config())
    return {r.check_id: r for r in run_checks([get_check(c) for c in FASE4], ctx)}


@pytest.mark.parametrize("check_id", FASE4)
def test_metrica_roda_no_windows_real_sem_erro(resultados, check_id):
    """Dado o Windows real e o config do usuário, quando a métrica roda, então não termina em ❗."""
    r = resultados[check_id]

    assert r.status is not Status.ERROR, r.error


def test_espaco_no_c_e_coerente(resultados):
    """Dado o Windows real, então o C: tem total positivo e % livre entre 0 e 100."""
    valores = {m.name: m.value for m in resultados["disk_c"].metrics}

    assert valores["disk_c_total_gb"] > 0
    assert 0 <= valores["disk_c_free_pct"] <= 100


def test_dev_drive_encontra_o_vhdx(resultados):
    """Dado o Dev Drive desta máquina, então o arquivo VHDX é encontrado (config ou descoberta)."""
    assert "VHDX não encontrado" not in resultados["dev_drive"].summary
