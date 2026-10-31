"""Diferenças nas categorias da fase 2, e as regras próprias de status e de elevação.

Os snapshots usam todas as checagens com os fakes; cada teste muda os dados de
exemplo entre a linha de base e o snapshot seguinte.
"""

import copy
import json

import pytest
from tests.fakes import FixedClock, all_responses, make_context, ok

from winzel.checks import all_checks
from winzel.diff import ChangeKind
from winzel.models import Status
from winzel.snapshot import take_snapshot

pytestmark = [pytest.mark.fase2, pytest.mark.diff]


class Maquina:
    """Uma máquina falsa com todas as checagens; o estado pode mudar entre snapshots."""

    def __init__(self, banco):
        self.banco = banco
        self.clock = FixedClock()
        self.respostas = all_responses()
        self.is_admin = False

    def dados(self, label):
        self.respostas[label] = copy.deepcopy(self.respostas[label])
        return self.respostas[label]

    def snapshot(self):
        ctx = make_context(dict(self.respostas), clock=self.clock, is_admin=self.is_admin)
        report = take_snapshot(self.banco, ctx, all_checks(), "auto")
        self.clock.advance(days=1)
        return {o.check_id: o for o in report.outcomes}


def mudancas(outcome):
    return [(c.kind, c.key, c.old_version, c.new_version) for c in outcome.changes]


def test_todas_as_categorias_do_inventario_viram_linha_de_base_no_primeiro_snapshot(banco):
    """Dado o 1º snapshot com as 7 checagens, então todas registram a linha de base sem erro."""
    resultados = Maquina(banco).snapshot()

    assert list(resultados) == [
        "programs",
        "store_apps",
        "startup",
        "scheduled_tasks",
        "services",
        "pip_global",
        "wsl_distros",
    ]
    assert all(o.is_baseline for o in resultados.values())
    assert all(o.status is Status.OK for o in resultados.values())


def test_app_da_store_atualizado_aparece_como_alterado(banco):
    """Dado o Terminal atualizado, então ele aparece 🔄 com as duas versões."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.dados("store_apps")[0]["Version"] = "1.22.100.0"

    resultado = maquina.snapshot()["store_apps"]

    assert mudancas(resultado) == [
        (ChangeKind.CHANGED, "Microsoft.WindowsTerminal", "1.21.2911.0", "1.22.100.0")
    ]


def test_tarefa_que_passa_de_em_execucao_para_pronta_nao_gera_mudanca(banco):
    """Dado o Firefox Background Update de Running para Ready, então nada muda."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.dados("scheduled_tasks")[2]["State"] = "Ready"

    assert maquina.snapshot()["scheduled_tasks"].changes == []


def test_tarefa_desabilitada_aparece_como_alterada(banco):
    """Dada a tarefa do OneDrive desabilitada, então ela aparece 🔄 habilitada → desabilitada."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.dados("scheduled_tasks")[0]["State"] = "Disabled"

    (mudanca,) = maquina.snapshot()["scheduled_tasks"].changes

    assert mudanca.old_version.startswith("habilitada:")
    assert mudanca.new_version.startswith("desabilitada:")


def test_tarefa_nova_aparece_como_adicionada(banco):
    """Dada uma tarefa nova fora de \\Microsoft\\, então ela aparece ➕ e a categoria fica 🟡."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.dados("scheduled_tasks").append(
        {
            "TaskPath": "\\",
            "TaskName": "Atualizador",
            "State": "Ready",
            "Actions": [{"Execute": "C:\\X\\up.exe", "Arguments": None, "ClassId": None}],
        }
    )

    resultado = maquina.snapshot()["scheduled_tasks"]

    assert [(c.kind, c.key) for c in resultado.changes] == [(ChangeKind.ADDED, "\\|Atualizador")]
    assert resultado.status is Status.WARN


def test_servico_que_muda_de_manual_para_automatico_aparece_como_alterado(banco):
    """Dado o Steam de manual para automático, então ele aparece 🔄; parar/iniciar não conta."""
    maquina = Maquina(banco)
    maquina.snapshot()
    steam = maquina.dados("services")[4]
    steam["StartMode"] = "Auto"
    steam["State"] = "Running"

    (mudanca,) = maquina.snapshot()["services"].changes

    assert (mudanca.kind, mudanca.key) == (ChangeKind.CHANGED, "steam client service")
    assert mudanca.old_version.startswith("manual:")
    assert mudanca.new_version.startswith("automático:")


