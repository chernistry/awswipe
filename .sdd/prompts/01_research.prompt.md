# Best Practices Research Template (Improved)

Instruction for AI: produce a practical, evidence‑backed best practices guide tailored to this project and stack.

---

## Project Context
- Project: awswipe
- Description: # Project Description

AWSwipe — автоматизированный инструмент для очистки AWS ресурсов. Удаляет orphaned ресурсы во всех регионах, помогает поддерживать гигиену AWS аккаунта и избегать лишних расходов.

## Core
- Primary goal: Безопасное и полное удаление неиспользуемых AWS ресурсов
- Users/personas: DevOps инженеры, разработчики с личными AWS аккаунтами, команды с dev/test окружениями
- Key constraints: Безопасность (не удалять production ресурсы), идемпотентность, поддержка всех регионов

## Definition of Done
- [ ] Удаляет все основные типы ресурсов (EC2, S3, RDS, Lambda, VPC, IAM и т.д.)
- [ ] Работает во всех AWS регионах
- [ ] Имеет dry-run режим для предварительного просмотра
- [ ] Генерирует детальный отчёт об удалённых/failed ресурсах
- [ ] Обрабатывает зависимости между ресурсами (порядок удаления)
- [ ] Retry механизм для throttling и временных ошибок
- [ ] Логирование всех операций
- [ ] Поддержка фильтрации по тегам/регионам

## Non-functional Requirements
- Performance: Параллельное удаление где возможно
- Reliability: Graceful handling rate limits и API errors
- Security: Использует стандартные AWS credentials, не хранит секреты
- Observability: Structured logging, итоговый отчёт
- Tech stack: Python/Boto3/AWS CLI
- Domain: cloud-infrastructure
- Year: 2025

## CRITICAL: Scope Analysis (DO THIS FIRST)

Before generating any content, analyze the goal/description for scope signals:

**Detect Appetite:**
- `Small` signals: "minor", "small", "tiny", "quick fix", "tweak", "мелкие", "небольшие", "слегка"
- `Batch` signals: "several", "few changes", "update", "improve" (without "completely")
- `Big` signals: "refactor", "redesign", "rewrite", "major", "complete overhaul"

**Detect Constraints:**
- Look for: "DO NOT", "don't", "NOT", "never", "without", "без", "не делай", "не меняй"
- Extract the full constraint phrase (e.g., "DO NOT REDESIGN COMPLETELY")

**Your output MUST respect these signals:**
- If goal says "minor improvements", do NOT suggest architectural overhauls.
- If goal says "DO NOT X", explicitly list X as an Anti-Pattern.

---

## Task
Create a comprehensive best‑practices guide for awswipe that is:
1) Current — relevant to 2025; mark deprecated/outdated items.
2) Specific — tailored to Python/Boto3/AWS CLI and cloud-infrastructure.
3) Practical — include concrete commands/config/code.
4) Complete — cover architecture, quality, ops, security, and technical debt.
5) Risk‑aware — define a simple metric profile (PerfGain, SecRisk, DevTime, Maintainability, Cost, DX) with indicative weights for this project, plus 3–5 key risks with High/Medium/Low labels.
6) Conflict‑aware — explicitly call out conflicting or mutually exclusive practices and alternative patterns.
7) Verification‑ready — for each major recommendation, note how to validate it (tests, metrics, experiments) so the architect/agent can reuse these checks.

## Output Structure (Markdown)

### 1. Scope Analysis Summary
- Appetite: [Small/Batch/Big]
- Key Constraints: [List]
- Reasoning: [Why]

### 2. TL;DR (≤10 bullets)
- Key decisions and patterns (why, trade‑offs, MVP vs later)
- Observability posture; Security posture; CI/CD; Performance & Cost guardrails
- What changed in 2025; SLOs summary

