# winzel — SPEC

> Especificação para implementação com o Claude Code.
> Status: **pronta para implementação, a partir da fase 0**. Fases 2 a 5 serão refinadas antes do início de cada uma.

## 1. Visão e objetivo

Instalações do Windows se degradam com o tempo: programas, serviços, tarefas agendadas e itens de inicialização se acumulam, muitas vezes sem que o usuário perceba.

O **winzel** é um utilitário de terminal que **observa, registra e compara** o estado da instalação do Windows ao longo do tempo, destacando o que mudou desde marcos definidos pelo usuário (milestones). Ele apoia a manutenção de uma instalação enxuta.

**Sucesso:** em poucos segundos, o usuário sabe se algo relevante mudou na instalação e o que está pendente (atualizações, espaço, backup, segurança).

## 2. Escopo

### O que o winzel faz

- **Observa:** coleta o inventário (programas, apps da Store, inicialização, tarefas agendadas, serviços, pacotes do pip global, distribuições WSL), as métricas (disco, bateria, SSD) e o estado de atualizações, segurança e backup.
- **Registra:** grava um snapshot local a cada execução.
- **Compara:** mostra diferenças em relação a um milestone ou ao último snapshot; permite aprovar mudanças esperadas.
- **Alerta:** status 🟢🟡🔴 por área, com limites configuráveis.
- **Mostra a evolução:** linha do tempo das contagens e métricas, com milestones marcados.
- **Age, de forma limitada** (fase final): conjunto fechado de ações conhecidas, sempre com confirmação explícita.
- **Documenta a si mesmo:** gera o painel de testes em HTML a cada commit (seção 9).

### O que o winzel não faz

- Não altera o sistema sem confirmação; nunca desinstala ou remove nada automaticamente.
- Não roda em segundo plano (não é serviço nem tarefa agendada). Snapshots agendados ficam fora da versão 1.
- Não envia dados para fora da máquina; sem telemetria.
- Não coleta conteúdo sensível: apenas metadados (nomes, versões, datas, tamanhos).
- Não substitui o antivírus nem detecta malware.
- Não é gerenciador de pacotes; delega ao winget.
- Suporta apenas Windows 11, nesta máquina.

### Princípios de comportamento

- **Somente leitura por padrão.**
- **Falha com elegância:** uma checagem que falha ou estoura o tempo aparece como erro, sem afetar as demais.
- **Rápido:** a execução completa leva segundos.
- **Dados legíveis:** SQLite local, consultável pelo usuário.
- **Administrador:** checagens que exigem elevação aparecem como **"pulada"** quando o winzel não é executado como administrador.

## 3. Ambiente e stack

| Item | Definição |
|---|---|
| Sistema | Windows 11 Home Single Language x64 (ASUS Vivobook S14, 32 GB) |
| Terminal | Windows Terminal |
| Python | 3.14, em venv na pasta do projeto (`.venv`); Python global sem pacotes |
| Dependências | Declaradas no `pyproject.toml`; `requirements-lock.txt` (via `pip freeze`) versionado |
| Execução | `textual`, `textual-plotext`, `matplotlib`, `psutil` |
| Desenvolvimento | `pytest`, `pygments`, `ruff` |
| Biblioteca padrão | `sqlite3`, `tomllib`, `subprocess`, `json` |
| PowerShell | Windows PowerShell 5.1 via `subprocess` (`-NoProfile -NonInteractive`); saída em JSON (`ConvertTo-Json`) e UTF-8 forçado |
| Módulos PowerShell | `Microsoft.WinGet.Client` |
| Armazenamento | SQLite com versão de esquema (`PRAGMA user_version`) e migrações |
| Código | `D:\projetos\winzel` (Dev Drive), repositório privado no GitHub (SSH) |
| Dados | `%LOCALAPPDATA%\winzel\winzel.db` (fora do repositório) |
| Configuração | Padrão dentro do pacote; do usuário em `%APPDATA%\winzel\config.toml` |
| Git hook | Scripts em `scripts/hooks/`, ativados com `git config core.hooksPath scripts/hooks` |

