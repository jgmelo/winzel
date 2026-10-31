"""Checagem `scheduled_tasks`: tarefas agendadas de terceiros (fora de \\Microsoft\\).

Os dados de exemplo (tests/data/scheduled_tasks.json) imitam a saída de `Get-ScheduledTask`.
"""

import pytest
from tests.fakes import make_context, sample

from winzel.checks.scheduled_tasks import ScheduledTasksCheck, parse_scheduled_tasks
from winzel.models import Status

pytestmark = [pytest.mark.fase2, pytest.mark.inventario]


def por_tarefa(itens):
    return {i.details["task"]: i for i in itens}


def test_tarefas_fora_de_microsoft_aparecem_com_chave_caminho_e_nome():
    """Dado o exemplo, então as 5 tarefas de terceiros aparecem, com chave `caminho|nome`."""
    itens = parse_scheduled_tasks(sample("scheduled_tasks"))

    assert len(itens) == 5
    assert por_tarefa(itens)["Firefox Background Update"].key == (
        "\\Mozilla\\|Firefox Background Update"
    )


def test_tarefas_em_microsoft_sao_ignoradas():
    """Dada uma tarefa em \\Microsoft\\Windows\\Defrag\\, então ela não aparece."""
    assert "ScheduledDefrag" not in por_tarefa(parse_scheduled_tasks(sample("scheduled_tasks")))


def test_atributo_comparavel_e_estado_habilitada_e_as_acoes():
    """Dada a tarefa do Google desabilitada, então o atributo é "desabilitada: <ação>"."""
    item = por_tarefa(parse_scheduled_tasks(sample("scheduled_tasks")))[
        "GoogleUpdateTaskMachineCore"
    ]

    assert item.version == (
        "desabilitada: C:\\Program Files (x86)\\Google\\Update\\GoogleUpdate.exe /c"
    )


def test_tarefa_em_execucao_conta_como_habilitada():
    """Dada uma tarefa com State = Running, então ela conta como "habilitada"."""
    item = por_tarefa(parse_scheduled_tasks(sample("scheduled_tasks")))["Firefox Background Update"]

    assert item.version.startswith("habilitada: ")
    assert item.details["state"] == "Running"


def test_varias_acoes_sao_unidas_e_acao_com_um_so_objeto_e_aceita():
    """Dadas duas ações, então elas são unidas por ";"; uma ação como objeto também funciona."""
    itens = por_tarefa(parse_scheduled_tasks(sample("scheduled_tasks")))

    assert itens["Manutencao"].details["actions"] == (
        "C:\\Contoso\\limpa.exe /tmp; C:\\Contoso\\relata.exe"
    )
    assert itens["Firefox Background Update"].details["actions"].endswith("backgroundupdate")


def test_acao_com_handler_com_aparece_pelo_class_id():
    """Dada uma ação do tipo COM (sem executável), então ela aparece como "COM {ClassId}"."""
    item = por_tarefa(parse_scheduled_tasks(sample("scheduled_tasks")))["Gatilho COM"]

    assert item.details["actions"] == "COM {A0B1C2D3-0000-0000-0000-000000000000}"


def test_checagem_resume_total_e_desabilitadas():
    """Dado o exemplo, quando a checagem roda, então resume "5 tarefas (1 desabilitada)"."""
    ctx = make_context({"scheduled_tasks": sample("scheduled_tasks")})

    resultado = ScheduledTasksCheck().run(ctx)

    assert (resultado.status, resultado.summary) == (Status.OK, "5 tarefas (1 desabilitada)")


def test_checagem_so_e_comparada_com_linha_de_base_de_mesma_elevacao():
    """Dada a regra da SPEC, então a checagem declara que só compara com a mesma elevação."""
    assert ScheduledTasksCheck.same_elevation_only is True
