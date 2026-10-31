"""Métricas de armazenamento: espaço no C:, Dev Drive, sandboxes e Temp (SPEC 5.2).

O acesso a disco passa pelo sistema de arquivos falso (tests/fakes.py).
"""

import pytest
from tests.fakes import FakeFileSystem, make_context

from winzel.checks.clutter import ClutterCheck
from winzel.checks.dev_drive import DevDriveCheck
from winzel.checks.disk_c import DiskCCheck
from winzel.filesystem import GB, DirSize, DiskUsage
from winzel.models import Status

pytestmark = [pytest.mark.fase4, pytest.mark.armazenamento]


def disco(livre_pct, total_gb=1000):
    total = total_gb * GB
    return DiskUsage(total=total, free=int(total * livre_pct / 100))


def rodar(check, fs, config=None, respostas=None):
    return check.run(make_context(respostas or {}, fs=fs, config=config))


def metricas(resultado):
    return {m.name: (m.value, m.unit) for m in resultado.metrics}


# --- C: -------------------------------------------------------------------------


def test_espaco_livre_no_c_gera_metricas_e_resumo():
    """Dado o C: com 330 GB livres de 1000 GB, então há métricas em % e GB e um resumo legível."""
    fs = FakeFileSystem()
    fs.disks["C:\\"] = disco(33)

    resultado = rodar(DiskCCheck(), fs)

    assert resultado.status is Status.OK
    assert resultado.summary == "330 GB livres de 1000 GB (33%)"
    assert metricas(resultado) == {
        "disk_c_free_pct": (33.0, "%"),
        "disk_c_free_gb": (330.0, "GB"),
        "disk_c_total_gb": (1000.0, "GB"),
    }


@pytest.mark.parametrize(
    ("livre_pct", "status"),
    [
        (20, Status.OK),
        (19.9, Status.WARN),
        (10, Status.WARN),
        (9.9, Status.PROBLEM),
    ],
)
def test_limites_do_c_nas_fronteiras(livre_pct, status):
    """Dado o C: com exatamente 20% / 19,9% / 10% / 9,9% livres, então 🟢 / 🟡 / 🟡 / 🔴."""
    fs = FakeFileSystem()
    fs.disks["C:\\"] = disco(livre_pct)

    assert rodar(DiskCCheck(), fs).status is status


def test_limites_do_c_vem_do_config():
    """Dado warn_below_pct = 40 no config, então 33% livres já fica 🟡."""
    fs = FakeFileSystem()
    fs.disks["C:\\"] = disco(33)
    config = {"checks": {"disk_c": {"warn_below_pct": 40}}}

    assert rodar(DiskCCheck(), fs, config).status is Status.WARN


# --- Dev Drive -------------------------------------------------------------------


def test_dev_drive_mede_espaco_livre_e_tamanho_do_vhdx_configurado():
    """Dado o D: com 40% livres e o VHDX configurado com 120 GB, então ambos aparecem."""
    fs = FakeFileSystem()
    fs.disks["D:\\"] = disco(40, total_gb=200)
    fs.files["C:\\DevDrive\\dev.vhdx"] = 120 * GB
    config = {"checks": {"dev_drive": {"vhdx": "C:\\DevDrive\\dev.vhdx"}}}

    resultado = rodar(DevDriveCheck(), fs, config)

    assert resultado.status is Status.OK
    assert resultado.summary == "D: 80,0 GB livres de 200 GB (40%) · VHDX 120 GB"
    assert metricas(resultado)["dev_drive_vhdx_gb"] == (120.0, "GB")


def test_vhdx_e_descoberto_automaticamente_quando_nao_configurado():
    """Dado o VHDX sem caminho no config, então o Windows informa qual arquivo sustenta o D:."""
    fs = FakeFileSystem()
    fs.disks["D:\\"] = disco(40, total_gb=200)
    fs.files["C:\\Users\\jg\\DevDrive.vhdx"] = 50 * GB
    resposta = {"Location": "C:\\Users\\jg\\DevDrive.vhdx", "BusType": "File Backed Virtual"}
    ctx = make_context({"dev_drive": resposta}, fs=fs)

    resultado = DevDriveCheck().run(ctx)

    assert "VHDX 50,0 GB" in resultado.summary
    assert "Get-Partition -DriveLetter $letter" in ctx.powershell.calls[0]["script"]
    assert "$letter = 'D'" in ctx.powershell.calls[0]["script"]


