"""Milestones: snapshots fixados e nomeados, e a comparação com a referência escolhida.

Usa as checagens `programs` e `startup` com o PowerShell falso; cada teste muda os
programas instalados entre um snapshot e outro.
"""

import copy
from datetime import datetime

import pytest
from tests.fakes import FixedClock, make_context, sample

from winzel.checks import get_check
from winzel.diff import ChangeKind
from winzel.models import Status
from winzel.reference import Reference, default_reference, reference_by_name
from winzel.snapshot import compare_snapshot, take_snapshot
from winzel.store import MilestoneError

pytestmark = [pytest.mark.fase3, pytest.mark.milestones]

CHECKS = [get_check("programs"), get_check("startup")]
AGORA = datetime(2026, 11, 5, 9, 0, 0)


def programa(nome, versao="1.0"):
    return {"Source": "HKLM64", "DisplayName": nome, "DisplayVersion": versao, "Publisher": "X"}


class Maquina:
    def __init__(self, banco):
        self.banco = banco
        self.clock = FixedClock()
        self.programas = copy.deepcopy(sample("programs"))
        self.erro_em_programas = False

    def instalar(self, nome, versao="1.0"):
        self.programas.append(programa(nome, versao))

    def snapshot(self, referencia=None, is_admin=False):
        respostas = {
            "programs": RuntimeError("falhou") if self.erro_em_programas else self.programas,
            "startup": sample("startup"),
        }
        ctx = make_context(respostas, clock=self.clock, is_admin=is_admin)
        report = take_snapshot(self.banco, ctx, CHECKS, "auto", reference=referencia)
        self.clock.advance(days=1)
        return report


def programas(report):
    return next(o for o in report.outcomes if o.check_id == "programs")


def nomes_novos(report):
    return [c.name for c in programas(report).changes if c.kind is ChangeKind.ADDED]


# --- criação e listagem ---------------------------------------------------------


def test_primeiro_snapshot_vira_o_milestone_linha_de_base(banco):
    """Dado um banco vazio, quando gravo o 1º snapshot, então existe o milestone linha-de-base."""
    report = Maquina(banco).snapshot()

    (marco,) = banco.milestones()
    assert (marco.name, marco.snapshot.id) == ("linha-de-base", report.snapshot.id)
    assert marco.note == "Registrado automaticamente: primeiro snapshot."


def test_linha_de_base_nao_e_recriada_nos_snapshots_seguintes(banco):
    """Dados três snapshots, então continua havendo um só milestone linha-de-base, no 1º."""
    maquina = Maquina(banco)
    for _ in range(3):
        maquina.snapshot()

    assert [(m.name, m.snapshot.id) for m in banco.milestones()] == [("linha-de-base", 1)]


def test_milestone_fixa_um_snapshot_com_nome_e_nota(banco):
    """Dado um snapshot, quando crio o milestone "antes-do-office", então ele guarda nome e nota."""
    maquina = Maquina(banco)
    maquina.snapshot()
    segundo = maquina.snapshot()

    marco = banco.create_milestone(segundo.snapshot.id, " antes-do-office ", " limpo ", AGORA)

    assert (marco.name, marco.note, marco.snapshot.id) == ("antes-do-office", "limpo", 2)
    assert marco.created_at == AGORA


def test_milestones_sao_listados_do_snapshot_mais_recente_para_o_mais_antigo(banco):
    """Dados milestones nos snapshots 1, 3 e 2, então a lista vem na ordem 3, 2, 1."""
    maquina = Maquina(banco)
    for _ in range(3):
        maquina.snapshot()
    banco.create_milestone(3, "tres", "", AGORA)
    banco.create_milestone(2, "dois", "", AGORA)

    assert [m.name for m in banco.milestones()] == ["tres", "dois", "linha-de-base"]


