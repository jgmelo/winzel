"""Segurança: Microsoft Defender e criptografia do disco (SPEC 5.3)."""

from datetime import datetime

import pytest
from tests.fakes import FixedClock, make_context

from winzel.checks.defender import DefenderCheck
from winzel.checks.encryption import EncryptionCheck
from winzel.models import Status
from winzel.runner import run_checks

pytestmark = [pytest.mark.fase5, pytest.mark.seguranca]

AGORA = datetime(2026, 11, 10, 12, 0)


def defender(atualizado="2026-11-09T12:00:00", antivirus=True, tempo_real=True):
    status = {
        "AntivirusEnabled": antivirus,
        "RealTimeProtectionEnabled": tempo_real,
        "SignatureLastUpdated": atualizado,
        "SignatureVersion": "1.421.0.0",
    }
    return DefenderCheck().run(make_context({"defender": status}, clock=FixedClock(AGORA)))


def test_defender_ativo_com_assinaturas_recentes_fica_verde():
    """Dados antivírus e tempo real ligados e assinaturas de ontem, então 🟢."""
    resultado = defender()

    assert resultado.status is Status.OK
    assert resultado.summary == "proteção ativa · assinaturas de 09/11/2026 (1 dias)"


@pytest.mark.parametrize(
    ("atualizado", "status"),
    [("2026-11-07T12:00:00", Status.OK), ("2026-11-07T11:00:00", Status.WARN)],
)
def test_assinaturas_com_mais_de_3_dias_deixam_amarelo(atualizado, status):
    """Dadas assinaturas com exatamente 3 dias ou um pouco mais, então 🟢 ou 🟡."""
    assert defender(atualizado).status is status


@pytest.mark.parametrize(
    ("antivirus", "tempo_real", "desligado"),
    [(False, True, "antivírus"), (True, False, "proteção em tempo real")],
)
def test_defender_desligado_fica_vermelho(antivirus, tempo_real, desligado):
    """Dado o antivírus ou o tempo real desligado, então 🔴, citando o que está desligado."""
    resultado = defender(antivirus=antivirus, tempo_real=tempo_real)

    assert resultado.status is Status.PROBLEM
    assert resultado.summary.startswith(f"desligado: {desligado}")


# --- criptografia ------------------------------------------------------------------


def test_criptografia_exige_administrador():
    """Dado o winzel sem elevação, então a checagem de criptografia fica ⚪ pulada."""
    ctx = make_context({}, is_admin=False)

    (resultado,) = run_checks([EncryptionCheck()], ctx)

    assert resultado.status is Status.SKIPPED
    assert ctx.powershell.calls == []


def test_disco_criptografado_fica_verde():
    """Dado o C: com proteção ativada e 100% criptografado, então 🟢."""
    resposta = {"ProtectionStatus": 1, "EncryptionPercentage": 100}

    resultado = EncryptionCheck().run(make_context({"encryption": resposta}, is_admin=True))

    assert (resultado.status, resultado.summary) == (
        Status.OK,
        "C: proteção ativada (100% criptografado)",
    )


def test_disco_sem_criptografia_fica_amarelo():
    """Dado o C: com proteção desativada, então 🟡."""
    resposta = {"ProtectionStatus": 0, "EncryptionPercentage": 0}

    resultado = EncryptionCheck().run(make_context({"encryption": resposta}, is_admin=True))

    assert resultado.status is Status.WARN
    assert resultado.summary.startswith("C: proteção desativada")


def test_volume_nao_criptografavel_fica_amarelo():
    """Dado que o C: não aparece como volume criptografável, então 🟡 com a explicação."""
    resultado = EncryptionCheck().run(make_context({"encryption": None}, is_admin=True))

    assert (resultado.status, resultado.summary) == (
        Status.WARN,
        "C: não aparece como volume criptografável",
    )
