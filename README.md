# winzel

Utilitário de terminal que **observa, registra e compara** o estado da instalação do
Windows 11 ao longo do tempo. A especificação completa está em [`SPEC.md`](SPEC.md).

**Estado atual:** fase 1 (MVP: programas e inicialização). O painel de testes em
[`docs/testes/index.html`](docs/testes/index.html) mostra o que o winzel sabe fazer hoje.

## Uso

```powershell
.venv\Scripts\python.exe -m winzel            # interface (grava um snapshot ao abrir)
.venv\Scripts\python.exe -m winzel snapshot   # sem interface: grava e imprime o resumo
```

Opções: `--db CAMINHO` (padrão `%LOCALAPPDATA%\winzel\winzel.db`) e `--config CAMINHO`
(padrão `%APPDATA%\winzel\config.toml`). Teclas: `Tab` troca de aba, `r` atualiza, `q` sai.

## Ambiente de desenvolvimento (Windows)

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
git config core.hooksPath scripts/hooks
```

Para atualizar o `requirements-lock.txt`:

```powershell
.venv\Scripts\python.exe -m pip freeze --exclude-editable > requirements-lock.txt
```

## Testes

```powershell
.venv\Scripts\python.exe -m pytest              # suíte completa, exceto `sistema`; gera o painel
.venv\Scripts\python.exe -m pytest -m sistema   # integração com o Windows real
.venv\Scripts\python.exe -m pytest --sem-painel # sem regenerar docs/testes/index.html
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
```

## Pre-commit

`scripts/hooks/pre-commit` roda a suíte a cada commit:

- algum teste falhou → o commit é bloqueado;
- todos passaram → `docs/testes/index.html` e um novo JSON em `docs/testes/historico/`
  entram no mesmo commit;
- há alterações fora do commit → o commit é bloqueado (inclua com `git add` ou guarde com
  `git stash push --keep-index --include-untracked`).

O hook usa `.venv/Scripts/python.exe` (ou `.venv/bin/python`); a variável `WINZEL_PYTHON`
substitui esse caminho.