@pytest.mark.parametrize(
    ("nome", "erro"),
    [
        ("", "o nome do milestone é obrigatório"),
        ("   ", "o nome do milestone é obrigatório"),
        ("linha-de-base", "o nome linha-de-base é reservado"),
        ("LINHA-DE-BASE", "o nome linha-de-base é reservado"),
        ("Limpo", "já existe um milestone chamado Limpo"),
    ],
)
def test_nome_vazio_reservado_ou_repetido_e_recusado(banco, nome, erro):
    """Dado um nome vazio, reservado ou já usado (sem diferenciar maiúsculas), então é recusado."""
    Maquina(banco).snapshot()
    banco.create_milestone(1, "limpo", "", AGORA)

    with pytest.raises(MilestoneError, match=erro):
        banco.create_milestone(1, nome, "", AGORA)


def test_milestone_em_snapshot_inexistente_e_recusado(banco):
    """Dado um snapshot que não existe, quando crio o milestone, então ele é recusado."""
    with pytest.raises(MilestoneError, match="snapshot #42 não existe"):
        banco.create_milestone(42, "x", "", AGORA)


def test_milestone_pode_ser_apagado_exceto_a_linha_de_base(banco):
    """Dado o milestone "limpo", quando o apago, então some; a linha-de-base não pode."""
    Maquina(banco).snapshot()
    banco.create_milestone(1, "limpo", "", AGORA)

    banco.delete_milestone("LIMPO")

    assert [m.name for m in banco.milestones()] == ["linha-de-base"]
    with pytest.raises(MilestoneError, match="não pode ser apagado"):
        banco.delete_milestone("linha-de-base")


def test_apagar_milestone_inexistente_gera_erro(banco):
    """Dado um nome que não existe, quando apago, então MilestoneError explica."""
    with pytest.raises(MilestoneError, match="milestone fantasma não existe"):
        banco.delete_milestone("fantasma")


# --- referência ---------------------------------------------------------------


def test_referencia_padrao_e_o_milestone_mais_recente(banco):
    """Dado um milestone criado no 2º snapshot, então ele é a referência padrão do 3º."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    maquina.snapshot()
    banco.create_milestone(2, "com-obsidian", "", AGORA)
    maquina.instalar("Zotero")

    report = maquina.snapshot()

    assert report.reference_label == "milestone com-obsidian (01/11/2026 14:30)"
    assert nomes_novos(report) == ["Zotero"]
    assert programas(report).result.summary.endswith(
        "1 novo desde o milestone com-obsidian (01/11/2026 14:30)"
    )


def test_linha_de_base_continua_como_referencia_enquanto_nao_ha_outro_milestone(banco):
    """Dado só o milestone linha-de-base, então a comparação é com ele, como nas fases 1 e 2."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")

    report = maquina.snapshot()

    assert report.reference_label == "linha de base (31/10/2026 14:30)"
    assert "1 novo desde a linha de base (31/10/2026 14:30)" in programas(report).result.summary


def test_referencia_pode_ser_um_milestone_mais_antigo(banco):
    """Dados linha-de-base e "x" (mais novo), quando escolho a linha-de-base, comparo com ela."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    maquina.snapshot()
    banco.create_milestone(2, "x", "", AGORA)
    maquina.instalar("Zotero")

    report = maquina.snapshot(referencia=reference_by_name(banco, "linha-de-base"))

    assert nomes_novos(report) == ["Obsidian", "Zotero"]


def test_referencia_ultimo_snapshot_compara_com_o_anterior(banco):
    """Dada a referência "último snapshot", então só aparece o que mudou desde o anterior."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    maquina.snapshot()
    maquina.instalar("Zotero")

    report = maquina.snapshot(referencia=Reference.previous())

    assert report.reference_label == "último snapshot"
    assert nomes_novos(report) == ["Zotero"]
    assert "desde o último snapshot (01/11/2026 14:30)" in programas(report).result.summary


