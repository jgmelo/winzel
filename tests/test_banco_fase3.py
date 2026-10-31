"""Banco na fase 3: migração 0002 (dados das fases 1 e 2 preservados) e retenção (SPEC 6.3)."""

from datetime import datetime, timedelta

import pytest
from tests.fakes import FixedClock, make_context, sample

from winzel.checks import get_check
from winzel.models import CheckResult, Status
from winzel.snapshot import take_snapshot
from winzel.store import Store
from winzel.store.db import connect, migrate, schema_version

pytestmark = [pytest.mark.fase3, pytest.mark.banco]

AGORA = datetime(2026, 11, 5, 9, 0, 0)


# --- migração 0002 --------------------------------------------------------------


def banco_v1_com_dados():
    """Um banco como as fases 1 e 2 o deixaram: versão 1, com três snapshots."""
    conn = connect(":memory:")
    migrate(conn, target=1)
    linhas = [
        (1, "2026-10-31T14:30:00", "auto", 1),
        (2, "2026-11-01T10:00:00", "auto", 0),
        (3, "2026-11-02T10:00:00", "manual", 0),
    ]
    conn.executemany("INSERT INTO snapshots VALUES (?, ?, ?, ?)", linhas)
    runs = [
        (1, "programs", "ok", "6 programas — linha de base registrada agora", 10, None),
        (
            2,
            "programs",
            "warn",
            "7 programas — 1 novo desde a linha de base (31/10/2026 14:30)",
            10,
            None,
        ),
        (
            2,
            "startup",
            "error",
            "erro: startup: PowerShell falhou — Acesso negado",
            5,
            "startup: PowerShell falhou — Acesso negado",
        ),
        (
            2,
            "scheduled_tasks",
            "skipped",
            "5 tarefas — não comparada: linha de base feita com admin, este snapshot sem admin",
            8,
            None,
        ),
        (3, "ssd", "skipped", "pulada: requer administrador", 0, None),
    ]
    conn.executemany("INSERT INTO check_runs VALUES (?, ?, ?, ?, ?, ?)", runs)
    return conn


def runs(conn):
    return {
        (r["snapshot_id"], r["check_id"]): (r["raw_status"], r["raw_summary"])
        for r in conn.execute("SELECT * FROM check_runs")
    }


def test_migracao_0002_leva_o_banco_da_versao_1_para_a_2_preservando_os_snapshots():
    """Dado um banco v1 com três snapshots, quando migro, então a versão é 2 e os dados ficam."""
    conn = banco_v1_com_dados()

    migrate(conn)

    assert schema_version(conn) == 2
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM check_runs").fetchone()[0] == 5


def test_migracao_0002_cria_a_linha_de_base_no_primeiro_snapshot():
    """Dado um banco v1 com snapshots, quando migro, então a linha-de-base aponta para o #1."""
    conn = banco_v1_com_dados()

    migrate(conn)

    (linha,) = conn.execute("SELECT * FROM milestones").fetchall()
    assert (linha["snapshot_id"], linha["name"]) == (1, "linha-de-base")
    assert linha["created_at"] == "2026-10-31T14:30:00"


def test_migracao_0002_em_banco_vazio_nao_cria_milestone():
    """Dado um banco v1 sem snapshots, quando migro, então não há milestones."""
    conn = connect(":memory:")
    migrate(conn, target=1)

    migrate(conn)

    assert conn.execute("SELECT COUNT(*) FROM milestones").fetchone()[0] == 0


def test_migracao_0002_separa_o_resumo_proprio_da_checagem_do_resumo_comparado():
    """Dado o resumo "7 programas — 1 novo…", quando migro, então o próprio é "7 programas"."""
    conn = banco_v1_com_dados()

    migrate(conn)

    assert runs(conn)[(1, "programs")] == ("ok", "6 programas")
    assert runs(conn)[(2, "programs")] == ("ok", "7 programas")


def test_migracao_0002_mantem_falhas_como_falhas_com_a_mensagem_inteira():
    """Dados um erro e uma checagem pulada, quando migro, então continuam falhas, com a mensagem."""
    conn = banco_v1_com_dados()

    migrate(conn)

    assert runs(conn)[(2, "startup")] == (
        "error",
        "erro: startup: PowerShell falhou — Acesso negado",
    )
    assert runs(conn)[(3, "ssd")] == ("skipped", "pulada: requer administrador")


def test_migracao_0002_reconhece_tarefas_nao_comparadas_por_elevacao_como_coletadas():
    """Dadas tarefas ⚪ por elevação (fase 2), quando migro, então contam como coletadas."""
    conn = banco_v1_com_dados()

    migrate(conn)

    assert runs(conn)[(2, "scheduled_tasks")] == ("ok", "5 tarefas")


def test_nomes_de_milestone_sao_unicos_sem_diferenciar_maiusculas_no_proprio_banco(banco):
    """Dado "Limpo" gravado, quando insiro "LIMPO" direto no SQLite, então o índice recusa."""
    import sqlite3

    banco.save_snapshot(AGORA, "auto", False, [])
    banco.create_milestone(1, "Limpo", "", AGORA)

    with pytest.raises(sqlite3.IntegrityError):
        banco.conn.execute("INSERT INTO milestones VALUES (1, 'LIMPO', '', '2026-11-05T09:00:00')")