## 4. Conceitos

| Conceito | Definição |
|---|---|
| Snapshot | Registro completo do inventário e das métricas, gravado a cada execução |
| Linha de base | O primeiro snapshot gravado; referência padrão nas fases 1 e 2. É definida **por categoria**: o primeiro snapshot em que a checagem daquela categoria rodou sem erro e sem ser pulada. A partir da fase 3, registrada automaticamente como o milestone `linha-de-base` |
| Milestone | Snapshot fixado e nomeado pelo usuário, com nota |
| Diferença | Comparação entre dois snapshots, por categoria: adicionados, removidos e alterados (versão) |
| Aprovação | Item marcado como esperado; sai da contagem de alertas |

## 5. Checagens

IDs em inglês (código); rótulos em português (interface).

**Status:** 🟢 ok · 🟡 atenção · 🔴 problema · ⚪ pulada/indisponível (sem admin, disco ausente) · ❗ erro na checagem.

Todos os limites ficam no `config.toml`.

### 5.1 Inventário

Gera itens comparáveis entre snapshots. Cada item tem **chave** estável e **versão** (ou atributo equivalente) separada.

| ID | Checagem | Fonte e filtro | Chave | Versão/atributo | Admin | Fase |
|---|---|---|---|---|---|---|
| `programs` | Programas instalados | Registro `...\CurrentVersion\Uninstall` em HKLM (64 bits e `WOW6432Node`) e HKCU; ignora entradas sem `DisplayName` ou com `SystemComponent = 1`; o mesmo programa em mais de uma fonte vira um item só (com a lista de fontes) | `nome normalizado\|fabricante` (seção 12, risco 1) | `DisplayVersion` | Não | 1 |
| `startup` | Inicialização | Chaves `Run`/`RunOnce` (HKCU, HKLM, 32 bits) e pastas Startup (usuário e comum); estado via `...\Explorer\StartupApproved` | `nome\|local` | comando + ligado/desligado | Não | 1 |
| `store_apps` | Apps da Store | `Get-AppxPackage` do usuário atual, sem frameworks, pacotes de recurso nem apps com `SignatureKind = System`; o mesmo pacote em mais de uma arquitetura vira um item só | nome do pacote (`Name`) | versão | Não | 2 |
| `scheduled_tasks` | Tarefas agendadas de terceiros | `Get-ScheduledTask`, fora de `\Microsoft\` | `caminho\|nome` | ações (executável + argumentos, ou `COM {ClassId}`) + habilitada/desabilitada. O estado ao vivo (`Running`/`Ready`) não conta | Não | 2 |
| `services` | Serviços de terceiros | `Get-CimInstance Win32_Service`, com executável (`PathName`, sem aspas nem argumentos, com `%SystemRoot%` expandido, sem diferenciar maiúsculas) fora de `C:\Windows`; serviços sem `PathName` ficam de fora | nome do serviço (minúsculas) | modo de início (automático, automático (atrasado), manual, desativado) + executável. O estado (rodando/parado) não conta | Não | 2 |
| `pip_global` | Pacotes do Python global | `python -m pip list --format=json` no Python global: `checks.pip_global.python` do `config.toml` (caminho ou lista) ou, por padrão, `py -3.14`, sempre sem `VIRTUAL_ENV` no ambiente. Antes, o interpretador informa seu caminho e se é um venv (venv → ❗; Python não encontrado → ⚪). O caminho aparece no resumo | pacote (nome PEP 503) | versão | Não | 2 |
| `wsl_distros` | Distribuições WSL | `wsl -l -v` (UTF-16 LE; colunas lidas pela posição, pois o cabeçalho é traduzido). WSL não instalado ou sem distros → 🟢 com 0 itens; outro erro → ❗ | nome (minúsculas) | versão do WSL (1/2). Estado e distro padrão não contam | Não | 2 |

**Status do inventário:** 🟢 sem mudanças não aprovadas desde o milestone de referência; 🟡 com mudanças não aprovadas. Em `pip_global`, qualquer pacote além do `pip` resulta em 🟡.

**Limitações conhecidas** (documentar nos testes):

- `programs`: programas portáteis não aparecem; entradas órfãs aparecem.
- `services`: serviços de terceiros em `System32` escapam do filtro; serviços da Microsoft fora de `C:\Windows` aparecem (aprováveis). Drivers de kernel ficam fora do escopo.
- Um mesmo programa pode aparecer em `programs` e em `store_apps` (instalado pelos dois meios).
- `scheduled_tasks`: sem elevação, o Windows esconde algumas tarefas. Por isso, essa categoria só é comparada com uma linha de base feita com a **mesma elevação**; com elevação diferente, fica ⚪ "não comparada" (os itens são gravados).
- `services`: executável sem `.exe` e sem aspas (ex.: Docker) é guardado com a linha de comando inteira, pois não dá para separar argumentos de espaços no caminho.
- `wsl_distros`: o aviso de "nenhuma distribuição" é reconhecido pelo código `WSL_E_DEFAULT_DISTRO_NOT_FOUND` ou pela frase em português/inglês.

### 5.2 Métricas

Valores numéricos ao longo do tempo.

| ID | Checagem | Fonte | Status padrão | Admin | Fase |
|---|---|---|---|---|---|
| `disk_c` | Espaço livre no C: | `psutil` | 🟡 < 20% · 🔴 < 10% | Não | 4 |
| `dev_drive` | Tamanho do VHDX e espaço livre no Dev Drive | Tamanho do arquivo + `psutil` | 🟡 < 20% livre | Não | 4 |
| `clutter` | Tamanho das sandboxes e da pasta Temp | Tamanho das pastas | 🟡 > 5 GB | Não | 4 |
| `battery` | Capacidade atual vs. de projeto | `powercfg /batteryreport /xml` | 🟡 < 80% · 🔴 < 60% | Pode exigir | 4 |
| `ssd` | Desgaste e temperatura do SSD | `Get-StorageReliabilityCounter` | 🟡 desgaste > 50% | Sim | 4 |

### 5.3 Atualizações, segurança e backup

| ID | Checagem | Fonte | Status padrão | Admin | Fase |
|---|---|---|---|---|---|
| `winget_updates` | Pacotes com atualização | `Get-WinGetPackage` (`Microsoft.WinGet.Client`) | 🟡 se houver alguma | Não | 5 |
| `windows_update` | Atualizações pendentes | COM `Microsoft.Update.Session` (lenta; timeout próprio) | 🟡 se houver alguma | Não | 5 |
| `defender` | Proteção ativa e idade das assinaturas | `Get-MpComputerStatus` | 🔴 desativado · 🟡 > 3 dias | Não | 5 |
| `restore_point` | Último ponto de restauração | `Get-ComputerRestorePoint` | 🟡 > 30 dias | Sim | 5 |
| `encryption` | Criptografia do disco | `Get-BitLockerVolume` | 🟡 desativada | Sim | 5 |
| `disk_image` | Idade da última imagem de disco | Pasta configurada no SSD externo | 🟡 > 60 dias · ⚪ disco ausente | Não | 5 |
| `git_repos` | Repositórios com pendências | `git status --porcelain` e `git rev-list @{u}..HEAD` nos repositórios de `D:\projetos` | 🟡 com alterações não enviadas | Não | 5 |

## 6. Modelo de dados

SQLite em `%LOCALAPPDATA%\winzel\winzel.db`.

### 6.1 Tabelas

| Tabela | Colunas | Função |
|---|---|---|
| `snapshots` | `id`, `created_at`, `kind` (`auto`/`manual`), `is_admin` | Uma linha por execução. `auto`: gravado ao abrir a interface (ou com `r`); `manual`: gravado por `python -m winzel snapshot` |
| `check_runs` | `snapshot_id`, `check_id`, `status`, `summary`, `duration_ms`, `error` | Resultado de cada checagem no snapshot |
| `items` | `snapshot_id`, `category`, `key`, `version`, `details_json` | Inventário completo do snapshot |
| `metrics` | `snapshot_id`, `name`, `value`, `unit` | Valores numéricos do snapshot |
| `milestones` | `snapshot_id`, `name` (único), `note`, `created_at` | Marcos nomeados |
| `approvals` | `category`, `key`, `change` (`added`/`removed`), `approved_at`, `reason` | Mudanças aprovadas |

- `check_runs` distingue **"item sumiu"** de **"não foi possível verificar"**: se a checagem de uma categoria foi pulada ou deu erro em um snapshot, os itens dessa categoria não são comparados.
- `is_admin` registra se o snapshot foi feito com elevação.

### 6.2 Regras de diferença e aprovação

- **Adicionado:** chave presente no snapshot atual e ausente na referência.
- **Removido:** chave presente na referência e ausente no atual.
- **Alterado:** mesma chave, versão/atributo diferente. **Informativo:** aparece na aba Mudanças, mas **não afeta o status**.
- **Aprovação** vale para o item (`category` + `key`) e o tipo de mudança, **em qualquer versão**. Um item aprovado como adicionado que depois for removido gera uma nova mudança não aprovada.
- O status do inventário (🟢/🟡) considera apenas adicionados e removidos não aprovados.

### 6.3 Retenção

- Milestones e seus snapshots: mantidos para sempre.
- Snapshots automáticos com mais de 90 dias: reduzidos a um por mês.

### 6.4 Evolução do esquema

- Versão gravada em `PRAGMA user_version`.
- Migrações numeradas e sequenciais, aplicadas automaticamente na abertura do banco.
- Cada migração tem teste (banco na versão anterior → migrado → dados preservados).

## 7. Arquitetura e estrutura do projeto

### 7.1 Camadas

1. **Coleta:** cada checagem obtém dados brutos (PowerShell, registro, arquivos).
2. **Interpretação:** funções **puras** transformam dados brutos em itens, métricas e status (onde fica a lógica testável).
3. **Armazenamento:** grava e lê snapshots no SQLite.
4. **Análise:** diferenças, aprovações e status geral.
5. **Apresentação:** interface Textual, gráficos e modo sem interface.

### 7.2 Contrato de uma checagem

```python
@dataclass
class Item:
    category: str
    key: str
    version: str | None
    details: dict


