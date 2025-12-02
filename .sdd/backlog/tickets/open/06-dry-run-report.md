# Ticket: 06 Enhanced Dry-Run Report

Spec version: v1.0

## User Problem
- Текущий dry-run просто отключает deletion
- Нет детального preview что будет удалено
- Нет estimated cost savings

## Outcome / Success Signals
- Dry-run показывает полный список ресурсов к удалению
- Группировка по типу и региону
- Опциональный cost estimate

## Context
- `.sdd/project.md`: Definition of Done — "Имеет dry-run режим для предварительного просмотра"
- `.sdd/best_practices.md`: Section 6 — "Dry-run is default; destructive actions require explicit --execute flag"

## Objective & Definition of Done
Улучшить dry-run режим с детальным отчётом.

- [ ] Dry-run выводит structured report всех найденных ресурсов
- [ ] Группировка: по региону → по типу → список ресурсов
- [ ] Для каждого ресурса: ID, name/tags, age, reason for deletion
- [ ] Summary: total count по типам
- [ ] Опционально: export в JSON/CSV

## Steps
1. Создать `core/report.py` с Report dataclass
2. Добавить `ResourceCandidate` model (id, type, region, tags, age, reason)
3. Реализовать report generation в dry-run mode
4. Добавить `--output-format [text|json|csv]` флаг
5. Добавить summary statistics

## Affected files/modules
- `awswipe/core/report.py` (new)
- `awswipe/cleaner.py` — генерировать report
- `awswipe/cli.py` — output format flag

## Tests
- `pytest tests/core/test_report.py`
- Test: JSON output is valid
- Test: CSV has correct headers

## Risks & Edge Cases
- Large accounts могут иметь тысячи ресурсов
- Mitigation: pagination в output, summary first

## Dependencies
- Upstream: 01-modular-architecture, 02-resource-coverage
- Downstream: нет
