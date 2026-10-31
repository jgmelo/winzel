"""Aprovações: mudanças esperadas saem da contagem de alertas (SPEC 6.2)."""

import copy
from datetime import datetime

import pytest
from tests.fakes import FixedClock, make_context, sample

from winzel.checks import get_check
from winzel.cli import format_report
from winzel.diff import Change, ChangeKind, apply_approvals
from winzel.models import Status
from winzel.reference import Reference
from winzel.snapshot import compare_snapshot, take_snapshot
from winzel.store import Approval

pytestmark = [pytest.mark.fase3, pytest.mark.aprovacoes]

CHECKS = [get_check("programs")]
AGORA = datetime(2026, 11, 5, 9, 0, 0)
OBSIDIAN = "obsidian|x"


def programa(nome, versao="1.0"):
    return {"Source": "HKLM64", "DisplayName": nome, "DisplayVersion": versao, "Publisher": "X"}


class Maquina:
    def __init__(self, banco):
        self.banco = banco
        self.clock = FixedClock()
        self.programas = copy.deepcopy(sample("programs"))

    def instalar(self, nome, versao="1.0"):
        self.desinstalar(nome)
        self.programas.append(programa(nome, versao))

    def desinstalar(self, nome):
        self.programas = [p for p in self.programas if p["DisplayName"] != nome]

    def snapshot(self, referencia=None):
        ctx = make_context({"programs": self.programas}, clock=self.clock)
        report = take_snapshot(self.banco, ctx, CHECKS, "auto", reference=referencia)
        self.clock.advance(days=1)
        return report.outcomes[0], report


def aprovar(banco, key, change, motivo=""):
    banco.approve("programs", key, change, motivo, AGORA)


# --- regras puras ---------------------------------------------------------------


def mudanca(kind, key="k"):
    return Change(kind, "programs", key, key, None, None)


def aprovacao(change, key="k"):
    return {("programs", key, change): Approval("programs", key, change, AGORA, "esperado")}


def test_aprovacao_vale_para_item_e_tipo_de_mudanca():
    """Dado "k" aprovado como adicionado, então só a mudança ➕ de "k" fica aprovada."""
    mudancas = [mudanca(ChangeKind.ADDED), mudanca(ChangeKind.ADDED, "outro")]

    marcadas = apply_approvals(mudancas, aprovacao("added"))

    assert [m.approved for m in marcadas] == [True, False]
    assert marcadas[0].approval_reason == "esperado"


def test_aprovado_como_adicionado_e_depois_removido_e_mudanca_nova_nao_aprovada():
    """Dado "k" aprovado como adicionado, quando é removido, então a remoção não está aprovada."""
    (marcada,) = apply_approvals([mudanca(ChangeKind.REMOVED)], aprovacao("added"))

    assert marcada.approved is False
    assert marcada.affects_status is True


def test_mudanca_aprovada_nao_afeta_o_status():
    """Dada uma mudança ➕ aprovada, então ela não conta para o status do inventário."""
    (marcada,) = apply_approvals([mudanca(ChangeKind.ADDED)], aprovacao("added"))

    assert marcada.affects_status is False


def test_alterado_nao_e_aprovavel():
    """Dada uma mudança 🔄 (versão), então ela não é aprovável: é só informativa."""
    assert mudanca(ChangeKind.CHANGED).approvable is False


def test_banco_recusa_aprovar_mudanca_de_versao(banco):
    """Dado o tipo "changed", quando tento aprovar no banco, então ele recusa."""
    with pytest.raises(ValueError, match="só mudanças"):
        banco.approve("programs", "k", "changed", "", AGORA)


# --- no fluxo de snapshots ------------------------------------------------------


def test_programa_novo_aprovado_deixa_a_categoria_verde_e_continua_listado(banco):
    """Dado o Obsidian novo e aprovado, então programs fica 🟢 e a mudança aparece aprovada."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    aprovar(banco, OBSIDIAN, "added", "uso diário")

    programas, _ = maquina.snapshot()

    (mudanca_,) = programas.changes
    assert (mudanca_.kind, mudanca_.approved, mudanca_.approval_reason) == (
        ChangeKind.ADDED,
        True,
        "uso diário",
    )
    assert programas.status is Status.OK
    assert "1 novo (1 aprovado) desde a linha de base" in programas.result.summary


def test_aprovacao_vale_em_qualquer_versao(banco):
    """Dado o Obsidian aprovado como novo, quando ele é atualizado, então continua aprovado."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian", "1.0")
    aprovar(banco, OBSIDIAN, "added")
    maquina.instalar("Obsidian", "2.0")

    programas, _ = maquina.snapshot()

    assert programas.changes[0].approved
    assert programas.changes[0].new_version == "2.0"


def test_aprovado_como_novo_e_depois_desinstalado_volta_a_alertar(banco):
    """Dado o Obsidian aprovado como novo, quando some após um milestone que o tinha, então 🟡."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    aprovar(banco, OBSIDIAN, "added")
    _, segundo = maquina.snapshot()
    marco = banco.create_milestone(segundo.snapshot.id, "com-obsidian", "", AGORA)
    maquina.desinstalar("Obsidian")

    programas, _ = maquina.snapshot(Reference.of_milestone(marco))

    (removido,) = programas.changes
    assert (removido.kind, removido.approved) == (ChangeKind.REMOVED, False)
    assert programas.status is Status.WARN


def test_aprovacao_vale_para_qualquer_referencia(banco):
    """Dado o Obsidian aprovado, então ele aparece aprovado também contra o último snapshot."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    aprovar(banco, OBSIDIAN, "added")

    programas, _ = maquina.snapshot(Reference.previous())

    assert programas.changes[0].approved


def test_status_considera_so_mudancas_pendentes(banco):
    """Dados dois programas novos e só um aprovado, então programs continua 🟡."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    maquina.instalar("Zotero")
    aprovar(banco, OBSIDIAN, "added")

    programas, _ = maquina.snapshot()

    assert programas.status is Status.WARN
    assert [c.name for c in programas.pending] == ["Zotero"]
    assert "2 novos (1 aprovado)" in programas.result.summary


def test_revogar_aprovacao_volta_a_alertar(banco):
    """Dado o Obsidian aprovado, quando revogo, então ele volta a ser pendente (🟡)."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    aprovar(banco, OBSIDIAN, "added")
    _, report = maquina.snapshot()

    banco.revoke("programs", OBSIDIAN, "added")

    recomparado = compare_snapshot(banco, CHECKS, report.snapshot, report.reference)
    assert recomparado.outcomes[0].status is Status.WARN
    assert banco.approvals() == {}


def test_aprovar_de_novo_atualiza_o_motivo(banco):
    """Dado um item aprovado, quando aprovo de novo com outro motivo, então fica o motivo novo."""
    aprovar(banco, OBSIDIAN, "added", "primeiro")
    aprovar(banco, OBSIDIAN, "added", "segundo")

    (unica,) = banco.approvals().values()
    assert unica.reason == "segundo"


def test_resumo_sem_interface_marca_mudancas_aprovadas(banco):
    """Dado o Obsidian aprovado, então o resumo do `winzel snapshot` o marca com ✔ aprovado."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.instalar("Obsidian")
    aprovar(banco, OBSIDIAN, "added")

    _, report = maquina.snapshot()

    texto = format_report(report)
    assert "  ➕ Programas: Obsidian  1.0  ✔ aprovado" in texto
    assert "[aprovado]" in format_report(report, emoji=False)
