"""Execução: executor do PowerShell, configuração e execução paralela das checagens."""

import base64
import subprocess
import threading
from dataclasses import dataclass

import pytest
from tests.fakes import make_context

from winzel.config import ConfigError, check_timeout, load_config, load_default_config, merge
from winzel.models import CheckResult, Status
from winzel.powershell import PowerShell, PowerShellError, PowerShellTimeout, build_command
from winzel.runner import run_checks

pytestmark = [pytest.mark.fase1, pytest.mark.execucao]


# --- executor do PowerShell ---------------------------------------------------


def processo(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    """Um `subprocess.run` falso que devolve sempre o mesmo resultado e guarda as chamadas."""
    chamadas = []

    def run(command, **kwargs):
        chamadas.append((command, kwargs))
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    run.chamadas = chamadas
    return run


def test_powershell_roda_sem_perfil_nao_interativo_e_com_script_codificado():
    """Dado um script, quando monto o comando, então uso -NoProfile, -NonInteractive e base64."""
    comando = build_command("Get-Date")

    assert comando[:3] == ["powershell.exe", "-NoProfile", "-NonInteractive"]
    script = base64.b64decode(comando[-1]).decode("utf-16-le")
    assert "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8" in script
    assert script.endswith("Get-Date")


def test_powershell_devolve_o_json_da_saida_decodificado_em_utf8():
    """Dada uma saída JSON em UTF-8 (com acentos e BOM), então recebo o objeto Python."""
    run = processo(stdout='﻿[{"Nome": "Configurações"}]'.encode())

    resultado = PowerShell(run=run).run_json("x", label="teste", timeout_s=5)

    assert resultado == [{"Nome": "Configurações"}]
    assert run.chamadas[0][1]["timeout"] == 5


def test_powershell_sem_saida_devolve_none():
    """Dado um script que não imprime nada, então o resultado é None."""
    assert PowerShell(run=processo()).run_json("x", label="teste", timeout_s=5) is None


def test_powershell_com_codigo_de_erro_gera_erro_com_a_primeira_linha_do_stderr():
    """Dado código de saída 1, então PowerShellError traz o rótulo e a primeira linha do erro."""
    run = processo(stderr=b"Acesso negado.\r\nmais detalhes", returncode=1)

    with pytest.raises(PowerShellError, match=r"programs: PowerShell falhou — Acesso negado\."):
        PowerShell(run=run).run_json("x", label="programs", timeout_s=5)


def test_powershell_com_saida_que_nao_e_json_gera_erro():
    """Dada uma saída que não é JSON, então PowerShellError explica isso."""
    with pytest.raises(PowerShellError, match="não é JSON válido"):
        PowerShell(run=processo(stdout=b"oops")).run_json("x", label="t", timeout_s=5)


def test_powershell_que_estoura_o_tempo_gera_erro_de_timeout():
    """Dado um processo que excede o timeout, então PowerShellTimeout informa o limite."""

    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with pytest.raises(PowerShellTimeout, match=r"tempo esgotado \(2 s\)"):
        PowerShell(run=run).run_json("x", label="t", timeout_s=2)


# --- configuração -------------------------------------------------------------


def test_configuracao_padrao_vem_do_pacote():
    """Dado o pacote instalado, então a configuração padrão traz emoji ligado e timeouts."""
    config = load_default_config()

    assert config["display"]["emoji"] is True
    assert config["checks"]["programs"]["timeout_s"] == 30


def test_config_do_usuario_se_sobrepoe_ao_padrao_chave_a_chave(tmp_path):
    """Dado um config.toml do usuário com emoji = false, então só essa chave muda."""
    arquivo = tmp_path / "config.toml"
    arquivo.write_text("[display]\nemoji = false\n", encoding="utf-8")

    config = load_config(arquivo)

    assert config["display"]["emoji"] is False
    assert config["checks"]["startup"]["timeout_s"] == 30


def test_sem_config_do_usuario_vale_o_padrao(tmp_path):
    """Dado que o config.toml do usuário não existe, então vale a configuração padrão."""
    assert load_config(tmp_path / "nao-existe.toml") == load_default_config()


def test_config_invalido_gera_erro_claro(tmp_path):
    """Dado um config.toml com TOML inválido, então ConfigError aponta o arquivo."""
    arquivo = tmp_path / "config.toml"
    arquivo.write_text("[display\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="configuração inválida"):
        load_config(arquivo)


def test_mescla_profunda_preserva_tabelas_nao_mencionadas():
    """Dadas duas tabelas aninhadas, quando mesclo, então o que não foi sobrescrito permanece."""
    resultado = merge({"a": {"x": 1, "y": 2}, "b": 3}, {"a": {"y": 20}})

    assert resultado == {"a": {"x": 1, "y": 20}, "b": 3}


def test_timeout_da_checagem_usa_o_config_ou_o_padrao_da_checagem():
    """Dado um timeout no config, então ele vale; sem ele, vale o padrão da checagem."""
    config = {"checks": {"programs": {"timeout_s": 12}}}

    assert check_timeout(config, "programs", 30) == 12
    assert check_timeout(config, "startup", 30) == 30


# --- execução paralela --------------------------------------------------------


@dataclass
class ChecagemFalsa:
    id: str
    comportamento: object = None  # None: ok; Exception: lança; threading.Event: espera
    requires_admin: bool = False
    timeout_s: float = 5.0
    label: str = "Falsa"
    area: str = "inventario"
    executou: bool = False

    def run(self, ctx):
        self.executou = True
        if isinstance(self.comportamento, Exception):
            raise self.comportamento
        if isinstance(self.comportamento, threading.Event):
            self.comportamento.wait(5)
        return CheckResult(check_id=self.id, status=Status.OK, summary="ok")


def test_checagens_rodam_e_os_resultados_vem_na_ordem_das_checagens():
    """Dadas três checagens, quando executo, então os resultados vêm na mesma ordem."""
    checagens = [ChecagemFalsa("a"), ChecagemFalsa("b"), ChecagemFalsa("c")]

    resultados = run_checks(checagens, make_context())

    assert [r.check_id for r in resultados] == ["a", "b", "c"]
    assert all(r.status is Status.OK for r in resultados)


def test_checagens_rodam_em_paralelo():
    """Dadas duas checagens que esperam uma pela outra, quando executo, então ambas terminam."""
    a_comecou, b_comecou = threading.Event(), threading.Event()

    class Espera(ChecagemFalsa):
        def run(self, ctx):
            meu, outro = (a_comecou, b_comecou) if self.id == "a" else (b_comecou, a_comecou)
            meu.set()
            assert outro.wait(2), "a outra checagem não rodou em paralelo"
            return super().run(ctx)

    resultados = run_checks([Espera("a"), Espera("b")], make_context())

    assert [r.status for r in resultados] == [Status.OK, Status.OK]


def test_excecao_numa_checagem_vira_erro_e_nao_afeta_as_demais():
    """Dada uma checagem que lança exceção, então ela fica ❗ com a mensagem; a outra fica 🟢."""
    checagens = [ChecagemFalsa("quebra", RuntimeError("registro ilegível")), ChecagemFalsa("ok")]

    quebra, ok = run_checks(checagens, make_context())

    assert quebra.status is Status.ERROR
    assert quebra.error == "registro ilegível"
    assert quebra.summary == "erro: registro ilegível"
    assert ok.status is Status.OK


def test_checagem_que_estoura_o_tempo_vira_erro_e_nao_atrasa_as_demais():
    """Dada uma checagem travada com timeout de 0,2 s, então ela vira erro de tempo esgotado."""
    trava = threading.Event()
    lenta = ChecagemFalsa("lenta", trava, timeout_s=0.2)
    config = {"checks": {}}

    try:
        lenta_r, rapida_r = run_checks(
            [lenta, ChecagemFalsa("rapida")], make_context(config=config)
        )
    finally:
        trava.set()

    assert lenta_r.status is Status.ERROR
    assert lenta_r.error == "tempo esgotado (0.2 s)"
    assert rapida_r.status is Status.OK


def test_checagem_que_exige_admin_sem_elevacao_e_pulada_sem_executar():
    """Dada uma checagem com requires_admin sem elevação, então ela fica ⚪ e não executa."""
    checagem = ChecagemFalsa("ssd", requires_admin=True)

    (resultado,) = run_checks([checagem], make_context(is_admin=False))

    assert resultado.status is Status.SKIPPED
    assert resultado.summary == "pulada: requer administrador"
    assert checagem.executou is False


def test_checagem_que_exige_admin_com_elevacao_executa():
    """Dada uma checagem com requires_admin e o winzel elevado, então ela executa."""
    checagem = ChecagemFalsa("ssd", requires_admin=True)

    (resultado,) = run_checks([checagem], make_context(is_admin=True))

    assert resultado.status is Status.OK
    assert checagem.executou is True


def test_progresso_e_informado_a_cada_checagem_concluida():
    """Dadas duas checagens, quando executo com callback, então ele é chamado duas vezes."""
    vistos = []

    run_checks([ChecagemFalsa("a"), ChecagemFalsa("b")], make_context(), vistos.append)

    assert sorted(r.check_id for r in vistos) == ["a", "b"]


def test_duracao_de_cada_checagem_e_medida():
    """Dada uma checagem, quando executo, então duration_ms é preenchido (≥ 0)."""
    (resultado,) = run_checks([ChecagemFalsa("a")], make_context())

    assert resultado.duration_ms >= 0
