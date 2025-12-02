# Ticket: 01 Modular Architecture Refactoring

Spec version: v1.0

## User Problem
- Текущий монолитный скрипт (~900 LOC) сложно поддерживать и расширять
- Добавление новых типов ресурсов требует изменения одного большого файла
- Нет чёткого разделения ответственности

## Outcome / Success Signals
- Код разбит на модули по ответственности
- Добавление нового типа ресурса = создание нового файла в `resources/`
- Тесты можно запускать изолированно для каждого модуля

## Context
- `.sdd/best_practices.md`: Section 16 "Red Flags & Smells" — "Single 2k+ line script doing everything"
- `.sdd/best_practices.md`: Section 14 "Code Quality Standards" — "Small functions with single responsibility; no god modules"

## Objective & Definition of Done
Разбить монолитный `awswipe.py` на модульную структуру с чётким разделением ответственности.

- [ ] Создана структура `awswipe/` пакета
- [ ] Выделен модуль `awswipe/core/` (retry, logging, config)
- [ ] Выделен модуль `awswipe/resources/` с базовым классом и 2-3 примерами
- [ ] CLI остаётся в `awswipe/cli.py`
- [ ] Старый `awswipe.py` заменён на entry point
- [ ] Все существующие функции работают как раньше

## Steps
1. Создать структуру директорий:
   ```
   awswipe/
   ├── __init__.py
   ├── cli.py              # argparse, main()
   ├── cleaner.py          # SuperAWSResourceCleaner (orchestration)
   ├── core/
   │   ├── __init__.py
   │   ├── retry.py        # retry_delete, retry_delete_with_backoff
   │   ├── logging.py      # setup_logging, timed decorator
   │   └── config.py       # Config dataclass
   └── resources/
       ├── __init__.py
       ├── base.py         # ResourceCleaner ABC
       ├── s3.py           # S3BucketCleaner
       └── iam.py          # IAMRoleCleaner
   ```
2. Извлечь retry логику в `core/retry.py`
3. Извлечь logging setup и `timed` decorator в `core/logging.py`
4. Создать базовый класс `ResourceCleaner` в `resources/base.py`
5. Мигрировать S3 и IAM cleaners как примеры
6. Обновить `awswipe.py` как thin wrapper

## Affected files/modules
- `awswipe.py` → разбивается на модули
- Создаются: `awswipe/__init__.py`, `awswipe/cli.py`, `awswipe/cleaner.py`, `awswipe/core/*`, `awswipe/resources/*`

## Tests
- `pytest tests/test_retry.py` — unit tests для retry логики
- `python -m awswipe --help` — CLI работает
- `python -m awswipe --region us-east-1` — dry-run работает

## Risks & Edge Cases
- Circular imports при неправильном разделении
- Потеря функциональности при рефакторинге
- Mitigation: пошаговая миграция с проверкой после каждого шага

## Dependencies
- Upstream: нет
- Downstream: 02, 03, 04, 05
