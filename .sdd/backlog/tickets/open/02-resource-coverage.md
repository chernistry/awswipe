# Ticket: 02 Complete Resource Coverage

Spec version: v1.0

## User Problem
- Текущий скрипт не удаляет многие важные типы ресурсов (EC2, EBS, Lambda, VPC)
- Пользователи ожидают полную очистку аккаунта

## Outcome / Success Signals
- Покрыты все основные типы ресурсов из Definition of Done
- Каждый тип ресурса имеет свой модуль в `resources/`

## Context
- `.sdd/project.md`: Definition of Done — "Удаляет все основные типы ресурсов (EC2, S3, RDS, Lambda, VPC, IAM и т.д.)"
- `.sdd/best_practices.md`: Section 6 "Priority 1 — Safety" — discovery + quarantine + delete lifecycle

## Objective & Definition of Done
Добавить поддержку всех основных типов AWS ресурсов.

- [ ] EC2 instances (terminate)
- [ ] EBS volumes (delete unattached)
- [ ] EBS snapshots (delete)
- [ ] Lambda functions (delete)
- [ ] VPC и связанные ресурсы (subnets, IGW, NAT, security groups)
- [ ] Elastic IPs (release)
- [ ] Load Balancers (ALB/NLB/CLB)
- [ ] Auto Scaling Groups
- [ ] Каждый тип в отдельном файле `resources/<type>.py`

## Steps
1. Создать `resources/ec2.py` — EC2InstanceCleaner
2. Создать `resources/ebs.py` — EBSVolumeCleaner, EBSSnapshotCleaner
3. Создать `resources/lambda_.py` — LambdaFunctionCleaner
4. Создать `resources/vpc.py` — VPCCleaner (с зависимостями)
5. Создать `resources/elb.py` — LoadBalancerCleaner
6. Создать `resources/autoscaling.py` — ASGCleaner
7. Зарегистрировать все cleaners в registry

## Affected files/modules
- `awswipe/resources/ec2.py` (new)
- `awswipe/resources/ebs.py` (new)
- `awswipe/resources/lambda_.py` (new)
- `awswipe/resources/vpc.py` (new)
- `awswipe/resources/elb.py` (new)
- `awswipe/resources/autoscaling.py` (new)
- `awswipe/resources/__init__.py` (update registry)

## Tests
- Unit tests с moto для каждого типа ресурса
- `pytest tests/resources/test_ec2.py`

## Risks & Edge Cases
- VPC deletion order критичен (сначала instances, потом subnets, потом VPC)
- EC2 instances могут быть в termination-protected state
- EBS volumes могут быть attached

## Dependencies
- Upstream: 01-modular-architecture
- Downstream: 03-dependency-graph