def test_servico_removido_aparece_como_removido(banco):
    """Dado o Docker desinstalado, então o serviço dele aparece ➖."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.respostas["services"] = [
        s for s in maquina.dados("services") if s["Name"] != "com.docker.service"
    ]

    resultado = maquina.snapshot()["services"]

    assert [(c.kind, c.key) for c in resultado.changes] == [
        (ChangeKind.REMOVED, "com.docker.service")
    ]


def test_distro_nova_no_wsl_aparece_como_adicionada(banco):
    """Dada uma distro instalada após a linha de base, então ela aparece ➕."""
    maquina = Maquina(banco)
    maquina.snapshot()
    texto = "NAME STATE VERSION\n* Ubuntu-24.04 Running 2\n  docker-desktop Stopped 2\n"
    texto += "  Debian Stopped 1\n  kali-linux Stopped 2\n"
    maquina.respostas["wsl_distros"] = ok(texto.replace("\n", "\r\n").encode("utf-16-le"))

    resultado = maquina.snapshot()["wsl_distros"]

    assert mudancas(resultado) == [(ChangeKind.ADDED, "kali-linux", None, "2")]


def test_pacote_instalado_no_python_global_aparece_e_deixa_amarelo(banco):
    """Dado `pip install requests` no Python global, então ele aparece ➕ e a categoria fica 🟡."""
    maquina = Maquina(banco)
    maquina.snapshot()
    pacotes = [{"name": "pip", "version": "25.2"}, {"name": "requests", "version": "2.32.3"}]
    maquina.respostas["pip_global:list"] = ok(json.dumps(pacotes))

    resultado = maquina.snapshot()["pip_global"]

    assert mudancas(resultado) == [(ChangeKind.ADDED, "requests", None, "2.32.3")]
    assert resultado.status is Status.WARN


def test_pacote_extra_no_python_global_deixa_amarelo_mesmo_na_linha_de_base(banco):
    """Dado um pacote extra já na linha de base, então pip_global fica 🟡 sem nenhuma mudança."""
    maquina = Maquina(banco)
    pacotes = [{"name": "pip", "version": "25.2"}, {"name": "black", "version": "24.10.0"}]
    maquina.respostas["pip_global:list"] = ok(json.dumps(pacotes))
    maquina.snapshot()

    resultado = maquina.snapshot()["pip_global"]

    assert resultado.changes == []
    assert resultado.status is Status.WARN


def test_atualizar_o_pip_no_python_global_e_so_informativo(banco):
    """Dado o pip atualizado no Python global, então há 🔄, mas a categoria continua 🟢."""
    maquina = Maquina(banco)
    maquina.snapshot()
    maquina.respostas["pip_global:list"] = ok(json.dumps([{"name": "pip", "version": "25.3"}]))

    resultado = maquina.snapshot()["pip_global"]

    assert mudancas(resultado) == [(ChangeKind.CHANGED, "pip", "25.2", "25.3")]
    assert resultado.status is Status.OK


# --- tarefas agendadas e elevação (decisão 2b) ----------------------------------


def test_tarefas_nao_sao_comparadas_com_linha_de_base_de_outra_elevacao(banco):
    """Dada a linha de base com admin e um snapshot sem admin, então as tarefas ficam ⚪."""
    maquina = Maquina(banco)
    maquina.is_admin = True
    maquina.snapshot()
    maquina.is_admin = False
    maquina.respostas["scheduled_tasks"] = maquina.dados("scheduled_tasks")[:2]

    resultado = maquina.snapshot()["scheduled_tasks"]

    assert resultado.status is Status.SKIPPED
    assert resultado.changes == []
    assert "não comparada: linha de base feita com admin, este snapshot sem admin" in (
        resultado.result.summary
    )


def test_tarefas_voltam_a_ser_comparadas_com_a_mesma_elevacao_da_linha_de_base(banco):
    """Dada a linha de base com admin, um snapshot sem admin e outro com, então o 3º compara."""
    maquina = Maquina(banco)
    maquina.is_admin = True
    maquina.snapshot()
    maquina.is_admin = False
    maquina.snapshot()
    maquina.is_admin = True
    maquina.dados("scheduled_tasks")[0]["State"] = "Disabled"

    resultado = maquina.snapshot()["scheduled_tasks"]

    assert resultado.comparable
    assert resultado.reference.id == 1
    assert [c.kind for c in resultado.changes] == [ChangeKind.CHANGED]


def test_regra_de_elevacao_vale_so_para_tarefas_agendadas(banco):
    """Dada a linha de base com admin e um snapshot sem admin, então os serviços são comparados."""
    maquina = Maquina(banco)
    maquina.is_admin = True
    maquina.snapshot()
    maquina.is_admin = False

    resultados = maquina.snapshot()

    assert resultados["services"].comparable
    assert resultados["services"].status is Status.OK
