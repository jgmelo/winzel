"""Single source of truth for test markers: phases, areas and `sistema`.

The pytest plugin registers these markers, so `--strict-markers` rejects
anything not listed here. Labels are shown in the test dashboard (Portuguese).
"""

PHASES: dict[str, str] = {
    "fase0": "Fase 0 — infraestrutura",
    "fase1": "Fase 1 — MVP",
    "fase2": "Fase 2 — restante do inventário",
    "fase3": "Fase 3 — milestones e aprovações",
    "fase4": "Fase 4 — métricas e linha do tempo",
    "fase5": "Fase 5 — atualizações, segurança, backup e ações",
}

AREAS: dict[str, str] = {
    "inventario": "Inventário",
    "diff": "Diferenças",
    "milestones": "Milestones",
    "aprovacoes": "Aprovações",
    "armazenamento": "Armazenamento",
    "hardware": "Hardware",
    "atualizacoes": "Atualizações",
    "seguranca": "Segurança",
    "backup": "Backup",
    "banco": "Banco de dados",
    "execucao": "Execução",
    "interface": "Interface",
    "relatorio": "Painel de testes",
}

SYSTEM_MARKER = "sistema"
SYSTEM_LABEL = "integração com o Windows real; excluído por padrão (pytest -m sistema)"

NO_PHASE = "sem-fase"
NO_AREA = "sem-area"
NO_PHASE_LABEL = "Sem fase"
NO_AREA_LABEL = "Sem área"


def phase_label(phase: str) -> str:
    return PHASES.get(phase, NO_PHASE_LABEL)


def area_label(area: str) -> str:
    return AREAS.get(area, NO_AREA_LABEL)


def phase_order(phase: str) -> int:
    keys = list(PHASES)
    return keys.index(phase) if phase in keys else len(keys)


def area_order(area: str) -> int:
    keys = list(AREAS)
    return keys.index(area) if area in keys else len(keys)
