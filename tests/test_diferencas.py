"""Diferenças em relação à linha de base (SPEC, seções 4 e 6.2).

Os snapshots usam as checagens reais com o PowerShell falso; cada teste muda os
dados de exemplo entre um snapshot e outro.
"""

import copy

import pytest
from tests.fakes import FixedClock, make_context, sample

from winzel.checks import get_check
from winzel.diff import ChangeKind, diff_items
from winzel.models import Item, Status
from winzel.powershell import PowerShellTimeout
from winzel.snapshot import take_snapshot
from winzel.status import inventory_status

pytestmark = [pytest.mark.fase1, pytest.mark.diff]

CHECKS = [get_check("programs"), get_check("startup")]


def item(key, version="1", name=None):
    return Item("programs", key, version, {"name": name or key})


def programas(*extras, sem=()):
    """Exemplo de programas, com entradas extras e sem as de DisplayName em `sem`."""
    dados = [p for p in copy.deepcopy(sample("programs")) if p["DisplayName"] not in sem]
    return dados + list(extras)


def novo_programa(nome, versao="1.0", fabricante="Fulano"):
    return {
        "Source": "HKLM64",
        "DisplayName": nome,
        "DisplayVersion": versao,
        "Publisher": fabricante,
    }


class Maquina:
    """Uma máquina falsa: o estado do registro pode mudar entre snapshots."""

    def __init__(self, banco):
        self.banco = banco
        self.clock = FixedClock()
        self.respostas = {"programs": programas(), "startup": sample("startup")}

    def snapshot(self, kind="auto"):
        ctx = make_context(dict(self.respostas), clock=self.clock)
        report = take_snapshot(self.banco, ctx, CHECKS, kind)
        self.clock.advance(days=1)
        return report


def resultado(report, check_id):
    return next(o for o in report.outcomes if o.check_id == check_id)


# --- regras puras -------------------------------------------------------------


def test_chave_so_no_atual_e_adicionada_so_na_referencia_e_removida():
    """Dadas referência {a, b} e atual {b, c}, então c é adicionado e a é removido."""
    mudancas = diff_items({"a": item("a"), "b": item("b")}, {"b": item("b"), "c": item("c")})

    assert [(m.kind, m.key) for m in mudancas] == [
        (ChangeKind.ADDED, "c"),
        (ChangeKind.REMOVED, "a"),
    ]


def test_mesma_chave_com_versao_diferente_e_alterada():
    """Dado o item a na versão 1 e depois na 2, então ele aparece como alterado 1 → 2."""
    (mudanca,) = diff_items({"a": item("a", "1")}, {"a": item("a", "2")})

    assert (mudanca.kind, mudanca.old_version, mudanca.new_version) == (
        ChangeKind.CHANGED,
        "1",
        "2",
    )


def test_alterado_e_informativo_e_nao_afeta_o_status():
    """Dada só uma mudança de versão, então o status do inventário continua 🟢."""
    mudancas = diff_items({"a": item("a", "1")}, {"a": item("a", "2")})

    assert inventory_status(mudancas) is Status.OK


def test_adicionado_ou_removido_deixa_o_inventario_em_atencao():
    """Dado um item adicionado, então o status do inventário é 🟡."""
    mudancas = diff_items({}, {"a": item("a")})

    assert inventory_status(mudancas) is Status.WARN


def test_sem_diferencas_nao_ha_mudancas():
    """Dados conjuntos iguais, então não há mudanças."""
    assert diff_items({"a": item("a")}, {"a": item("a")}) == []


# --- linha de base ------------------------------------------------------------


def test_primeiro_snapshot_vira_a_linha_de_base(banco):
    """Dado um banco vazio, quando gravo o 1º snapshot, então ele vira a linha de base."""
    report = Maquina(banco).snapshot()

    programs = resultado(report, "programs")
    assert programs.is_baseline
    assert programs.changes == []
    assert programs.status is Status.OK
    assert programs.result.summary == "6 programas — linha de base registrada agora"


def test_snapshot_seguinte_sem_mudancas_fica_verde(banco):
    """Dados dois snapshots iguais, então o 2º mostra "sem mudanças desde a linha de base"."""
    maquina = Maquina(banco)
    base = maquina.snapshot()

    report = maquina.snapshot()

    programs = resultado(report, "programs")
    assert programs.reference.id == base.snapshot.id
    assert programs.status is Status.OK
    assert programs.result.summary == (
        "6 programas — sem mudanças desde a linha de base (31/10/2026 14:30)"
    )


def test_programa_novo_aparece_como_adicionado_desde_a_linha_de_base(banco):
    """Dado um programa instalado após a linha de base, então ele aparece como ➕ e fica 🟡."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.respostas["programs"] = programas(novo_programa("Obsidian", "1.7.4", "Obsidian"))

    report = maquina.snapshot()

    programs = resultado(report, "programs")
    assert [(c.kind, c.name, c.new_version) for c in programs.changes] == [
        (ChangeKind.ADDED, "Obsidian", "1.7.4")
    ]
    assert programs.status is Status.WARN
    assert programs.result.summary.startswith("7 programas — 1 novo desde a linha de base")


def test_programa_desinstalado_aparece_como_removido(banco):
    """Dado o 7-Zip desinstalado após a linha de base, então ele aparece como ➖."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.respostas["programs"] = programas(sem=["7-Zip 24.08 (x64)"])

    report = maquina.snapshot()

    (mudanca,) = resultado(report, "programs").changes
    assert (mudanca.kind, mudanca.name, mudanca.old_version) == (
        ChangeKind.REMOVED,
        "7-Zip 24.08 (x64)",
        "24.08",
    )


