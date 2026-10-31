"""Executor de comandos externos (pip, wsl), que não passam pelo PowerShell."""

import subprocess

import pytest

from winzel.commands import CommandNotFound, Commands, CommandTimeout, first_line

pytestmark = [pytest.mark.fase2, pytest.mark.execucao]


def test_comando_devolve_codigo_saida_e_erro_em_bytes():
    """Dado um comando que termina, então recebo código de saída, stdout e stderr."""

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 3, b"saida", b"erro")

    resultado = Commands(run=run).run(["x"], label="t", timeout_s=5)

    assert (resultado.returncode, resultado.stdout, resultado.stderr) == (3, b"saida", b"erro")


def test_variaveis_pedidas_sao_removidas_do_ambiente(monkeypatch):
    """Dado env_remove=["VIRTUAL_ENV"], então o processo roda sem essa variável."""
    monkeypatch.setenv("VIRTUAL_ENV", "D:\\projetos\\winzel\\.venv")
    monkeypatch.setenv("OUTRA", "1")
    vistos = {}

    def run(args, **kwargs):
        vistos.update(kwargs["env"])
        return subprocess.CompletedProcess(args, 0, b"", b"")

    Commands(run=run).run(["py"], label="t", timeout_s=5, env_remove=["VIRTUAL_ENV"])

    assert "VIRTUAL_ENV" not in vistos
    assert vistos["OUTRA"] == "1"


def test_executavel_inexistente_gera_comando_nao_encontrado():
    """Dado um executável que não existe, então CommandNotFound informa qual."""

    def run(args, **kwargs):
        raise FileNotFoundError(args[0])

    with pytest.raises(CommandNotFound, match=r"comando não encontrado \(py\)"):
        Commands(run=run).run(["py", "-3.14"], label="pip_global:probe", timeout_s=5)


def test_comando_que_estoura_o_tempo_gera_timeout():
    """Dado um comando que excede o tempo, então CommandTimeout informa o limite."""

    def run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    with pytest.raises(CommandTimeout, match=r"tempo esgotado \(4 s\)"):
        Commands(run=run).run(["wsl.exe"], label="wsl_distros", timeout_s=4)


def test_primeira_linha_ignora_bytes_nulos_e_linhas_vazias():
    """Dada uma mensagem com bytes nulos e quebras, então obtenho a primeira linha legível."""
    assert first_line(b"\r\nNo module named pip\r\nmais") == "No module named pip"
