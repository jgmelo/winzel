"""Banco SQLite: esquema versionado, migrações e gravação de snapshots."""

import sqlite3
from datetime import datetime

import pytest

from winzel.models import CheckResult, Item, Metric, Status
from winzel.store import Store
from winzel.store.db import connect, migrate, migrations, schema_version

pytestmark = [pytest.mark.fase1, pytest.mark.banco]

MOMENTO = datetime(2026, 10, 31, 14, 30, 0)


def resultado(check_id="programs", status=Status.OK, itens=()):
    return CheckResult(
        check_id=check_id,
        status=status,
        summary="resumo",
        items=[Item(check_id, k, v, {"name": k.upper()}) for k, v in itens],
        duration_ms=12,
    )


def test_banco_novo_e_migrado_ate_a_ultima_versao_do_esquema(banco):
    """Dado um banco vazio, quando abro, então PRAGMA user_version é a última migração."""
    assert schema_version(banco.conn) == migrations()[-1][0]


def test_migracao_0001_cria_as_tabelas_da_spec(banco):
    """Dado o esquema inicial, então existem as seis tabelas da SPEC (seção 6.1)."""
    tabelas = {
        r[0] for r in banco.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    assert {"snapshots", "check_runs", "items", "metrics", "milestones", "approvals"} <= tabelas


def test_migracoes_sao_numeradas_em_sequencia_sem_lacunas():
    """Dadas as migrações do pacote, então os números são 1, 2, 3… sem lacunas."""
    numeros = [n for n, _ in migrations()]

    assert numeros == list(range(1, len(numeros) + 1))


def test_reabrir_o_banco_nao_reaplica_migracoes_e_preserva_os_dados(tmp_path):
    """Dado um banco com um snapshot, quando reabro, então o snapshot continua lá."""
    caminho = tmp_path / "winzel.db"
    store = Store.open(caminho)
    store.save_snapshot(MOMENTO, "auto", False, [resultado(itens=[("a", "1")])])
    store.close()

    store = Store.open(caminho)

    assert len(store.snapshots()) == 1
    assert store.items(1, "programs")["a"].version == "1"
    store.close()


def test_migracao_a_partir_da_versao_anterior_preserva_os_dados():
    """Dado um banco na versão N-1 com dados, quando migro, então os dados são preservados."""
    conn = connect(":memory:")
    ultima = migrations()[-1][0]
    migrate(conn, target=ultima - 1)
    if ultima > 1:
        conn.execute(
            "INSERT INTO snapshots (created_at, kind, is_admin)"
            " VALUES ('2026-01-01T00:00:00', 'auto', 0)"
        )

    migrate(conn)

    assert schema_version(conn) == ultima
    if ultima > 1:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_snapshot_grava_checagens_itens_e_metricas(banco):
    """Dado um resultado com itens e métricas, quando gravo, então tudo é lido de volta."""
    r = resultado(itens=[("7-zip|igor pavlov", "24.08")])
    r.metrics = [Metric("disk_c_free_pct", 42.5, "%")]

    snapshot_id = banco.save_snapshot(MOMENTO, "manual", True, [r])

    info = banco.snapshot(snapshot_id)
    assert (info.created_at, info.kind, info.is_admin) == (MOMENTO, "manual", True)
    run = banco.check_runs(snapshot_id)["programs"]
    assert (run.status, run.summary, run.duration_ms) == (Status.OK, "resumo", 12)
    item = banco.items(snapshot_id, "programs")["7-zip|igor pavlov"]
    assert (item.version, item.details) == ("24.08", {"name": "7-ZIP|IGOR PAVLOV"})
    valor = banco.conn.execute("SELECT value FROM metrics").fetchone()[0]
    assert valor == 42.5


def test_snapshot_e_gravado_de_uma_vez_e_nada_fica_se_algo_falhar(banco):
    """Dado um erro no meio da gravação (chave duplicada), então nenhuma linha é gravada."""
    duplicado = resultado(itens=[("a", "1"), ("a", "2")])

    with pytest.raises(sqlite3.IntegrityError):
        banco.save_snapshot(MOMENTO, "auto", False, [resultado("startup"), duplicado])

    assert banco.snapshots() == []
    assert banco.conn.execute("SELECT COUNT(*) FROM check_runs").fetchone()[0] == 0


def test_tipo_de_snapshot_so_aceita_auto_ou_manual(banco):
    """Dado um tipo desconhecido, quando gravo, então o banco recusa."""
    with pytest.raises(sqlite3.IntegrityError):
        banco.save_snapshot(MOMENTO, "agendado", False, [])


def test_linha_de_base_e_o_primeiro_snapshot_em_que_a_checagem_rodou(banco):
    """Dado o 1º snapshot com erro em programs e o 2º ok, então a linha de base é o 2º."""
    banco.save_snapshot(MOMENTO, "auto", False, [resultado(status=Status.ERROR)])
    segundo = banco.save_snapshot(MOMENTO, "auto", False, [resultado()])
    banco.save_snapshot(MOMENTO, "auto", False, [resultado()])

    assert banco.baseline_for("programs").id == segundo


def test_checagem_pulada_tambem_nao_vira_linha_de_base(banco):
    """Dado o 1º snapshot com programs pulada, então ele não é a linha de base."""
    banco.save_snapshot(MOMENTO, "auto", False, [resultado(status=Status.SKIPPED)])

    assert banco.baseline_for("programs") is None


def test_linha_de_base_e_por_categoria(banco):
    """Dado programs ok e startup com erro no 1º snapshot, então cada uma tem sua linha de base."""
    primeiro = banco.save_snapshot(
        MOMENTO, "auto", False, [resultado("programs"), resultado("startup", Status.ERROR)]
    )
    segundo = banco.save_snapshot(
        MOMENTO, "auto", False, [resultado("programs"), resultado("startup")]
    )

    assert banco.baseline_for("programs").id == primeiro
    assert banco.baseline_for("startup").id == segundo


def test_ultimo_snapshot(banco):
    """Dados dois snapshots, então o último é o de maior id; sem snapshots, é None."""
    assert banco.latest_snapshot() is None
    banco.save_snapshot(MOMENTO, "auto", False, [])
    segundo = banco.save_snapshot(MOMENTO, "manual", False, [])

    assert banco.latest_snapshot().id == segundo