def test_atualizacao_com_versao_no_nome_aparece_como_alterado(banco):
    """Dado o Python 3.14.0 atualizado para 3.14.1, então há uma mudança 🔄, não ➖ + ➕."""
    maquina = Maquina(banco)
    maquina.snapshot()
    atualizado = novo_programa(
        "Python 3.14.1 (64-bit)", "3.14.1150.0", "Python Software Foundation"
    )
    maquina.respostas["programs"] = programas(atualizado, sem=["Python 3.14.0 (64-bit)"])

    report = maquina.snapshot()

    (mudanca,) = resultado(report, "programs").changes
    assert mudanca.kind is ChangeKind.CHANGED
    assert (mudanca.old_version, mudanca.new_version) == ("3.14.150.0", "3.14.1150.0")
    assert resultado(report, "programs").status is Status.OK


def test_item_de_inicializacao_desligado_aparece_como_alterado(banco):
    """Dado o OneDrive desligado após a linha de base, então aparece 🔄 ligado → desligado."""
    maquina = Maquina(banco)
    maquina.snapshot()
    startup = copy.deepcopy(sample("startup"))
    startup["approved"][0]["Flag"] = 3
    maquina.respostas["startup"] = startup

    report = maquina.snapshot()

    (mudanca,) = resultado(report, "startup").changes
    assert mudanca.kind is ChangeKind.CHANGED
    assert mudanca.old_version.startswith("ligado:")
    assert mudanca.new_version.startswith("desligado:")


def test_comparacao_e_sempre_com_a_linha_de_base_e_nao_com_o_ultimo_snapshot(banco):
    """Dado um programa instalado no 2º snapshot, então no 3º ele ainda aparece como novo."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.respostas["programs"] = programas(novo_programa("Obsidian"))
    maquina.snapshot()

    report = maquina.snapshot()

    assert [c.name for c in resultado(report, "programs").changes] == ["Obsidian"]


# --- checagens que falham -----------------------------------------------------


def test_checagem_com_erro_nao_e_comparada_e_seus_itens_nao_somem(banco):
    """Dado erro em programs no 2º snapshot, então nada aparece como removido: não há comparação."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.respostas["programs"] = RuntimeError("registro inacessível")

    report = maquina.snapshot()

    programs = resultado(report, "programs")
    assert programs.status is Status.ERROR
    assert programs.comparable is False
    assert programs.changes == []


def test_erro_numa_checagem_nao_afeta_a_comparacao_da_outra(banco):
    """Dado tempo esgotado em programs, então startup continua sendo comparada normalmente."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.respostas["programs"] = PowerShellTimeout("programs: tempo esgotado (30 s)")
    startup = copy.deepcopy(sample("startup"))
    startup["entries"].pop(0)
    maquina.respostas["startup"] = startup

    report = maquina.snapshot()

    assert resultado(report, "programs").status is Status.ERROR
    startup_r = resultado(report, "startup")
    assert [(c.kind, c.name) for c in startup_r.changes] == [(ChangeKind.REMOVED, "OneDrive")]


def test_linha_de_base_de_uma_categoria_com_erro_no_primeiro_snapshot_e_o_primeiro_ok(banco):
    """Dado erro em programs no 1º snapshot, então o 2º vira a linha de base de programs."""
    maquina = Maquina(banco)
    maquina.respostas["programs"] = RuntimeError("falhou")
    maquina.snapshot()
    maquina.respostas["programs"] = programas()

    report = maquina.snapshot()

    assert resultado(report, "programs").is_baseline
    assert resultado(report, "startup").reference.id == 1


# --- snapshot -----------------------------------------------------------------


def test_snapshot_registra_tipo_data_e_se_foi_feito_como_admin(banco):
    """Dado um snapshot manual sem admin, então o banco guarda kind, data e is_admin."""
    report = Maquina(banco).snapshot(kind="manual")

    info = banco.snapshot(report.snapshot.id)
    assert (info.kind, info.is_admin) == ("manual", False)
    assert info.created_at.isoformat() == "2026-10-31T14:30:00"


def test_status_e_resumo_gravados_sao_os_ja_comparados(banco):
    """Dado um programa novo, então o check_run gravado tem 🟡 e o resumo com a comparação."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.respostas["programs"] = programas(novo_programa("Obsidian"))

    report = maquina.snapshot()

    run = banco.check_runs(report.snapshot.id)["programs"]
    assert run.status is Status.WARN
    assert "1 novo desde a linha de base" in run.summary


def test_status_geral_e_o_pior_entre_as_checagens(banco):
    """Dado programs 🟡 e startup ❗, então o status geral é ❗ erro."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.respostas["programs"] = programas(novo_programa("Obsidian"))
    maquina.respostas["startup"] = RuntimeError("falhou")

    report = maquina.snapshot()

    assert report.overall_status is Status.ERROR
