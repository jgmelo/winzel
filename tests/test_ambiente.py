"""Ambiente de desenvolvimento: o pacote e suas dependências estão instalados."""

import importlib
import sys

import pytest

pytestmark = [pytest.mark.fase0, pytest.mark.execucao]


def test_python_e_da_versao_3_14_ou_superior():
    """Dado o venv do projeto, quando os testes rodam, então o Python é 3.14 ou superior."""
    versao = sys.version_info

    assert versao >= (3, 14)


def test_pacote_winzel_esta_instalado_e_informa_sua_versao():
    """Dado `pip install -e .[dev]`, quando importo `winzel`, então ele expõe `__version__`."""
    import winzel

    assert winzel.__version__


@pytest.mark.parametrize(
    "modulo",
    ["textual", "textual_plotext", "matplotlib", "psutil", "pygments", "pytest"],
)
def test_dependencias_de_execucao_e_desenvolvimento_estao_disponiveis(modulo):
    """Dado o venv instalado, quando importo cada dependência declarada, então ela existe."""
    importlib.import_module(modulo)