### 3. Landscape — What’s new in 2025
For Python/Boto3/AWS CLI:
- Standards/framework updates; deprecations/EOL; pricing changes
- Tooling maturity: testing, observability, security
- Cloud/vendor updates
- **Red flags & traps**: widespread but now-discouraged practices, legacy patterns to avoid

### 4. Architecture Patterns (2–4 for cloud-infrastructure with Python/Boto3/AWS CLI)
Pattern A — [NAME] (MVP)
- When to use; Steps; Pros/Cons; Optional later features

Pattern B — [NAME] (Scale‑up)
- When to use; Migration from A

### 5. Conflicting Practices & Alternatives
- List concrete areas where reputable sources disagree (e.g., sync vs async I/O, ORMs vs SQL, service boundaries, caching strategy).
- For each conflict, summarize:
  - Options (A/B/…)
  - When each is preferable (context/scale/risk profile)
  - Key trade‑offs and risks (PerfGain, SecRisk, DevTime, Maintainability, Cost, DX)
  - Any hard constraints from the project description (Definition of Done, compliance, budgets) that favor one option.

### 6. Priority 1 — [AREA]
Why → relation to goals and mitigated risks
Scope → In/Out
Decisions → with rationale and alternatives
Implementation outline → 3–6 concrete steps
Guardrails & SLOs → metrics and limits/quotas
Failure Modes & Recovery → detection→remediation→rollback

### 7–8. Priority 2/3 — [AREA]
Repeat the structure from 6.

### 9. Testing Strategy (for Python/Boto3/AWS CLI)
- Unit / Integration / E2E / Performance / Security
- Frameworks, patterns, coverage targets
- When to stub/mock vs use real dependencies

### 10. Observability & Operations
- Metrics, Logging, Tracing, Alerting, Dashboards
- Structured logging (JSON, no secrets) with correlation IDs
- Health endpoints, SLIs/SLOs

### 11. Security Best Practices
- AuthN/AuthZ, Data protection (PII, encryption), Secrets, Dependency security
- OWASP Top 10 (2025) coverage; Compliance (if any)
- SSRF/input validation; allowlists for external domains

### 12. Performance & Cost
- Budgets (concrete numbers), optimization techniques, cost monitoring, resource limits
- Profiling strategy and tools

### 13. CI/CD Pipeline
- Build/Test/Deploy; quality gates; environments
- Rollback strategy

### 14. Code Quality Standards
- Style, linters/formatters, typing, docs, review, refactoring

### 15. Anti‑Patterns to Avoid
For Python/Boto3/AWS CLI/cloud-infrastructure:
- **What**: concrete code/config/systems examples
- **Why bad now**: broken assumptions, perf/regulatory/security risks
- **What instead**: actionable alternatives or migration paths

### 16. Red Flags & Smells
How to recognize a project in trouble:
- Architectural smells (god files, tight coupling)
- Operational smells (no timeouts, no retries, no metrics)
- Process smells (no tests, no CI, dangerous deploys)
- For each: how to detect, minimal remediation, when to create janitor ticket

### 17. Evidence & Citations
- List sources inline near claims; add links; include “Last updated” dates when possible.

### 18. Verification
- Self‑check: how to validate key recommendations (scripts, smoke tests, benchmarks)
- Confidence: [High/Medium/Low] per section

### 19. Technical Debt & Migration Guidance
- Typical sources of technical debt for Python/Boto3/AWS CLI/cloud-infrastructure.
- Recommended strategies to keep debt under control over time (continuous refactoring, migration paths, feature flags).
- When to introduce dedicated “janitor” tasks and what they should look like.

## Requirements
1) No chain‑of‑thought. Provide final answers with short, verifiable reasoning.
2) If browsing is needed, state what to check and why; produce a provisional answer with TODOs.
3) Keep it implementable today; prefer defaults that reduce complexity.
4) Do not fabricate libraries, APIs, or data; if unsure or the evidence is weak, mark the item as TODO/Low confidence and suggest concrete sources to verify.