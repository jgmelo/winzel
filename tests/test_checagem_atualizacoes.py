"""Atualizações: pacotes do winget e Windows Update (SPEC 5.3)."""

import pytest
from tests.fakes import make_context

from winzel.checks.windows_update import WindowsUpdateCheck
from winzel.checks.winget_updates import WingetUpdatesCheck, parse_updates
from winzel.models import Status

pytestmark = [pytest.mark.fase5, pytest.mark.atualizacoes]


def pacote(pid, nome, de, para):
    return {"Id": pid, "Name": nome, "Installed": de, "Available": para, "Source": "winget"}


PACOTES = {
    "packages": [
        pacote("Git.Git", "Git", "2.47.0", "2.48.1"),
        pacote("Obsidian.Obsidian", "Obsidian", "1.7.4", "1.7.7"),
    ]
}


def test_pacotes_com_atualizacao_aparecem_com_versao_instalada_e_disponivel():
    """Dados Git e Obsidian com atualização, então cada um vira um item "instalada → disponível"."""
    itens = parse_updates(PACOTES)

    assert [(i.key, i.version) for i in itens] == [
        ("Git.Git", "2.47.0 → 2.48.1"),
        ("Obsidian.Obsidian", "1.7.4 → 1.7.7"),
    ]


def test_com_atualizacoes_no_winget_fica_amarelo_e_lista_no_resumo():
    """Dadas duas atualizações, então a checagem fica 🟡 e o resumo cita os pacotes."""
    resultado = WingetUpdatesCheck().run(make_context({"winget_updates": PACOTES}))

    assert resultado.status is Status.WARN
    assert resultado.summary == ("2 atualizações: Git (2.47.0 → 2.48.1), Obsidian (1.7.4 → 1.7.7)")
    assert resultado.metrics[0].value == 2


def test_resumo_mostra_tres_pacotes_e_conta_os_demais():
    """Dadas cinco atualizações, então o resumo cita três e diz "e mais 2"."""
    muitos = {"packages": [pacote(f"P.{n}", f"P{n}", "1", "2") for n in range(5)]}

    resultado = WingetUpdatesCheck().run(make_context({"winget_updates": muitos}))

    assert resultado.summary.endswith("e mais 2")


def test_sem_atualizacoes_no_winget_fica_verde():
    """Dado nenhum pacote com atualização, então a checagem fica 🟢."""
    resultado = WingetUpdatesCheck().run(make_context({"winget_updates": {"packages": []}}))

    assert (resultado.status, resultado.summary) == (Status.OK, "nenhuma atualização pendente")


def test_sem_o_modulo_do_winget_fica_indisponivel_e_explica_como_instalar():
    """Dado o módulo Microsoft.WinGet.Client ausente, então a checagem fica ⚪ com a instrução."""
    resultado = WingetUpdatesCheck().run(make_context({"winget_updates": {"module_missing": True}}))

    assert resultado.status is Status.SKIPPED
    assert "Install-Module Microsoft.WinGet.Client -Scope CurrentUser" in resultado.summary


# --- Windows Update ---------------------------------------------------------------

PENDENTES = [
    {"Title": "Atualização cumulativa 2026-11 (KB5050001)", "KB": "KB5050001", "Severity": ""},
    {"Title": "Atualização de definições do Defender", "KB": "KB2267602", "Severity": ""},
]


def test_atualizacoes_pendentes_do_windows_deixam_amarelo():
    """Dadas duas atualizações pendentes, então a checagem fica 🟡 e cita a primeira."""
    resultado = WindowsUpdateCheck().run(make_context({"windows_update": PENDENTES}))

    assert resultado.status is Status.WARN
    assert resultado.summary == "2 pendentes: Atualização cumulativa 2026-11 (KB5050001) e mais 1"
    assert [i.key for i in resultado.items] == ["KB5050001", "KB2267602"]


def test_sem_atualizacoes_pendentes_do_windows_fica_verde():
    """Dada a busca sem resultados, então a checagem fica 🟢."""
    resultado = WindowsUpdateCheck().run(make_context({"windows_update": None}))

    assert (resultado.status, resultado.summary) == (Status.OK, "nenhuma atualização pendente")


def test_busca_do_windows_update_tem_timeout_proprio_maior():
    """Dada a busca lenta do Windows Update, então o timeout padrão é de 120 s."""
    ctx = make_context({"windows_update": []})

    WindowsUpdateCheck().run(ctx)

    assert ctx.powershell.calls[0]["timeout_s"] == 120