# --- retenção -------------------------------------------------------------------


def gravar(banco, quando, kind="auto", status=Status.OK):
    return banco.save_snapshot(quando, kind, False, [CheckResult("programs", status, "x")])


def existentes(banco):
    return [s.id for s in banco.snapshots()]


def test_snapshots_automaticos_antigos_ficam_reduzidos_ao_ultimo_de_cada_mes(banco):
    """Dados automáticos de junho e julho (> 90 dias), então fica o último de cada mês."""
    linha_de_base = gravar(banco, datetime(2026, 5, 1))
    junho = [gravar(banco, datetime(2026, 6, d)) for d in (2, 15, 28)]
    julho = [gravar(banco, datetime(2026, 7, d)) for d in (3, 20)]

    apagados = banco.apply_retention(AGORA, keep_all_days=90)

    assert apagados == junho[:2] + julho[:1]
    assert existentes(banco) == [linha_de_base, junho[2], julho[1]]


def test_snapshots_dos_ultimos_90_dias_sao_todos_mantidos(banco):
    """Dados snapshots diários nos últimos 90 dias, então nenhum é apagado."""
    for dias in range(1, 90):
        gravar(banco, AGORA - timedelta(days=dias))

    assert banco.apply_retention(AGORA, keep_all_days=90) == []


def test_snapshots_manuais_nunca_sao_apagados(banco):
    """Dados snapshots manuais antigos, então a retenção não os apaga."""
    gravar(banco, datetime(2026, 5, 1))
    manuais = [gravar(banco, datetime(2026, 6, d), kind="manual") for d in (2, 15)]

    banco.apply_retention(AGORA, keep_all_days=90)

    assert set(manuais) <= set(existentes(banco))


def test_snapshots_de_milestones_nunca_sao_apagados(banco):
    """Dado um milestone num snapshot automático antigo, então ele é mantido."""
    gravar(banco, datetime(2026, 5, 1))
    marcado = gravar(banco, datetime(2026, 6, 2))
    gravar(banco, datetime(2026, 6, 28))
    banco.create_milestone(marcado, "junho", "", AGORA)

    banco.apply_retention(AGORA, keep_all_days=90)

    assert marcado in existentes(banco)


def test_referencia_efetiva_de_um_milestone_e_preservada(banco):
    """Dado o milestone num snapshot com erro, então o 1º snapshot OK depois dele é mantido."""
    gravar(banco, datetime(2026, 5, 1))
    com_erro = gravar(banco, datetime(2026, 6, 2), status=Status.ERROR)
    referencia = gravar(banco, datetime(2026, 6, 3))
    gravar(banco, datetime(2026, 6, 28))
    banco.create_milestone(com_erro, "junho", "", AGORA)

    banco.apply_retention(AGORA, keep_all_days=90)

    assert {com_erro, referencia} <= set(existentes(banco))


def test_apagar_snapshot_apaga_seus_itens_e_checagens(banco):
    """Dado um snapshot apagado pela retenção, então seus itens e check_runs somem junto."""
    gravar(banco, datetime(2026, 5, 1))
    banco.save_snapshot(
        datetime(2026, 6, 2),
        "auto",
        False,
        [CheckResult("programs", Status.OK, "x", items=[])],
    )
    gravar(banco, datetime(2026, 6, 28))

    banco.apply_retention(AGORA, keep_all_days=90)

    assert (
        banco.conn.execute("SELECT COUNT(*) FROM check_runs WHERE snapshot_id = 2").fetchone()[0]
        == 0
    )


def test_retencao_roda_a_cada_snapshot_e_usa_o_config(banco):
    """Dado keep_all_days = 10 no config, quando gravo um snapshot, então a retenção roda."""
    clock = FixedClock(datetime(2026, 10, 1))
    config = {"retention": {"keep_all_days": 10}}
    for _ in range(3):
        take_snapshot(
            banco,
            make_context({"programs": sample("programs")}, clock=clock, config=config),
            [get_check("programs")],
            "auto",
        )
        clock.advance(days=1)
    clock.advance(days=30)

    report = take_snapshot(
        banco,
        make_context({"programs": sample("programs")}, clock=clock, config=config),
        [get_check("programs")],
        "auto",
    )

    assert report.pruned == [2]
    assert existentes(banco) == [1, 3, 4]


def test_banco_aberto_em_arquivo_da_fase_2_e_migrado_automaticamente(tmp_path):
    """Dado um arquivo winzel.db na versão 1, quando o winzel o abre, então ele é migrado."""
    caminho = tmp_path / "winzel.db"
    conn = connect(caminho)
    migrate(conn, target=1)
    conn.execute("INSERT INTO snapshots VALUES (1, '2026-10-31T14:30:00', 'auto', 0)")
    conn.close()

    store = Store.open(caminho)

    assert [m.name for m in store.milestones()] == ["linha-de-base"]
    store.close()
