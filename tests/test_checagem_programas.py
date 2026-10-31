"""Checagem `programs`: programas instalados, a partir das chaves Uninstall do registro.

Os dados de exemplo (tests/data/programs.json) imitam a saída do PowerShell com
entradas de HKLM 64 bits, HKLM 32 bits (WOW6432Node) e HKCU.
"""

import pytest
from tests.fakes import make_context, sample

from winzel.checks.programs import ProgramsCheck, normalize_name, parse_programs, program_key
from winzel.models import Status

pytestmark = [pytest.mark.fase1, pytest.mark.inventario]


def por_nome(itens):
    return {i.details["name"]: i for i in itens}


# --- filtros e fontes ---------------------------------------------------------


def test_le_programas_de_hklm_64_bits_hklm_32_bits_e_hkcu():
    """Dados programas nas três fontes do registro, quando interpreto, então todos aparecem."""
    itens = por_nome(parse_programs(sample("programs")))

    assert itens["7-Zip 24.08 (x64)"].details["sources"] == ["HKLM64"]
    assert itens["Microsoft Visual C++ 2015-2022 Redistributable (x86) - 14.40.33810"].details[
        "sources"
    ] == ["HKLM32"]
    assert itens["Microsoft Visual Studio Code (User)"].details["sources"] == ["HKCU"]


def test_entrada_sem_display_name_e_ignorada():
    """Dada uma entrada do registro sem DisplayName (ex.: atualização KB), então ela é ignorada."""
    itens = parse_programs(sample("programs"))

    assert all(i.details["registry_key"] != "KB5034441" for i in itens)


def test_entrada_com_system_component_1_e_ignorada_e_com_0_e_mantida():
    """Dado SystemComponent = 1, então o programa some da lista; com "0", ele é mantido."""
    nomes = por_nome(parse_programs(sample("programs")))

    assert "Microsoft Visual C++ 2022 X64 Minimum Runtime - 14.40.33810" not in nomes
    assert "VLC media player" in nomes


def test_mesmo_programa_em_duas_fontes_vira_um_item_com_as_duas_fontes():
    """Dado o Git registrado em HKLM e em HKCU, então há um só item, que lista as duas fontes."""
    itens = [i for i in parse_programs(sample("programs")) if i.details["name"] == "Git"]

    assert len(itens) == 1
    assert itens[0].details["sources"] == ["HKLM64", "HKCU"]


def test_total_de_programas_do_exemplo():
    """Dadas 9 entradas (1 sem nome, 1 de sistema, 1 duplicada), então restam 6 programas."""
    itens = parse_programs(sample("programs"))

    assert len(itens) == 6


def test_versao_vem_de_display_version_como_texto():
    """Dado DisplayVersion numérico (3), então a versão do item é o texto "3"."""
    itens = por_nome(parse_programs(sample("programs")))

    assert itens["VLC media player"].version == "3"
    assert itens["Python 3.14.0 (64-bit)"].version == "3.14.150.0"


def test_saida_com_um_unico_programa_em_objeto_e_saida_vazia_sao_aceitas():
    """Dado o ConvertTo-Json devolvendo um objeto (1 programa) ou null, então nada quebra."""
    um = {"Source": "HKCU", "DisplayName": "Steam", "DisplayVersion": "2.10", "Publisher": "Valve"}

    assert [i.details["name"] for i in parse_programs(um)] == ["Steam"]
    assert parse_programs(None) == []


# --- chave normalizada (SPEC, risco 1) ----------------------------------------


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("Python 3.14.0 (64-bit)", "python (64-bit)"),
        ("7-Zip 24.08 (x64)", "7-zip (x64)"),
        (
            "Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.40.33810",
            "microsoft visual c++ 2015-2022 redistributable (x64)",
        ),
        ("Dell SupportAssist Plugin v5.5.12.16815", "dell supportassist plugin"),
        ("Mozilla Firefox (x64 pt-BR)", "mozilla firefox (x64 pt-br)"),
        ("Node.js", "node.js"),
        ("Microsoft 365 Apps for business - pt-br", "microsoft 365 apps for business - pt-br"),
    ],
)
def test_nome_normalizado_remove_versoes_e_mantem_arquitetura_e_anos(nome, esperado):
    """Dado um nome com versão embutida, então a chave remove a versão e mantém o resto."""
    assert normalize_name(nome) == esperado


def test_atualizacao_com_versao_no_nome_mantem_a_mesma_chave():
    """Dados "Python 3.14.0" e "Python 3.14.1", então a chave é a mesma (vira "alterado")."""
    antes = program_key("Python 3.14.0 (64-bit)", "Python Software Foundation")
    depois = program_key("Python 3.14.1 (64-bit)", "Python Software Foundation")

    assert antes == depois == "python (64-bit)|python software foundation"


def test_versoes_de_32_e_64_bits_tem_chaves_diferentes():
    """Dados os pacotes x86 e x64 do mesmo programa, então são itens distintos."""
    x86 = program_key("Microsoft Visual C++ 2015-2022 Redistributable (x86) - 14.40", "Microsoft")
    x64 = program_key("Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.40", "Microsoft")

    assert x86 != x64


def test_limitacao_versao_sem_ponto_no_nome_nao_e_removida():
    """Limitação conhecida: em "Java 8 Update 401", números sem ponto ficam na chave."""
    assert normalize_name("Java 8 Update 401 (64-bit)") == "java 8 update 401 (64-bit)"


def test_nome_original_fica_guardado_nos_detalhes():
    """Dada a chave normalizada, então o nome original continua disponível em details."""
    item = por_nome(parse_programs(sample("programs")))["Python 3.14.0 (64-bit)"]

    assert item.key == "python (64-bit)|python software foundation"
    assert item.details["publisher"] == "Python Software Foundation"


# --- a checagem ---------------------------------------------------------------


def test_checagem_consulta_o_powershell_uma_vez_e_resume_a_contagem():
    """Dado o PowerShell falso com o exemplo, quando a checagem roda, então resume "6 programas"."""
    ctx = make_context({"programs": sample("programs")})

    resultado = ProgramsCheck().run(ctx)

    assert resultado.status is Status.OK
    assert resultado.summary == "6 programas"
    assert len(ctx.powershell.calls) == 1
    assert "WOW6432Node" in ctx.powershell.calls[0]["script"]


def test_checagem_usa_o_timeout_do_config():
    """Dado timeout_s = 7 no config, quando a checagem roda, então o PowerShell recebe 7 s."""
    config = {"checks": {"programs": {"timeout_s": 7}}}
    ctx = make_context({"programs": []}, config=config)

    ProgramsCheck().run(ctx)

    assert ctx.powershell.calls[0]["timeout_s"] == 7


def test_limitacao_programas_portateis_nao_aparecem():
    """Limitação conhecida: só entra o que tem chave Uninstall; portáteis não são vistos."""
    ctx = make_context({"programs": []})

    resultado = ProgramsCheck().run(ctx)

    assert resultado.items == []
