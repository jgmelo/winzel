-- 0002: fase 3 (milestones, aprovações e comparação com referência escolhida)

-- Situação da coleta e resumo próprios da checagem, antes da comparação.
-- `status`/`summary` continuam guardando o resultado já comparado.
ALTER TABLE check_runs ADD COLUMN raw_status TEXT NOT NULL DEFAULT 'ok';
ALTER TABLE check_runs ADD COLUMN raw_summary TEXT NOT NULL DEFAULT '';

-- Dados anteriores: falha (pulada/erro) continua falha, exceto as tarefas agendadas
-- "não comparadas" por elevação, cujos itens foram coletados normalmente.
UPDATE check_runs SET raw_status = CASE
    WHEN status IN ('skipped', 'error')
         AND summary NOT LIKE '%não comparada: linha de base feita%' THEN status
    ELSE 'ok'
END;

UPDATE check_runs SET raw_summary = CASE
    WHEN raw_status <> 'ok' THEN summary
    WHEN instr(summary, ' — ') > 0 THEN substr(summary, 1, instr(summary, ' — ') - 1)
    ELSE summary
END;

-- Nomes de milestones são únicos sem diferenciar maiúsculas.
CREATE UNIQUE INDEX milestones_name_nocase ON milestones (name COLLATE NOCASE);

-- A linha de base vira o milestone `linha-de-base` (primeiro snapshot).
INSERT INTO milestones (snapshot_id, name, note, created_at)
SELECT id, 'linha-de-base', 'Registrado automaticamente: primeiro snapshot.', created_at
FROM snapshots
WHERE id = (SELECT MIN(id) FROM snapshots)
  AND NOT EXISTS (SELECT 1 FROM milestones WHERE name = 'linha-de-base');
