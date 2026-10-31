"""Checagem `store_apps`: apps da Store (AppX/MSIX) do usuário atual.

Os dados de exemplo (tests/data/store_apps.json) imitam a saída de `Get-AppxPackage`.
"""

import pytest
from tests.fakes import make_context, sample

from winzel.checks.programs import parse_programs
from winzel.checks.store_apps import StoreAppsCheck, parse_store_apps
from winzel.models import Status

pytestmark = [pytest.mark.fase2, pytest.mark.inventario]


def nomes(itens):
    return [i.key for i in itens]


def test_apps_da_store_e_sideload_aparecem_com_nome_do_pacote_e_versao():
    """Dado o exemplo, então ficam Terminal, Spotify e um app de desenvolvedor, com versão."""
    itens = parse_store_apps(sample("store_apps"))

    assert nomes(itens) == [
        "Contoso.Ferramenta",
        "Microsoft.WindowsTerminal",
        "SpotifyAB.SpotifyMusic",
    ]
    terminal = itens[1]
    assert terminal.version == "1.21.2911.0"
    assert terminal.details["family"] == "Microsoft.WindowsTerminal_8wekyb3d8bbwe"


def test_frameworks_sao_ignorados():
    """Dado um pacote com IsFramework (VCLibs), então ele não aparece."""
    assert "Microsoft.VCLibs.140.00.UWPDesktop" not in nomes(parse_store_apps(sample("store_apps")))


def test_pacotes_de_recurso_sao_ignorados():
    """Dado um pacote de idioma (IsResourcePackage), então ele não aparece."""
    assert "Microsoft.LanguageExperiencePackpt-BR" not in nomes(
        parse_store_apps(sample("store_apps"))
    )


def test_apps_de_sistema_sao_ignorados():
    """Dado um app com SignatureKind = System, então ele não aparece."""
    assert "Microsoft.Windows.ShellExperienceHost" not in nomes(
        parse_store_apps(sample("store_apps"))
    )


def test_mesmo_pacote_em_duas_arquiteturas_vira_um_item():
    """Dado o mesmo pacote em x64 e x86, então há um só item, com as duas arquiteturas."""
    itens = [i for i in parse_store_apps(sample("store_apps")) if i.key == "Contoso.Ferramenta"]

    assert len(itens) == 1
    assert itens[0].details["architectures"] == ["X64", "X86"]


def test_limitacao_mesmo_programa_pode_aparecer_em_programas_e_em_apps_da_store():
    """Limitação conhecida: o Spotify instalado pelos dois meios aparece nas duas categorias."""
    spotify_win32 = [{"Source": "HKCU", "DisplayName": "Spotify", "DisplayVersion": "1.2.48"}]

    em_programas = [i.details["name"] for i in parse_programs(spotify_win32)]
    na_store = nomes(parse_store_apps(sample("store_apps")))

    assert "Spotify" in em_programas
    assert "SpotifyAB.SpotifyMusic" in na_store


def test_checagem_resume_a_contagem_de_apps():
    """Dado o exemplo, quando a checagem roda, então resume "3 apps"."""
    ctx = make_context({"store_apps": sample("store_apps")})

    resultado = StoreAppsCheck().run(ctx)

    assert (resultado.status, resultado.summary) == (Status.OK, "3 apps")


def test_saida_com_um_unico_app_em_objeto_e_aceita():
    """Dado o ConvertTo-Json devolvendo um objeto (1 app), então ele vira um item."""
    um = sample("store_apps")[0]

    assert nomes(parse_store_apps(um)) == ["Microsoft.WindowsTerminal"]
