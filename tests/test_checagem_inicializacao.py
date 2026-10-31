"""Checagem `startup`: itens de inicialização e seu estado ligado/desligado.

Os dados de exemplo (tests/data/startup.json) imitam a saída do PowerShell:
`entries` (chaves Run/RunOnce e pastas Inicializar) e `approved` (StartupApproved).
"""

import pytest
from tests.fakes import make_context, sample

from winzel.checks.startup import StartupCheck, is_disabled, parse_startup
from winzel.models import Status

pytestmark = [pytest.mark.fase1, pytest.mark.inventario]


def por_nome(itens):
    return {i.details["name"]: i for i in itens}


def test_le_chaves_run_runonce_de_hkcu_hklm_e_32_bits_e_as_duas_pastas_inicializar():
    """Dado o exemplo, quando interpreto, então os itens vêm de todas as origens."""
    locais = {i.details["location"] for i in parse_startup(sample("startup"))}

    assert locais == {
        "hkcu_run",
        "hkcu_runonce",
        "hklm_run",
        "hklm32_run",
        "startup_user",
        "startup_common",
    }


def test_chave_do_item_e_nome_e_local():
    """Dado o OneDrive em HKCU Run, então a chave é `onedrive|hkcu_run`."""
    item = por_nome(parse_startup(sample("startup")))["OneDrive"]

    assert item.key == "onedrive|hkcu_run"
    assert item.details["location_label"] == "HKCU Run"


def test_startup_approved_com_byte_par_e_ligado_e_impar_e_desligado():
    """Dados 02 (OneDrive) e 03 (Spotify) em StartupApproved, então ligado e desligado."""
    itens = por_nome(parse_startup(sample("startup")))

    assert itens["OneDrive"].details["enabled"] is True
    assert itens["Spotify"].details["enabled"] is False


def test_item_sem_valor_em_startup_approved_esta_ligado():
    """Dado SecurityHealth sem valor em StartupApproved, então ele está ligado."""
    item = por_nome(parse_startup(sample("startup")))["SecurityHealth"]

    assert item.details["enabled"] is True


def test_run_de_32_bits_usa_a_lista_run32_de_startup_approved():
    """Dado um item em WOW6432Node\\Run desligado em Run32, então ele aparece desligado."""
    item = por_nome(parse_startup(sample("startup")))["Logitech Download Assistant"]

    assert item.details["location_label"] == "HKLM Run (32 bits)"
    assert item.details["enabled"] is False


def test_atalho_na_pasta_inicializar_usa_a_lista_startup_folder():
    """Dado um atalho desligado em StartupFolder, então ele aparece desligado, com o destino."""
    item = por_nome(parse_startup(sample("startup")))["Send to OneNote.lnk"]

    assert item.details["enabled"] is False
    assert item.details["command"].endswith("ONENOTEM.EXE /tsr")


def test_runonce_esta_sempre_ligado():
    """Dado um item em RunOnce, então ele está ligado (RunOnce não tem estado ligado/desligado)."""
    item = por_nome(parse_startup(sample("startup")))["LimpezaPosInstalacao"]

    assert item.details["enabled"] is True


def test_valor_orfao_em_startup_approved_nao_cria_item():
    """Dado um valor em StartupApproved sem item correspondente, então nenhum item é criado."""
    assert "AppJaRemovido" not in por_nome(parse_startup(sample("startup")))


def test_estado_e_comando_formam_o_atributo_comparavel():
    """Dado o Spotify desligado, então o atributo comparável é "desligado: <comando>"."""
    item = por_nome(parse_startup(sample("startup")))["Spotify"]

    assert (
        item.version
        == "desligado: C:\\Users\\jg\\AppData\\Roaming\\Spotify\\Spotify.exe --autostart"
    )


def test_nome_em_startup_approved_e_comparado_sem_diferenciar_maiusculas():
    """Dado "SPOTIFY" em StartupApproved e "Spotify" em Run, então o estado se aplica."""
    bruto = {
        "entries": [{"Location": "hkcu_run", "Name": "Spotify", "Command": "spotify.exe"}],
        "approved": [{"Hive": "HKCU", "List": "Run", "Name": "SPOTIFY", "Flag": 3}],
    }

    assert parse_startup(bruto)[0].details["enabled"] is False


@pytest.mark.parametrize(("flag", "desligado"), [(2, False), (3, True), (6, False), (7, True)])
def test_bit_menos_significativo_do_primeiro_byte_indica_desligado(flag, desligado):
    """Dado o primeiro byte de StartupApproved, então ímpar significa desligado."""
    assert is_disabled(flag) is desligado


def test_checagem_resume_total_e_desligados():
    """Dado o exemplo com 7 itens, 3 desligados, quando a checagem roda, então resume isso."""
    ctx = make_context({"startup": sample("startup")})

    resultado = StartupCheck().run(ctx)

    assert resultado.status is Status.OK
    assert resultado.summary == "7 itens (3 desligados)"


def test_saida_vazia_do_powershell_gera_lista_vazia():
    """Dado o PowerShell sem saída (null), então a checagem devolve zero itens."""
    ctx = make_context({"startup": None})

    resultado = StartupCheck().run(ctx)

    assert resultado.items == []
    assert resultado.summary == "0 itens"
