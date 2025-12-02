# Ticket: 03 Resource Dependency Graph

Spec version: v1.0

## User Problem
- Текущий `resolve_dependencies()` неполный и hardcoded
- Удаление в неправильном порядке приводит к ошибкам (e.g., VPC before instances)
- Нет автоматического определения порядка удаления

## Outcome / Success Signals
- Топологическая сортировка ресурсов перед удалением
- Зависимости декларативно описаны в каждом ResourceCleaner
- Ошибки "resource in use" минимизированы

## Context
- `.sdd/project.md`: Definition of Done — "Обрабатывает зависимости между ресурсами (порядок удаления)"
- `.sdd/best_practices.md`: Section 6 — "Deletion requires passing all rules"

## Objective & Definition of Done
Реализовать корректный граф зависимостей и топологическую сортировку для удаления.

- [ ] Каждый ResourceCleaner декларирует свои зависимости
- [ ] Реализован топологический sort (Kahn's algorithm или DFS)
- [ ] Циклические зависимости детектируются и логируются
- [ ] Порядок удаления: EC2 → EBS → Security Groups → Subnets → VPC

## Steps
1. Добавить `dependencies: List[str]` в базовый класс ResourceCleaner
2. Создать `core/dependency_resolver.py` с топологической сортировкой
3. Обновить каждый cleaner с правильными зависимостями
4. Интегрировать resolver в основной cleanup flow
5. Добавить detection циклических зависимостей

## Affected files/modules
- `awswipe/resources/base.py` — добавить dependencies
- `awswipe/core/dependency_resolver.py` (new)
- `awswipe/cleaner.py` — использовать resolver
- Все `awswipe/resources/*.py` — добавить dependencies

## Tests
- `pytest tests/core/test_dependency_resolver.py`
- Test case: циклическая зависимость → error
- Test case: VPC cleanup order correct

## Risks & Edge Cases
- Циклические зависимости (редко, но возможно)
- Неизвестные зависимости для новых сервисов
- Mitigation: fallback на sequential deletion с retries

## Dependencies
- Upstream: 01-modular-architecture, 02-resource-coverage
- Downstream: нет
