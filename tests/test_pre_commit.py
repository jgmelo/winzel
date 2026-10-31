"""Pre-commit hook: bloqueia commits com testes falhando e inclui o painel nos aprovados.

Cada teste cria um repositório Git temporário com uma cópia do hook, do gerador do
painel e uma suíte mínima, e faz commits de verdade.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.fase0, pytest.mark.relatorio]

PROJETO = Path(__file__).resolve().parents[1]

PYPROJECT = """
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = ["-p", "tools.test_dashboard.plugin", "-p", "no:cacheprovider"]
"""

TESTE_APROVADO = '''
import pytest

pytestmark = [pytest.mark.fase0, pytest.mark.relatorio]


def test_aprovado():
    """Dado nada, então passa."""
'''

TESTE_FALHO = (
    TESTE_APROVADO
    + '''

def test_falho_de_proposito():
    """Dado um erro proposital, então falha."""
    assert False
'''
)


class Repo:
    """Repositório Git temporário com o hook do winzel ativado."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env["WINZEL_PYTHON"] = sys.executable
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.raiz,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=check,
        )

    def escrever(self, caminho: str, conteudo: str) -> None:
        arquivo = self.raiz / caminho
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(conteudo, encoding="utf-8")

    def commit(self, mensagem: str) -> subprocess.CompletedProcess:
        self.git("add", "-A")
        return self.git("commit", "-m", mensagem, check=False)

    def arquivos_do_head(self) -> list[str]:
        return self.git("show", "--name-only", "--format=", "HEAD").stdout.split()

    def historico_no_head(self) -> list[str]:
        saida = self.git("ls-tree", "--name-only", "HEAD", "docs/testes/historico/").stdout
        return [n for n in saida.split() if n.endswith(".json")]

    def quantidade_de_commits(self) -> int:
        resultado = self.git("rev-list", "--count", "HEAD", check=False)
        return int(resultado.stdout) if resultado.returncode == 0 else 0


@pytest.fixture
def repo(tmp_path) -> Repo:
    if shutil.which("git") is None:
        pytest.skip("git não está instalado")
    repo = Repo(tmp_path / "repo")
    repo.raiz.mkdir()
    repo.git("init", "-q", "-b", "main")
    repo.git("config", "user.name", "Teste")
    repo.git("config", "user.email", "teste@example.com")
    repo.git("config", "core.hooksPath", "scripts/hooks")
    shutil.copytree(PROJETO / "scripts" / "hooks", repo.raiz / "scripts" / "hooks")
    shutil.copytree(
        PROJETO / "tools",
        repo.raiz / "tools",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    repo.escrever("pyproject.toml", PYPROJECT)
    repo.escrever(".gitignore", "__pycache__/\n")
    return repo


def test_com_todos_os_testes_passando_o_commit_inclui_o_painel_e_o_json_do_historico(repo):
    """Dada uma suíte aprovada, quando faço o commit, então ele contém index.html e um JSON novo."""
    repo.escrever("tests/test_exemplo.py", TESTE_APROVADO)

    resultado = repo.commit("chore: início")

    assert resultado.returncode == 0, resultado.stderr
    arquivos = repo.arquivos_do_head()
    assert "docs/testes/index.html" in arquivos
    assert any(a.startswith("docs/testes/historico/") and a.endswith(".json") for a in arquivos)
    assert repo.git("status", "--porcelain").stdout == ""


def test_com_um_teste_falhando_o_commit_e_bloqueado_e_nada_e_gravado(repo):
    """Dado um teste falhando de propósito, quando faço o commit, então ele é cancelado."""
    repo.escrever("tests/test_exemplo.py", TESTE_APROVADO)
    repo.commit("chore: início")
    repo.escrever("tests/test_exemplo.py", TESTE_FALHO)

    resultado = repo.commit("test: teste que falha")

    assert resultado.returncode != 0
    assert "commit bloqueado" in resultado.stderr
    assert repo.quantidade_de_commits() == 1
    assert len(repo.historico_no_head()) == 1


def test_cada_commit_acrescenta_um_json_ao_historico(repo):
    """Dados dois commits aprovados, então o histórico no HEAD tem dois JSONs."""
    repo.escrever("tests/test_exemplo.py", TESTE_APROVADO)
    repo.commit("chore: início")
    repo.escrever("tests/test_outro.py", TESTE_APROVADO)

    resultado = repo.commit("test: outro teste")

    assert resultado.returncode == 0, resultado.stderr
    assert len(repo.historico_no_head()) == 2


def test_alteracoes_fora_do_commit_bloqueiam_para_testar_exatamente_o_conteudo_commitado(repo):
    """Dado um arquivo alterado mas não incluído, quando faço o commit, então ele é bloqueado."""
    repo.escrever("tests/test_exemplo.py", TESTE_APROVADO)
    repo.commit("chore: início")
    repo.escrever("README.md", "novo\n")
    repo.git("add", "README.md")
    repo.escrever("tests/test_exemplo.py", TESTE_FALHO)

    resultado = repo.git("commit", "-m", "docs: readme", check=False)

    assert resultado.returncode != 0
    assert "alterações fora do commit" in resultado.stderr
    assert "tests/test_exemplo.py" in resultado.stderr
    assert repo.quantidade_de_commits() == 1
