"""Backup: ponto de restauração e repositórios git com pendências (SPEC 5.3).

A imagem de disco (`disk_image`) foi adiada: ainda não há como testá-la.
"""

from datetime import datetime

import pytest
from tests.fakes import FakeFileSystem, FixedClock, make_context, ok

from winzel.checks.git_repos import GitReposCheck
from winzel.checks.restore_point import RestorePointCheck
from winzel.commands import CommandNotFound, CommandResult
from winzel.models import Status
from winzel.runner import run_checks

pytestmark = [pytest.mark.fase5, pytest.mark.backup]

AGORA = datetime(2026, 11, 10, 12, 0)


# --- ponto de restauração ------------------------------------------------------------


def restauracao(pontos):
    ctx = make_context({"restore_point": pontos}, clock=FixedClock(AGORA), is_admin=True)
    return RestorePointCheck().run(ctx)


def test_ponto_de_restauracao_recente_fica_verde_e_mostra_o_mais_novo():
    """Dados dois pontos, então vale o mais novo; com 5 dias, a checagem fica 🟢."""
    resultado = restauracao(
        [
            {"Created": "2026-10-01T10:00:00", "Description": "Antigo"},
            {"Created": "2026-11-05T12:00:00", "Description": "Instalou Office"},
        ]
    )

    assert resultado.status is Status.OK
    assert resultado.summary == "último em 05/11/2026 (5 dias): Instalou Office"


@pytest.mark.parametrize(
    ("criado", "status"),
    [("2026-10-11T12:00:00", Status.OK), ("2026-10-11T11:00:00", Status.WARN)],
)
def test_ponto_com_mais_de_30_dias_deixa_amarelo(criado, status):
    """Dado o último ponto com exatamente 30 dias ou um pouco mais, então 🟢 ou 🟡."""
    assert restauracao([{"Created": criado, "Description": "x"}]).status is status


def test_sem_ponto_de_restauracao_fica_amarelo():
    """Dado que não existe ponto de restauração, então a checagem fica 🟡."""
    resultado = restauracao(None)

    assert (resultado.status, resultado.summary) == (Status.WARN, "nenhum ponto de restauração")


def test_ponto_de_restauracao_exige_administrador():
    """Dado o winzel sem elevação, então a checagem fica ⚪ pulada."""
    (resultado,) = run_checks([RestorePointCheck()], make_context({}, is_admin=False))

    assert resultado.status is Status.SKIPPED


# --- repositórios git ----------------------------------------------------------------

RAIZ = "D:\\projetos"


class Repos:
    """Pasta D:\\projetos falsa: cada repositório responde aos comandos git como configurado."""

    def __init__(self):
        self.fs = FakeFileSystem()
        self.fs.subdirs[RAIZ] = []
        self.respostas = {}

    def repo(self, nome, alteracoes=0, adiante=0, remoto=True):
        self.fs.subdirs[RAIZ].append(nome)
        self.fs.existing.add(f"{RAIZ}\\{nome}\\.git")

        def git(args):
            comando = args[3]
            if comando == "status":
                return ok("".join(f" M arquivo{i}.py\n" for i in range(alteracoes)))
            if comando == "rev-parse":
                return ok("origin/main\n") if remoto else CommandResult(128, b"", b"fatal")
            return ok(f"{adiante}\n")

        self.respostas[f"git_repos:{nome}"] = git

    def pasta_comum(self, nome):
        self.fs.subdirs[RAIZ].append(nome)

    def rodar(self):
        ctx = make_context(self.respostas, fs=self.fs)
        return GitReposCheck().run(ctx), ctx


def test_repositorios_sem_pendencias_ficam_verdes():
    """Dados dois repositórios limpos e enviados, então 🟢 "tudo enviado"."""
    repos = Repos()
    repos.repo("winzel")
    repos.repo("notas")

    resultado, _ = repos.rodar()

    assert (resultado.status, resultado.summary) == (Status.OK, "2 repositórios, tudo enviado")


def test_alteracoes_nao_commitadas_e_commits_nao_enviados_deixam_amarelo():
    """Dados um repositório com 3 alterações e outro 2 commits à frente, então 🟡 detalhado."""
    repos = Repos()
    repos.repo("winzel", alteracoes=3)
    repos.repo("notas", adiante=2)
    repos.repo("limpo")

    resultado, _ = repos.rodar()

    assert resultado.status is Status.WARN
    assert resultado.summary == (
        "2 de 3 repositórios com pendências: winzel (3 alterações); notas (2 commits não enviados)"
    )
    assert resultado.metrics[0].value == 2


def test_branch_sem_remoto_conta_como_pendente():
    """Dado um repositório sem remoto, então ele conta como pendente (sem cópia fora)."""
    repos = Repos()
    repos.repo("rascunho", remoto=False)

    resultado, _ = repos.rodar()

    assert resultado.status is Status.WARN
    assert "rascunho (sem remoto)" in resultado.summary


def test_so_subpastas_diretas_que_sao_repositorios_sao_verificadas():
    """Dadas uma pasta comum e um repositório em D:\\projetos, então só o repositório conta."""
    repos = Repos()
    repos.pasta_comum("downloads")
    repos.repo("winzel")

    resultado, ctx = repos.rodar()

    assert [i.key for i in resultado.items] == ["winzel"]
    assert {c["args"][2] for c in ctx.commands.calls} == {f"{RAIZ}\\winzel"}


def test_comandos_git_usados_sao_status_porcelain_e_rev_list_do_upstream():
    """Dado um repositório, então uso `git status --porcelain` e `git rev-list @{u}..HEAD`."""
    repos = Repos()
    repos.repo("winzel")

    _, ctx = repos.rodar()

    comandos = [c["args"][3:] for c in ctx.commands.calls]
    assert ["status", "--porcelain"] in comandos
    assert ["rev-list", "--count", "@{u}..HEAD"] in comandos


def test_pasta_de_projetos_ausente_fica_indisponivel():
    """Dado que D:\\projetos não existe, então a checagem fica ⚪."""
    resultado = GitReposCheck().run(make_context({}, fs=FakeFileSystem()))

    assert (resultado.status, resultado.summary) == (
        Status.SKIPPED,
        "indisponível: D:\\projetos não existe",
    )


def test_git_nao_instalado_fica_indisponivel():
    """Dado que o git não está instalado, então a checagem fica ⚪."""
    repos = Repos()
    repos.repo("winzel")
    repos.respostas["git_repos:winzel"] = CommandNotFound("git")

    resultado, _ = repos.rodar()

    assert (resultado.status, resultado.summary) == (
        Status.SKIPPED,
        "indisponível: git não encontrado",
    )
