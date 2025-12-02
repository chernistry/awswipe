# Ticket: 04 Structured JSON Logging

Spec version: v1.0

## User Problem
- Текущий logging использует простой text format
- Сложно парсить логи для анализа и мониторинга
- Нет correlation IDs для трейсинга операций

## Outcome / Success Signals
- Логи в JSON формате с consistent schema
- Каждый run имеет уникальный run_id
- Логи легко парсить и анализировать

## Context
- `.sdd/project.md`: Non-functional Requirements — "Structured logging, итоговый отчёт"
- `.sdd/best_practices.md`: Section 10 "Observability" — "Structured JSON logs with correlation IDs"

## Objective & Definition of Done
Внедрить structured JSON logging с correlation IDs.

- [ ] JSON формат логов (опционально, через флаг `--json-logs`)
- [ ] Каждый лог содержит: timestamp, level, run_id, region, resource_type, resource_id, action, message
- [ ] Никаких секретов в логах
- [ ] Human-readable формат по умолчанию, JSON опционально

## Steps
1. Создать `core/logging.py` с custom JSON formatter
2. Добавить `run_id` генерацию (UUID) при старте
3. Создать LogContext dataclass для structured fields
4. Обновить все logging calls использовать structured format
5. Добавить `--json-logs` флаг в CLI

## Affected files/modules
- `awswipe/core/logging.py` (update)
- `awswipe/cli.py` — добавить флаг
- Все модули с logging calls

## Tests
- `pytest tests/core/test_logging.py`
- Verify JSON output is valid JSON
- Verify no secrets in logs

## Risks & Edge Cases
- Performance overhead от JSON serialization (minimal)
- Backwards compatibility с существующими log parsers

## Dependencies
- Upstream: 01-modular-architecture
- Downstream: нет
