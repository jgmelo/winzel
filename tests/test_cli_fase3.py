"""Linha de comando na fase 3: milestones e `snapshot --referencia`."""

import io

import pytest
from tests.fakes import FixedClock, make_context, sample

from winzel.cli import main

pytestmark = [pytest.mark.fase3, pytest.mark.milestones]


@pytest.fixture
def winzel(tmp_path):
    """Roda o `winzel` com banco em arquivo temporário e o PowerShell falso."""
    clock = FixedClock()

    def rodar(*args, resposta="s"):
        saida = io.StringIO()
        codigo = main(
            ["--db", str(tmp_path / "w.db"), "--config", str(tmp_path / "x.toml"), *args],
            context_factory=lambda config: make_context(
                {"programs": sample("programs"), "startup": sample("startup")},
                config=config,
                clock=clock,
            ),
            out=saida,
            ask=lambda pergunta: resposta,
        )
        clock.advance(days=1)
        return codigo, saida.getvalue()

    return rodar


def test_milestone_fixa_o_ultimo_snapshot(winzel):
    """Dados dois snapshots, quando rodo `winzel milestone limpo`, então ele fixa o 2º."""
    winzel("snapshot")
    winzel("snapshot")

    codigo, saida = winzel("milestone", "limpo", "--nota", "recém-formatado")

    assert codigo == 0
    assert saida.strip() == "Milestone limpo criado no snapshot #2 (01/11/2026 14:30)."


def test_milestone_sem_snapshot_gera_erro(winzel, capsys):
    """Dado um banco vazio, quando crio um milestone, então o winzel pede um snapshot antes."""
    codigo, _ = winzel("milestone", "limpo")

    assert codigo == 2
    assert "rode `winzel snapshot` antes" in capsys.readouterr().err


def test_milestone_com_nome_reservado_gera_erro(winzel, capsys):
    """Dado o nome linha-de-base, quando crio o milestone, então o winzel recusa."""
    winzel("snapshot")

    codigo, _ = winzel("milestone", "linha-de-base")

    assert codigo == 2
    assert "reservado" in capsys.readouterr().err


def test_milestones_lista_nome_snapshot_data_e_nota(winzel):
    """Dados dois milestones, quando rodo `winzel milestones`, então o mais novo vem antes."""
    winzel("snapshot")
    winzel("snapshot")
    winzel("milestone", "limpo", "--nota", "recém-formatado")

    _, saida = winzel("milestones")

    assert saida.splitlines() == [
        "limpo  snapshot #2 de 01/11/2026 14:30 — recém-formatado",
        "linha-de-base  snapshot #1 de 31/10/2026 14:30 — "
        "Registrado automaticamente: primeiro snapshot.",
    ]


def test_apagar_milestone_pede_confirmacao_e_apaga_com_sim(winzel):
    """Dado o milestone "limpo", quando confirmo com "s", então ele é apagado."""
    winzel("snapshot")
    winzel("milestone", "limpo")

    codigo, saida = winzel("milestone", "--apagar", "limpo", resposta="s")

    assert codigo == 0
    assert "Milestone limpo apagado." in saida
    assert "limpo" not in winzel("milestones")[1]


def test_apagar_milestone_sem_confirmar_nao_apaga(winzel):
    """Dado o milestone "limpo", quando respondo Enter (não), então nada é apagado."""
    winzel("snapshot")
    winzel("milestone", "limpo")

    codigo, saida = winzel("milestone", "--apagar", "limpo", resposta="")

    assert codigo == 1
    assert "Nada foi apagado." in saida
    assert "limpo" in winzel("milestones")[1]


def test_linha_de_base_nao_pode_ser_apagada_pela_linha_de_comando(winzel, capsys):
    """Dada a linha de base, quando tento apagá-la (mesmo confirmando), então o winzel recusa."""
    winzel("snapshot")

    codigo, _ = winzel("milestone", "--apagar", "linha-de-base", resposta="s")

    assert codigo == 2
    assert "não pode ser apagado" in capsys.readouterr().err


def test_snapshot_com_referencia_ultimo(winzel):
    """Dado `snapshot --referencia ultimo`, então o resumo compara com o snapshot anterior."""
    winzel("snapshot")

    _, saida = winzel("snapshot", "--referencia", "ultimo")

    assert "Referência: último snapshot" in saida
    assert "sem mudanças desde o último snapshot (31/10/2026 14:30)" in saida


def test_snapshot_com_referencia_desconhecida_gera_erro(winzel, capsys):
    """Dado um milestone que não existe, quando o uso como referência, então o winzel recusa."""
    winzel("snapshot")

    codigo, _ = winzel("snapshot", "--referencia", "fantasma")

    assert codigo == 2
    assert "referência desconhecida: fantasma" in capsys.readouterr().err
