"""Integração com o Windows real para as checagens da fase 5 (`pytest -m sistema`).

Só lê o estado do sistema: nenhuma ação é executada.
"""

import sys

import pytest

from winzel.checks import get_check
from winzel.config import load_config
from winzel.context import production_context
from winzel.models import Status
from winzel.runner import run_checks

pytestmark = [
    pytest.mark.fase5,
    pytest.mark.atualizacoes,
    pytest.mark.sistema,
    pytest.mark.skipif(sys.platform != "win32", reason="requer Windows"),
]

FASE5 = ["winget_updates", "windows_update", "defender", "encryption", "restore_point", "git_repos"]


@pytest.fixture(scope="module")
def resultados():
    ctx = production_context(load_config())
    return {r.check_id: r for r in run_checks([get_check(c) for c in FASE5], ctx)}


@pytest.mark.parametrize("check_id", FASE5)
def test_checagem_roda_no_windows_real_sem_erro(resultados, check_id):
    """Dado o Windows real e o config do usuário, então a checagem não termina em ❗."""
    r = resultados[check_id]

    assert r.status is not Status.ERROR, r.error


def test_defender_responde(resultados):
    """Dado o Windows real, então o Defender informa a data das assinaturas."""
    assert "assinaturas de" in resultados["defender"].summary
