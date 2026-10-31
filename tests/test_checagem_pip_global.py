"""Checagem `pip_global`: pacotes do Python global, que deve ter só o pip (SPEC, seção 3).

O executor de comandos falso responde à sondagem do interpretador (`pip_global:probe`)
e à listagem do pip (`pip_global:list`).
"""

import json

import pytest
from tests.fakes import make_context, ok, sample

from winzel.checks.pip_global import PipGlobalCheck, interpreter, normalize_package
from winzel.commands import CommandNotFound, CommandResult
from winzel.models import Status

pytestmark = [pytest.mark.fase2, pytest.mark.inventario]

PYTHON = "C:\\Python314\\python.exe"


def sonda(venv=False, executable=PYTHON):
    return ok(json.dumps({"executable": executable, "version": "3.14.6", "venv": venv}))


def lista(pacotes):
    return ok(json.dumps(pacotes))


def rodar(probe, listing=None, config=None):
    respostas = {"pip_global:probe": probe}
    if listing is not None:
        respostas["pip_global:list"] = listing
    ctx = make_context(respostas, config=config)
    return PipGlobalCheck().run(ctx), ctx


def test_python_global_so_com_pip_fica_verde():
    """Dado o Python global só com o pip, então a checagem fica 🟢 e mostra o interpretador."""
    resultado, _ = rodar(sonda(), lista([{"name": "pip", "version": "25.2"}]))

    assert resultado.status is Status.OK
    assert resultado.summary == f"1 pacote (só o pip) em {PYTHON}"


def test_qualquer_pacote_alem_do_pip_deixa_amarelo():
    """Dados requests e typing_extensions além do pip, então a checagem fica 🟡."""
    resultado, _ = rodar(sonda(), lista(sample("pip_list")))

    assert resultado.status is Status.WARN
    assert resultado.summary == f"3 pacotes (2 além do pip) em {PYTHON}"


def test_nomes_de_pacotes_sao_normalizados_pela_pep_503():
    """Dados "Requests" e "typing_extensions", então as chaves seguem a PEP 503."""
    resultado, _ = rodar(sonda(), lista(sample("pip_list")))

    assert [i.key for i in resultado.items] == ["pip", "requests", "typing-extensions"]
    assert normalize_package("Zope.Interface") == "zope-interface"


def test_por_padrao_usa_o_launcher_py_3_14_sem_a_variavel_virtual_env():
    """Dado o config padrão, então os comandos usam `py -3.14` e removem VIRTUAL_ENV."""
    _, ctx = rodar(sonda(), lista([]))

    sondagem, listagem = ctx.commands.calls
    assert sondagem["args"][:2] == ["py", "-3.14"]
    assert listagem["args"] == [
        "py",
        "-3.14",
        "-m",
        "pip",
        "list",
        "--format=json",
        "--disable-pip-version-check",
    ]
    assert sondagem["env_remove"] == ["VIRTUAL_ENV"]


def test_caminho_do_python_pode_ser_definido_no_config():
    """Dado `python` no config (caminho ou lista), então ele substitui o launcher."""
    assert interpreter({"checks": {"pip_global": {"python": PYTHON}}}) == [PYTHON]
    assert interpreter({"checks": {"pip_global": {"python": ["py", "-3.13"]}}}) == ["py", "-3.13"]
    assert interpreter({"checks": {"pip_global": {"python": ""}}}) == ["py", "-3.14"]


def test_interpretador_que_e_um_venv_gera_erro():
    """Dado que o Python encontrado é um venv, então a checagem falha (❗) em vez de listar."""
    with pytest.raises(Exception, match="o Python indicado é um venv"):
        rodar(sonda(venv=True, executable="D:\\projetos\\x\\.venv\\Scripts\\python.exe"))


def test_python_global_nao_encontrado_fica_indisponivel():
    """Dado que o launcher `py` não existe, então a checagem fica ⚪ indisponível, sem erro."""
    resultado, _ = rodar(CommandNotFound("pip_global:probe: comando não encontrado (py)"))

    assert resultado.status is Status.SKIPPED
    assert resultado.summary.startswith("indisponível: Python global não encontrado")


def test_versao_pedida_ao_launcher_inexistente_fica_indisponivel():
    """Dado `py -3.14` sem o Python 3.14 instalado, então a checagem fica ⚪ com o motivo."""
    resposta = CommandResult(103, b"", b"No suitable Python runtime found\r\n")

    resultado, _ = rodar(resposta)

    assert resultado.status is Status.SKIPPED
    assert "No suitable Python runtime found" in resultado.summary


def test_falha_do_pip_list_gera_erro():
    """Dado um Python global sem pip (pip list falha), então a checagem dá erro com o motivo."""
    sem_pip = CommandResult(1, b"", b"No module named pip\r\n")

    with pytest.raises(Exception, match="pip list falhou: No module named pip"):
        rodar(sonda(), sem_pip)


def test_regra_propria_de_status_vale_mesmo_sem_mudancas():
    """Dado o pip_global com pacote extra, então a regra própria dá 🟡 independente do diff."""
    resultado, _ = rodar(sonda(), lista(sample("pip_list")))

    assert PipGlobalCheck().status_rule(resultado.items) is Status.WARN