@dataclass
class Metric:
    name: str
    value: float
    unit: str


@dataclass
class CheckResult:
    check_id: str
    status: Status
    summary: str
    items: list[Item]
    metrics: list[Metric]
    error: str | None
    duration_ms: int


class Check(Protocol):
    id: str
    label: str  # rótulo em português, exibido na interface
    area: str
    requires_admin: bool
    timeout_s: float

    def run(self, ctx: Context) -> CheckResult: ...
```

- Uma checagem nova é um arquivo novo em `checks/` que cumpre o contrato e se registra no registro de checagens; nenhuma outra parte precisa mudar.
- Todo `Check` tem testes no formato "dado este dado bruto de exemplo, devolve estes itens/métricas e este status".

### 7.3 Context (injeção de dependência)

Objeto entregue a `run()` com tudo o que a checagem precisa do mundo externo:

| Campo | Produção | Testes |
|---|---|---|
| Executor do PowerShell | Executa `powershell.exe` (UTF-8, JSON, timeout) | Falso que devolve JSONs de `tests/data/` |
| Executor de comandos | Executa `pip`, `wsl` etc. (bytes, timeout, variáveis removidas do ambiente) | Falso que responde por rótulo |
| Configuração | `default_config.toml` + `%APPDATA%\winzel\config.toml` | Configuração de teste |
| `is_admin` | Detectado no início | Definido pelo teste |
| Relógio | Hora atual | Relógio parado em data fixa |

As checagens nunca acessam o sistema, a configuração ou a hora diretamente; sempre pelo `Context`. Leituras de registro e de arquivos também passam por ele (via PowerShell ou por um leitor injetável).

### 7.4 Execução

- Checagens em paralelo (threads), cada uma com seu `timeout_s`.
- `requires_admin` sem elevação → status ⚪ **pulada**, sem executar.
- Exceção ou tempo esgotado → status ❗ **erro**, com mensagem; as demais seguem normalmente.
- O resultado de todas as checagens forma um snapshot, gravado de uma vez (transação).

### 7.5 Pontos de entrada

- `python -m winzel`: abre a interface Textual (roda as checagens e grava um snapshot ao abrir).
- `python -m winzel snapshot`: roda as checagens, grava o snapshot e imprime um resumo, sem interface. Disponível desde a fase 1.

### 7.6 Estrutura (layout `src`)

```
winzel/
├── pyproject.toml
├── requirements-lock.txt
├── README.md
├── SPEC.md
├── src/winzel/
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── default_config.toml
│   ├── models.py            # dataclasses e Status
│   ├── context.py
│   ├── powershell.py        # executor (UTF-8, JSON, timeout)
│   ├── runner.py            # execução paralela
│   ├── diff.py
│   ├── status.py
│   ├── store/               # db.py + migrations/
│   ├── checks/              # uma checagem por arquivo + registro
│   ├── ui/                  # app Textual e telas
│   └── plots.py             # matplotlib em processo separado
├── tools/test_dashboard/    # gerador do painel de testes
├── tests/
│   ├── conftest.py
│   ├── data/                # saídas de exemplo do PowerShell
│   └── test_*.py
├── docs/testes/             # index.html + historico/
└── scripts/hooks/pre-commit
```

## 8. Interface

Aplicação Textual, em português.

### 8.1 Ao abrir

1. Exibe o progresso das checagens (⏳ → status de cada uma).
2. Grava o snapshot automático.
3. Abre a aba **Visão geral**.

### 8.2 Abas

| Aba | Fase | Conteúdo |
|---|---|---|
| **Visão geral** | 1 | Cartões por área com status e resumo de uma linha (ex.: "Programas 🟡 3 novos desde *linha de base*"). Topo: referência atual e data/hora do snapshot; aviso se o snapshot foi feito sem admin |
| **Mudanças** | 1 (básica), 3 (completa) | Tabela: tipo (➕ adicionado, ➖ removido, 🔄 alterado), categoria, item, versão anterior → atual. Filtros por categoria e tipo. Fase 3: seletor de milestone de referência e aprovação de itens |
| **Linha do tempo** | 4 | Minigráfico no terminal (`textual-plotext`) + gráfico detalhado no matplotlib, em processo separado, com milestones como linhas verticais rotuladas |
| **Ações** | 5 | Lista fechada de ações (ex.: atualizar pacotes do winget, esvaziar sandboxes, criar milestone), cada uma com confirmação explícita |

### 8.3 Teclas

`r` atualizar · `m` novo milestone · `a` aprovar item · `p` abrir gráfico · `Tab` trocar de aba · `q` sair.

Cada tecla só existe a partir da fase em que sua função é implementada.

### 8.4 Referência para comparação

- Fases 1 e 2: a **linha de base** (primeiro snapshot gravado).
- A partir da fase 3: o **último milestone**, trocável pelo seletor na aba Mudanças, que também oferece **"último snapshot"** como referência.

## 9. Testes

Os testes têm duas funções:

1. **Gate:** uma fase só é concluída, e a próxima só começa, quando todos os testes passam.
2. **Documentação principal:** o usuário entende as capacidades do winzel lendo os testes e o código deles, raramente o código do utilitário.

### Convenções

- Toda funcionalidade nova vem acompanhada de testes, de preferência escritos antes.
- **Nome do teste em português**, descritivo como uma especificação: `test_programa_novo_aparece_como_adicionado_desde_a_linha_de_base`.
- **Docstring** de uma linha no formato *Dado… quando… então…*.
- Código dos testes legível: preparação, ação e verificação claramente separadas.
- **Markers:**
  - fase: `fase0`, `fase1`, …
  - área: `inventario`, `diff`, `milestones`, `aprovacoes`, `armazenamento` (métricas de disco), `hardware`, `atualizacoes`, `seguranca`, `backup`, `banco` (SQLite e migrações), `execucao` (runner, Context, PowerShell), `interface`, `relatorio` (painel de testes)
  - `sistema`: integração com o Windows real; excluído por padrão (`pytest -m sistema` para rodar).
- **Isolamento:** checagens testadas com saídas de exemplo do PowerShell em `tests/data/` e SQLite em memória.

### Gate por commit (pre-commit hook)

1. Roda a suíte completa (exceto `sistema`).
2. Se algum teste falhar, **o commit é bloqueado**.
3. Se todos passarem, gera o painel de testes e o histórico, e os inclui no mesmo commit.
4. Para que o conteúdo testado seja exatamente o do commit, o hook recusa commits com alterações não incluídas (arquivos modificados fora do *stage* ou novos não rastreados, exceto em `docs/testes/`).

Todo teste declara um marker de fase e um de área; a suíte se recusa a rodar se faltar algum. Os markers são registrados a partir de `tools/test_dashboard/taxonomy.py` (fonte única), e `--strict-markers` rejeita os demais.

### Painel de testes (HTML)

Arquivo versionado em `docs/testes/index.html`, gerado a cada commit.

- **Cabeçalho:** commit anterior (hash e mensagem), branch, data e hora, totais (aprovados, falhos, pulados) e duração. O conteúdo testado é exatamente o do commit que contém o relatório.
- **Agrupamento** por fase e por área, cada grupo com seu sumário.
- **Por teste:** nome legível (sem `test_`, com espaços), docstring, status (✅ ❌ ⏭️), duração e **código do teste**, recolhível e com destaque de sintaxe (pygments).
- **Mapa de capacidades:** visão-resumo só com as docstrings, por área ("o que o winzel sabe fazer hoje").
- **Evolução:** contagem de testes por área e fase ao longo dos commits, a partir do histórico.

**Histórico:** um resumo em JSON por commit em `docs/testes/historico/`.

## 10. Fases e critérios de aceite

Uma fase só é concluída com todos os testes (desta e das anteriores) passando e seus critérios de aceite atendidos.

| Fase | Conteúdo |
|---|---|
| 0 | Infraestrutura: estrutura do projeto, ambiente, ruff, pytest, gerador do painel de testes (com seus próprios testes) e pre-commit hook |
| 1 (MVP) | `programs` e `startup`; snapshot; diferença em relação à linha de base; abas Visão geral e Mudanças (básica); modo `snapshot` sem interface |
| 2 | Restante do inventário: `store_apps`, `scheduled_tasks`, `services`, `pip_global`, `wsl_distros` |
| 3 | Milestones nomeados e aprovações |
| 4 | Métricas e aba Linha do tempo |
| 5 | Atualizações, segurança, backup e aba Ações |

### Critérios de aceite

**Fase 0 — infraestrutura**

- `pip install -e .[dev]` em um venv limpo funciona; `requirements-lock.txt` gerado.
- `ruff check` e `ruff format --check` passam.
- `pytest` roda e gera `docs/testes/index.html` com cabeçalho, agrupamento por fase e área, docstrings, código recolhível e mapa de capacidades.
- O gerador do painel de testes tem testes próprios (ex.: "teste falho aparece com ❌ e mensagem resumida").
- Pre-commit verificado nos dois sentidos:
  - **bloqueio:** com um teste falhando de propósito, `git commit` é cancelado e nada é gravado;
  - **inclusão:** com todos os testes passando, o commit contém o `index.html` atualizado e o novo JSON do histórico.
- O histórico grava um JSON por commit.

**Fase 1 — MVP**

- `programs` e `startup` geram itens corretos a partir de JSONs de exemplo, incluindo filtros (`SystemComponent`, 32/64 bits, HKCU) e estado ligado/desligado da inicialização.
- O primeiro snapshot vira a linha de base; os seguintes mostram adicionados, removidos e alterados em relação a ela.
- Checagem com erro ou tempo esgotado não afeta as demais, e seus itens não são comparados.
- `python -m winzel snapshot` grava o snapshot e imprime o resumo.
- A interface abre, mostra o progresso, a Visão geral e a aba Mudanças com filtros.
- Teste de integração (marker `sistema`) executa as duas checagens no Windows real sem erro.

**Fases 2 a 5** (refinadas antes do início de cada fase)

- Cada checagem testada a partir de dados de exemplo, incluindo suas limitações conhecidas.
- Milestones e aprovações seguem as regras da seção 6.2.
- Limites de status do `config.toml` testados nas fronteiras (ex.: exatamente 20% livre).
- Cada ação tem teste garantindo que nada é executado sem confirmação.

## 11. Convenções

- **Código** (identificadores, comentários técnicos): inglês.
- **Interface, nomes e docstrings dos testes, painel de testes:** português.
- **Estilo:** `ruff` (formatação e lint).
- **Commits:** Conventional Commits, com prefixo em inglês e descrição em português (`feat: checagem de inicialização`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`).
- **Branches:** trabalho direto na `main`; tag ao concluir cada fase (`fase-0`, `fase-1`, …).

