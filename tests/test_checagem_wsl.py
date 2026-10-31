"""Checagem `wsl_distros`: distribuições WSL, a partir de `wsl -l -v`.

O wsl.exe imprime em UTF-16 LE (SPEC, risco 3): os exemplos em tests/data/ são texto
e os testes os codificam como o wsl.exe faria.
"""

from pathlib import Path

import pytest
from tests.fakes import make_context, ok

from winzel.checks.wsl_distros import WslDistrosCheck, decode_wsl, parse_wsl_list
from winzel.commands import CommandNotFound, CommandResult
from winzel.models import Status

pytestmark = [pytest.mark.fase2, pytest.mark.inventario]

DATA = Path(__file__).parent / "data"


def saida_wsl(arquivo="wsl_list.txt", bom=False):
    """O texto de exemplo como o wsl.exe o imprime: UTF-16 LE, linhas com CRLF."""
    texto = (DATA / arquivo).read_text(encoding="utf-8").replace("\n", "\r\n")
    dados = texto.encode("utf-16-le")
    return b"\xff\xfe" + dados if bom else dados


def rodar(resposta):
    ctx = make_context({"wsl_distros": resposta})
    return WslDistrosCheck().run(ctx)


@pytest.mark.parametrize("bom", [False, True])
def test_saida_em_utf16_e_decodificada(bom):
    """Dada a saída do wsl.exe em UTF-16 LE (com ou sem BOM), então o texto sai legível."""
    texto = decode_wsl(saida_wsl(bom=bom))

    assert texto.startswith("NAME")
    assert "\x00" not in texto


def test_saida_em_utf8_tambem_e_aceita():
    """Dada a saída em UTF-8 (WSL_UTF8=1), então ela também é decodificada."""
    assert decode_wsl(b"NAME STATE VERSION\r\n").startswith("NAME")


def test_distros_aparecem_com_nome_e_versao_do_wsl():
    """Dado o exemplo, então há três distros, cada uma com a versão do WSL."""
    itens = parse_wsl_list(decode_wsl(saida_wsl()))

    assert [(i.details["name"], i.version) for i in itens] == [
        ("Debian", "1"),
        ("docker-desktop", "2"),
        ("Ubuntu-24.04", "2"),
    ]


def test_estado_e_distro_padrao_ficam_so_nos_detalhes():
    """Dado o Ubuntu rodando e padrão, então isso fica em details, fora do atributo comparado."""
    ubuntu = next(i for i in parse_wsl_list(decode_wsl(saida_wsl())) if i.key == "ubuntu-24.04")

    assert ubuntu.details == {"name": "Ubuntu-24.04", "state": "Running", "default": True}
    assert ubuntu.version == "2"


def test_cabecalho_traduzido_e_lido_pela_posicao_das_colunas():
    """Dado o cabeçalho em português ("NOME ESTADO VERSÃO"), então a leitura funciona igual."""
    itens = parse_wsl_list(decode_wsl(saida_wsl("wsl_list_pt.txt")))

    assert [(i.details["name"], i.details["state"], i.version) for i in itens] == [
        ("Ubuntu-24.04", "Parado", "2")
    ]


def test_checagem_resume_a_contagem_de_distros():
    """Dada a saída do exemplo, quando a checagem roda, então resume "3 distribuições"."""
    resultado = rodar(ok(saida_wsl()))

    assert (resultado.status, resultado.summary) == (Status.OK, "3 distribuições")


def test_wsl_nao_instalado_fica_verde_com_zero_distros():
    """Dado que o wsl.exe não existe, então a checagem fica 🟢 com 0 distros (não é erro)."""
    resultado = rodar(CommandNotFound("wsl.exe"))

    assert resultado.status is Status.OK
    assert resultado.items == []
    assert "WSL não instalado" in resultado.summary


@pytest.mark.parametrize(
    "mensagem",
    [
        "O Subsistema do Windows para Linux não tem distribuições instaladas.",
        "Windows Subsystem for Linux has no installed distributions.\r\n"
        "Error code: Wsl/WSL_E_DEFAULT_DISTRO_NOT_FOUND",
    ],
)
def test_wsl_sem_distribuicoes_fica_verde_com_zero_distros(mensagem):
    """Dado o aviso de "nenhuma distribuição" (código ≠ 0), então a checagem fica 🟢 com 0."""
    resultado = rodar(CommandResult(1, mensagem.encode("utf-16-le")))

    assert resultado.status is Status.OK
    assert resultado.items == []


def test_outro_erro_do_wsl_gera_erro_com_a_mensagem():
    """Dado um erro desconhecido do wsl.exe, então a checagem falha (❗) com a mensagem."""
    with pytest.raises(Exception, match="wsl falhou: Serviço indisponível"):
        rodar(CommandResult(1, "Serviço indisponível.\r\n".encode("utf-16-le")))
