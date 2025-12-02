# Ticket: 05 YAML Configuration File

Spec version: v1.0

## User Problem
- Все настройки через CLI флаги — неудобно для сложных конфигураций
- Нет возможности сохранить и переиспользовать конфигурацию
- Нет tag-based filtering

## Outcome / Success Signals
- Конфигурация через YAML файл
- Tag filters для selective cleanup
- Exclude patterns для защиты ресурсов

## Context
- `.sdd/project.md`: Definition of Done — "Поддержка фильтрации по тегам/регионам"
- `.sdd/best_practices.md`: Section 8 "Priority 3 — Tagging" — tag schemas and policies

## Objective & Definition of Done
Добавить поддержку YAML конфигурационного файла.

- [ ] Поддержка `--config config.yaml` флага
- [ ] YAML schema: regions, resource_types, tag_filters, exclude_patterns
- [ ] Валидация конфига при загрузке
- [ ] CLI флаги override config file values
- [ ] Пример конфига в репозитории

## Steps
1. Создать `core/config.py` с Config dataclass и YAML loader
2. Определить schema:
   ```yaml
   regions: [us-east-1, eu-west-1]  # or "all"
   resource_types: [ec2, s3, lambda]  # or "all"
   tag_filters:
     include:
       Environment: [dev, test]
     exclude:
       DoNotDelete: ["true"]
   exclude_patterns:
     - "prod-*"
     - "critical-*"
   dry_run: true
   ```
3. Добавить pydantic или dataclass validation
4. Интегрировать в CLI
5. Создать `config.example.yaml`

## Affected files/modules
- `awswipe/core/config.py` (new/update)
- `awswipe/cli.py` — добавить --config
- `config.example.yaml` (new)
- `requirements.txt` — добавить PyYAML

## Tests
- `pytest tests/core/test_config.py`
- Test: invalid YAML → clear error
- Test: CLI overrides config

## Risks & Edge Cases
- Typos в config могут привести к unexpected behavior
- Mitigation: strict validation, unknown keys → warning

## Dependencies
- Upstream: 01-modular-architecture
- Downstream: нет