### Regras para o Claude Code

- Trabalhar **uma fase por vez** e **parar ao fim de cada fase** para revisão do usuário.
- **Nunca** usar `git commit --no-verify` nem desativar, pular ou afrouxar testes para fazê-los passar.
- Diante de ambiguidade nesta SPEC, **perguntar** em vez de supor; quando uma decisão mudar, atualizar esta SPEC no mesmo commit.

## 12. Riscos e decisões técnicas

| # | Risco | Decisão |
|---|---|---|
| 1 | Nomes de programas com versão embutida (ex.: "Python 3.14.0 (64-bit)") fariam uma atualização aparecer como removido + adicionado | Normalizar a chave removendo padrões de versão do nome; guardar o nome original em `details`; cobrir com testes. Regra: minúsculas; remove números com ponto, com ou sem prefixo `v` (`3.14.0`, `v2.1`, `14.40.33810`) e separadores que sobrarem; mantém arquitetura e anos (`(x64)`, `2015-2022`), para que 32 e 64 bits sejam itens distintos. Limitação: números sem ponto ("Java 8 Update 401") permanecem |
| 2 | Cada chamada ao PowerShell leva ~0,5–1 s para iniciar | Agrupar consultas em uma mesma chamada quando possível |
| 3 | `wsl.exe` imprime em UTF-16, diferente das demais fontes | Decodificação específica, com teste |
| 4 | Emojis podem desalinhar tabelas no Windows Terminal | Alternativa em texto (`[OK]`, `[!]`, `[X]`) configurável |
| 5 | Caminhos variam entre máquinas e ao longo do tempo | Configuráveis no `config.toml`, com padrões: pasta de projetos (`D:\projetos`), letra do Dev Drive e caminho do VHDX, pasta das imagens de disco e pasta das sandboxes |
| 6 | O Git executa hooks via bash (Git for Windows) | O script do hook chama o Python do venv (`.venv/Scripts/python.exe`) |
