"""Métricas de hardware: saúde da bateria e desgaste do SSD (SPEC 5.2)."""

from pathlib import Path

import pytest
from tests.fakes import FakeFileSystem, make_context, ok, sample

from winzel.checks.battery import REPORT_NAME, BatteryCheck, parse_battery_report
from winzel.checks.ssd import SsdCheck, parse_disks
from winzel.commands import CommandResult
from winzel.models import Status
from winzel.runner import run_checks

pytestmark = [pytest.mark.fase4, pytest.mark.hardware]

RELATORIO = (Path(__file__).parent / "data" / "battery_report.xml").read_text(encoding="utf-8")
CAMINHO = f"C:\\Temp\\{REPORT_NAME}"


def relatorio(design=75000, full=66000, ciclos="142"):
    return (
        RELATORIO.replace("<DesignCapacity>75000", f"<DesignCapacity>{design}")
        .replace("<FullChargeCapacity>66000", f"<FullChargeCapacity>{full}")
        .replace("<CycleCount>142", f"<CycleCount>{ciclos}")
    )


def bateria(xml=RELATORIO, resposta=None, config=None):
    fs = FakeFileSystem()
    fs.texts[CAMINHO] = xml
    ctx = make_context({"battery": resposta or ok()}, fs=fs, config=config)
    return BatteryCheck().run(ctx), ctx


# --- bateria --------------------------------------------------------------------


def test_relatorio_de_bateria_do_powercfg_e_lido():
    """Dado o XML do powercfg, então leio capacidade de projeto, atual e ciclos."""
    assert parse_battery_report(RELATORIO) == [{"design": 75000, "full": 66000, "cycles": 142}]


def test_saude_da_bateria_e_capacidade_atual_sobre_a_de_projeto():
    """Dados 66 de 75 Wh, então a saúde é 88% (🟢), com métricas e ciclos."""
    resultado, _ = bateria()

    assert resultado.status is Status.OK
    assert resultado.summary == "88% da capacidade de projeto (66,0 de 75,0 Wh) · 142 ciclos"
    nomes = {m.name: m.value for m in resultado.metrics}
    assert nomes == {
        "battery_health_pct": 88.0,
        "battery_full_mwh": 66000,
        "battery_design_mwh": 75000,
        "battery_cycles": 142,
    }


@pytest.mark.parametrize(
    ("full", "status"),
    [(60000, Status.OK), (59999, Status.WARN), (45000, Status.WARN), (44999, Status.PROBLEM)],
)
def test_limites_da_bateria_nas_fronteiras(full, status):
    """Dada a saúde em 80%, logo abaixo, 60% e logo abaixo, então 🟢, 🟡, 🟡 e 🔴."""
    resultado, _ = bateria(relatorio(full=full))

    assert resultado.status is status


def test_powercfg_grava_em_arquivo_temporario_que_e_apagado_depois():
    """Dado o relatório, então o powercfg escreve num arquivo temporário, apagado ao final."""
    _, ctx = bateria()

    (chamada,) = ctx.commands.calls
    assert chamada["args"] == ["powercfg", "/batteryreport", "/xml", "/output", CAMINHO]
    assert ctx.fs.removed == [CAMINHO]


def test_sem_bateria_fica_indisponivel():
    """Dado um relatório sem baterias (desktop), então a checagem fica ⚪."""
    sem = RELATORIO.split("<Batteries>")[0] + "<Batteries/></BatteryReport>"

    resultado, _ = bateria(sem)

    assert resultado.status is Status.SKIPPED
    assert resultado.summary == "indisponível: nenhuma bateria encontrada"


def test_falha_do_powercfg_vira_erro_sem_afetar_outras_checagens():
    """Dado o powercfg falhando, então a bateria fica ❗ com o motivo."""
    fs = FakeFileSystem()
    ctx = make_context({"battery": CommandResult(1, b"", b"Acesso negado.\r\n")}, fs=fs)

    (resultado,) = run_checks([BatteryCheck()], ctx)

    assert resultado.status is Status.ERROR
    assert resultado.error == "powercfg falhou: Acesso negado."


def test_ciclos_ausentes_nao_impedem_a_leitura():
    """Dado um relatório sem CycleCount, então a saúde é medida e o resumo não cita ciclos."""
    resultado, _ = bateria(relatorio(ciclos=""))

    assert "ciclos" not in resultado.summary


# --- SSD ------------------------------------------------------------------------


def test_ssd_exige_administrador_e_fica_pulado_sem_elevacao():
    """Dado o winzel sem admin, então a checagem do SSD fica ⚪ pulada, sem executar."""
    ctx = make_context({}, is_admin=False)

    (resultado,) = run_checks([SsdCheck()], ctx)

    assert resultado.status is Status.SKIPPED
    assert ctx.powershell.calls == []


def test_discos_virtuais_e_usb_sao_ignorados():
    """Dados um NVMe, o disco virtual do Dev Drive e um HD USB, então só o NVMe é considerado."""
    assert [d["name"] for d in parse_disks(sample("ssd"))] == ["Micron 2400 NVMe 1TB"]


def test_ssd_informa_desgaste_e_temperatura():
    """Dado o NVMe com 3% de desgaste e 41 °C, então a checagem fica 🟢 com as duas métricas."""
    resultado = SsdCheck().run(make_context({"ssd": sample("ssd")}, is_admin=True))

    assert resultado.status is Status.OK
    assert resultado.summary == "Micron 2400 NVMe 1TB: desgaste 3%, 41 °C"
    assert {m.name: m.value for m in resultado.metrics} == {
        "ssd_wear_pct": 3,
        "ssd_temperature_c": 41,
    }


@pytest.mark.parametrize(("desgaste", "status"), [(50, Status.OK), (51, Status.WARN)])
def test_limite_de_desgaste_do_ssd_na_fronteira(desgaste, status):
    """Dado o desgaste em exatamente 50% ou 51%, então 🟢 ou 🟡."""
    discos = [{"FriendlyName": "X", "MediaType": "SSD", "BusType": "NVMe", "Wear": desgaste}]

    resultado = SsdCheck().run(make_context({"ssd": discos}, is_admin=True))

    assert resultado.status is status


def test_com_varios_ssds_vale_o_pior_desgaste():
    """Dados dois SSDs com 10% e 60% de desgaste, então a métrica é 60% e a checagem fica 🟡."""
    discos = [
        {"FriendlyName": "A", "MediaType": "SSD", "BusType": "SATA", "Wear": 10},
        {"FriendlyName": "B", "MediaType": "SSD", "BusType": "NVMe", "Wear": 60},
    ]

    resultado = SsdCheck().run(make_context({"ssd": discos}, is_admin=True))

    assert resultado.status is Status.WARN
    assert resultado.metrics[0].value == 60


def test_ssd_sem_dados_de_desgaste_nem_temperatura_fica_indisponivel():
    """Dado um SSD que não informa desgaste nem temperatura, então a checagem fica ⚪."""
    discos = [{"FriendlyName": "X", "MediaType": "SSD", "BusType": "NVMe", "Wear": None}]

    resultado = SsdCheck().run(make_context({"ssd": discos}, is_admin=True))

    assert resultado.status is Status.SKIPPED