def test_falha_na_descoberta_do_vhdx_nao_impede_a_medicao_do_espaco():
    """Dado erro ao descobrir o VHDX, então o espaço livre é medido e o resumo avisa."""
    fs = FakeFileSystem()
    fs.disks["D:\\"] = disco(40, total_gb=200)

    resultado = rodar(DevDriveCheck(), fs, respostas={"dev_drive": RuntimeError("negado")})

    assert resultado.status is Status.OK
    assert resultado.summary.endswith("VHDX não encontrado (defina checks.dev_drive.vhdx)")
    assert "dev_drive_vhdx_gb" not in metricas(resultado)


@pytest.mark.parametrize(("livre_pct", "status"), [(20, Status.OK), (19.9, Status.WARN)])
def test_limite_do_dev_drive_na_fronteira(livre_pct, status):
    """Dado o D: com exatamente 20% ou 19,9% livres, então 🟢 ou 🟡."""
    fs = FakeFileSystem()
    fs.disks["D:\\"] = disco(livre_pct)

    assert rodar(DevDriveCheck(), fs, respostas={"dev_drive": None}).status is status


def test_dev_drive_ausente_fica_indisponivel():
    """Dado que a unidade D: não existe, então a checagem fica ⚪ indisponível."""
    resultado = rodar(DevDriveCheck(), FakeFileSystem())

    assert resultado.status is Status.SKIPPED
    assert resultado.summary == "indisponível: unidade D: não encontrada"


# --- sandboxes e Temp --------------------------------------------------------------

TEMP = "C:\\Users\\jg\\AppData\\Local\\Temp"


def pastas(sandbox_gb=None, temp_gb=None):
    fs = FakeFileSystem()
    if sandbox_gb is not None:
        fs.dirs["C:\\Sandbox"] = DirSize(int(sandbox_gb * GB), 100)
    if temp_gb is not None:
        fs.dirs[TEMP] = DirSize(int(temp_gb * GB), 50)
    return fs


def test_soma_de_sandboxes_e_temp_com_cada_pasta_no_resumo():
    """Dados 3,5 GB em C:\\Sandbox e 1,0 GB no Temp, então o resumo traz a soma e cada pasta."""
    resultado = rodar(ClutterCheck(), pastas(3.5, 1.0))

    assert resultado.status is Status.OK
    assert resultado.summary == "4,5 GB no total — sandboxes 3,5 GB, Temp 1,0 GB"
    assert metricas(resultado) == {
        "clutter_sandboxes_gb": (3.5, "GB"),
        "clutter_temp_gb": (1.0, "GB"),
        "clutter_total_gb": (4.5, "GB"),
    }


@pytest.mark.parametrize(
    ("sandbox_gb", "temp_gb", "status"),
    [(4.0, 1.0, Status.OK), (4.0, 1.5, Status.WARN), (6.0, 0.0, Status.WARN)],
)
def test_limite_de_5_gb_vale_para_a_soma(sandbox_gb, temp_gb, status):
    """Dadas as pastas somando exatamente 5 GB, 5,5 GB ou 6 GB, então 🟢, 🟡 e 🟡."""
    assert rodar(ClutterCheck(), pastas(sandbox_gb, temp_gb)).status is status


def test_temp_e_expandido_a_partir_da_variavel_de_ambiente():
    """Dado temp = "%TEMP%" no config padrão, então a pasta medida é o Temp do usuário."""
    resultado = rodar(ClutterCheck(), pastas(0, 2.0))

    assert "Temp 2,0 GB" in resultado.summary


def test_pasta_que_nao_existe_conta_como_zero_e_e_citada():
    """Dado que C:\\Sandbox não existe, então ela conta 0 GB e o resumo avisa."""
    resultado = rodar(ClutterCheck(), pastas(None, 1.0))

    assert resultado.summary == (
        "1,0 GB no total — sandboxes 0,0 GB, Temp 1,0 GB (C:\\Sandbox não existe)"
    )


def test_varias_pastas_de_sandbox_sao_somadas():
    """Dadas duas pastas de sandbox no config, então "sandboxes" é a soma delas."""
    fs = pastas(1.0, 0.0)
    fs.dirs["D:\\Sandbox2"] = DirSize(2 * GB, 10)
    config = {"checks": {"clutter": {"sandboxes": ["C:\\Sandbox", "D:\\Sandbox2"]}}}

    resultado = rodar(ClutterCheck(), fs, config)

    assert metricas(resultado)["clutter_sandboxes_gb"] == (3.0, "GB")


def test_itens_inacessiveis_sao_informados():
    """Dados arquivos que não puderam ser lidos no Temp, então o resumo informa quantos."""
    fs = pastas(0.0, 0.0)
    fs.dirs[TEMP] = DirSize(GB, 10, unreadable=3)

    resultado = rodar(ClutterCheck(), fs)

    assert f"3 itens inacessíveis em {TEMP}" in resultado.summary
