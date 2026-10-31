"""Checagem `services`: serviços de terceiros (executável fora de C:\\Windows).

Os dados de exemplo (tests/data/services.json) imitam a saída de `Win32_Service`.
"""

import pytest
from tests.fakes import make_context, sample

from winzel.checks.services import ServicesCheck, executable_path, parse_services
from winzel.models import Status

pytestmark = [pytest.mark.fase2, pytest.mark.inventario]


def por_servico(itens):
    return {i.details["service"]: i for i in itens}


@pytest.mark.parametrize(
    ("linha_de_comando", "executavel"),
    [
        (
            '"C:\\Program Files (x86)\\Common Files\\Steam\\steamservice.exe" /RunAsService',
            "C:\\Program Files (x86)\\Common Files\\Steam\\steamservice.exe",
        ),
        (
            "C:\\Program Files\\Logitech\\LogiOptions\\LogiOptionsMgr.exe /service",
            "C:\\Program Files\\Logitech\\LogiOptions\\LogiOptionsMgr.exe",
        ),
        ("%SystemRoot%\\System32\\spoolsv.exe", "C:\\Windows\\System32\\spoolsv.exe"),
        ("\\SystemRoot\\System32\\svc.exe -x", "C:\\Windows\\System32\\svc.exe"),
        (
            "C:\\Program Files\\Docker\\Docker\\com.docker.service",
            "C:\\Program Files\\Docker\\Docker\\com.docker.service",
        ),
    ],
)
def test_executavel_e_extraido_sem_aspas_argumentos_ou_variaveis(linha_de_comando, executavel):
    """Dada a linha de comando do serviço, então obtenho só o caminho do executável."""
    assert executable_path(linha_de_comando) == executavel


def test_servicos_com_executavel_fora_de_c_windows_aparecem():
    """Dado o exemplo, então Steam, Docker, Logitech e Edge Update aparecem."""
    itens = por_servico(parse_services(sample("services")))

    assert sorted(itens) == [
        "LogiOptions",
        "Steam Client Service",
        "com.docker.service",
        "edgeupdate",
    ]


def test_servicos_em_c_windows_sao_ignorados_mesmo_com_variavel_ou_maiusculas():
    """Dados Spooler (%SystemRoot%) e wuauserv (C:\\WINDOWS), então nenhum dos dois aparece."""
    itens = por_servico(parse_services(sample("services")))

    assert "Spooler" not in itens
    assert "wuauserv" not in itens


def test_limitacao_servico_de_terceiro_em_system32_escapa_do_filtro():
    """Limitação conhecida: o serviço da NVIDIA fica dentro de C:\\Windows e não aparece."""
    assert "NVDisplay.ContainerLocalSystem" not in por_servico(parse_services(sample("services")))


def test_limitacao_servico_da_microsoft_fora_de_c_windows_aparece():
    """Limitação conhecida: o Edge Update (Microsoft) fica em Program Files e aparece."""
    item = por_servico(parse_services(sample("services")))["edgeupdate"]

    assert item.details["name"] == "Microsoft Edge Update Service (edgeupdate)"


def test_atributo_e_modo_de_inicio_e_executavel_sem_o_estado_atual():
    """Dado o Steam manual e parado, então o atributo é "manual: <executável>"."""
    item = por_servico(parse_services(sample("services")))["Steam Client Service"]

    assert item.version == "manual: C:\\Program Files (x86)\\Common Files\\Steam\\steamservice.exe"
    assert "Stopped" not in item.version


@pytest.mark.parametrize(
    ("servico", "modo"),
    [
        ("edgeupdate", "automático (atrasado)"),
        ("LogiOptions", "desativado"),
        ("com.docker.service", "manual"),
    ],
)
def test_modos_de_inicio_em_portugues_incluindo_automatico_atrasado(servico, modo):
    """Dados os modos Auto+atrasado, Disabled e Manual, então aparecem em português."""
    assert por_servico(parse_services(sample("services")))[servico].details["start_mode"] == modo


def test_servico_sem_caminho_e_ignorado():
    """Dado um serviço sem PathName, então ele não aparece (não dá para saber onde está)."""
    assert "FantasmaSemCaminho" not in por_servico(parse_services(sample("services")))


def test_chave_e_o_nome_do_servico_em_minusculas():
    """Dado o serviço "Steam Client Service", então a chave é "steam client service"."""
    assert por_servico(parse_services(sample("services")))["Steam Client Service"].key == (
        "steam client service"
    )


def test_checagem_resume_a_contagem_de_servicos():
    """Dado o exemplo, quando a checagem roda, então resume "4 serviços"."""
    ctx = make_context({"services": sample("services")})

    resultado = ServicesCheck().run(ctx)

    assert (resultado.status, resultado.summary) == (Status.OK, "4 serviços")