def test_ultimo_snapshot_pula_snapshots_em_que_a_categoria_falhou(banco):
    """Dado erro em programs no snapshot anterior, então "último snapshot" usa o anterior a ele."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.erro_em_programas = True
    maquina.snapshot()
    maquina.erro_em_programas = False
    maquina.instalar("Obsidian")

    report = maquina.snapshot(referencia=Reference.previous())

    assert programas(report).reference.id == 1
    assert nomes_novos(report) == ["Obsidian"]


def test_categoria_com_erro_no_milestone_usa_o_primeiro_snapshot_ok_depois_dele(banco):
    """Dado erro em programs no milestone, então a referência é o 1º snapshot OK depois dele."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.erro_em_programas = True
    maquina.snapshot()
    banco.create_milestone(2, "com-erro", "", AGORA)
    maquina.erro_em_programas = False
    maquina.snapshot()
    maquina.instalar("Obsidian")

    report = maquina.snapshot()

    assert programas(report).reference.id == 3
    assert nomes_novos(report) == ["Obsidian"]
    startup = next(o for o in report.outcomes if o.check_id == "startup")
    assert startup.reference.id == 2


def test_sem_snapshot_ok_desde_o_milestone_o_atual_vira_a_referencia(banco):
    """Dado erro em programs no milestone, então o snapshot seguinte é a primeira leitura válida."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.erro_em_programas = True
    maquina.snapshot()
    banco.create_milestone(2, "com-erro", "", AGORA)
    maquina.erro_em_programas = False

    report = maquina.snapshot()

    assert programas(report).changes == []
    assert programas(report).result.summary == (
        "6 programas — primeira leitura válida desde milestone com-erro (01/11/2026 14:30)"
    )


def test_trocar_a_referencia_recompara_o_snapshot_sem_rodar_as_checagens(banco):
    """Dado o 3º snapshot, quando troco para "último snapshot", então só o último novo aparece."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    maquina.snapshot()
    maquina.instalar("Zotero")
    terceiro = maquina.snapshot()

    report = compare_snapshot(banco, CHECKS, terceiro.snapshot, Reference.previous())

    assert nomes_novos(report) == ["Zotero"]
    assert programas(report).status is Status.WARN


def test_milestone_no_proprio_snapshot_nao_mostra_mudancas(banco):
    """Dado um milestone criado no snapshot exibido, quando comparo com ele, então nada mudou."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    segundo = maquina.snapshot()
    marco = banco.create_milestone(segundo.snapshot.id, "agora", "", AGORA)

    report = compare_snapshot(banco, CHECKS, segundo.snapshot, Reference.of_milestone(marco))

    assert report.changes == []
    assert programas(report).status is Status.OK
    assert "sem mudanças desde o milestone agora" in programas(report).result.summary


def test_recomparar_preserva_erro_da_checagem(banco):
    """Dado um snapshot com erro em programs, quando recomparo, então programs continua ❗."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.erro_em_programas = True
    segundo = maquina.snapshot()

    report = compare_snapshot(banco, CHECKS, segundo.snapshot, default_reference(banco))

    assert programas(report).status is Status.ERROR
    assert programas(report).result.summary == "erro: falhou"


def test_tarefas_com_milestone_de_outra_elevacao_ficam_nao_comparadas(banco):
    """Dado o milestone feito com admin e o snapshot sem, então as tarefas ficam ⚪ "referência"."""
    tarefas = get_check("scheduled_tasks")
    respostas = {"scheduled_tasks": sample("scheduled_tasks")}
    take_snapshot(banco, make_context(respostas, is_admin=False), [tarefas], "auto")
    take_snapshot(banco, make_context(respostas, is_admin=True), [tarefas], "auto")
    banco.create_milestone(2, "admin", "", AGORA)

    report = take_snapshot(banco, make_context(respostas, is_admin=False), [tarefas], "auto")

    (resultado,) = report.outcomes
    assert resultado.status is Status.SKIPPED
    assert "não comparada: referência feita com admin, este snapshot sem admin" in (
        resultado.result.summary
    )
