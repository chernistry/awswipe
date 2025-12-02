### 1. Scope Analysis Summary

* **Appetite:** Batch
* **Key Constraints (implicit):**

  * Must be safe-by-default for production AWS accounts.
  * Must avoid accidental data loss; deletions should be reversible where possible.
  * Must keep complexity reasonable for a Python/Boto3/CLI tool (no hard requirement to become a full SaaS platform).

**Reasoning:**
The goal is to create a *best-practices guide* for an existing/planned tool (awswipe), not to redesign AWS itself. The scope spans multiple concerns (architecture, safety, cost, DX, ops), so this is more than a tiny tweak, but there is no signal for “full rewrite”. Hence “Batch”.

---

### 2. TL;DR (≤10 bullets)

1. **Primary objective:** awswipe should be a *safe, scriptable, tag-aware janitor* for orphaned/idle AWS resources across regions/accounts, focused on cost savings and hygiene, not complex orchestration.
2. **Architecture MVP:** local/CI Python CLI using Boto3 + AWS CLI profiles, with strong dry-run, tag/age filters, and idempotent deletion flows.
3. **Scale-up pattern:** optional “central janitor” mode (Lambda + EventBridge + DynamoDB/S3 state) that runs in-account/organization with quarantine → delete workflows, configured via tags and policies.([AWS Documentation][1])
4. **Safety posture:** deletion is always preceded by discovery + classification + “quarantine” state (tagging/marking), with backups for stateful resources (EBS snapshots, RDS snapshots, S3 lifecycle) and strict allowlists.([AWS Documentation][1])
5. **Cost posture:** prioritize high-impact idle resources (EBS, EIP, snapshots, load balancers, idle EC2/RDS, Route53) and integrate with Trusted Advisor/Cost Optimization Hub/Cost Explorer to cross-validate candidates.([AWS Documentation][1])
6. **Reliability posture:** use proper Boto3 paginators, retry modes, exponential backoff, concurrency limits, and per-service rate caps to avoid throttling and partial failures.([Boto3][2])
7. **Security posture:** no long-lived keys; prefer AWS SSO / IAM Identity Center with short-lived credentials, least-privilege IAM roles for awswipe, MFA, and strict secrets handling.([AWS Documentation][3])
8. **Observability:** structured JSON logs + metrics on “discovered vs quarantined vs deleted”, error counts, per-service API calls, and per-run cost-saving estimates; alerts on error spikes or unusually high deletion counts.([CloudOptimo][4])
9. **2025-specific:** rely on AWS Config, Resource Explorer, Trusted Advisor Cost Optimization checks, and newer AWS CLI v2 features (SSO, improved paginators) instead of ad-hoc scraping or old v1 patterns.([CloudOptimo][4])
10. **SLOs:** e.g., “<0.1% false-positive deletions, 99% of candidates visible in dry-run, 95% of runs complete without throttling, and 10–20% monthly cost savings on target resource classes within 3 months.”([AWS Documentation][5])

---

### 3. Landscape — What’s New in 2025 (Python/Boto3/AWS CLI + Cloud-Infra)

**Python & Boto3**

* Boto3 remains the standard AWS SDK for Python.
* Recent guidance emphasizes:

  * Proper **retry modes** (`standard`, `adaptive`) via botocore config, to handle aggressive throttling.([Boto3][2])
  * Use of **paginators** for list operations; many APIs now *require* pagination to avoid missing resources.([Boto3][6])
  * Clear separation of **clients vs resources** (clients favored for infra tools to keep full API control).([Medium][7])

**AWS CLI v2**

* AWS CLI v2 is the default; v1 is legacy. Newer guidance highlights:

  * Built-in **SSO/Identity Center** support and improved credential caching.([AWS Documentation][3])
  * Improved **pagination and output** modes (e.g., `--query`, `--output json`, `--cli-pagination-config`).([AWS Documentation][8])
* CLI is still the standard way to bootstrap credentials/profiles for SDK tools.

**Cloud cost & orphaned resources**

* AWS and the FinOps ecosystem now heavily emphasize **idle/orphaned resource cleanup** (EBS volumes, snapshots, EIPs, idle EC2/RDS, unused load balancers, Route53, etc.) as an easy ~10–15% cost saving lever.([AWS Documentation][1])
* Tools/guides recommend:

  * Using **AWS Config rules**, **Resource Explorer**, **Trusted Advisor**, and **Compute Optimizer** to identify unused resources.([CloudOptimo][4])
  * Automating cleanup via **Lambda + EventBridge + Systems Manager** where possible.([AWS Documentation][1])

**Red flags & traps (2025)**

* Hand-rolled credential management (storing access keys in code/env without SSO, MFA, or rotation) is now strongly discouraged.([The Cloudericks Blog][9])
* “One-shot” cleanup scripts without dry-run, tagging, backups, or audit logs are considered risky, especially under OWASP 2025 RC (Broken Access Control, Security Misconfiguration).([OWASP][10])
* Ignoring API rate limits and pagination is a common failure mode for Boto3 scripts in production.([Boto3][2])

---

### 4. Architecture Patterns (Python/Boto3/AWS CLI)

#### Pattern A — “Safe Local/CI Janitor” (MVP)

**When to use**

* Single or few AWS accounts.
* Primary use by DevOps/FinOps engineers via CLI or CI.
* Initial rollout where you want maximum human oversight.

**Core ideas**

* `awswipe` is a Python CLI that:

  * Uses **AWS profiles/SSO** configured by AWS CLI v2.
  * Enumerates resources across regions via Boto3 clients + paginators.
  * Resolves candidates using *rules*: tag filters, age thresholds, orphan heuristics (e.g., unattached volumes/snapshots, unused security groups).([AWS Documentation][1])
  * Implements **three phases**: `discover` → `quarantine` (tag/mark) → `delete`.

**Implementation outline (high-level)**

1. **CLI layer:** `awswipe discover`, `awswipe quarantine`, `awswipe delete`.
2. **Config:** YAML/JSON for:

   * target profiles/accounts;
   * resource types;
   * allowlist/denylist tags;
   * age thresholds;
   * dry-run level.
3. **Infra layer:** Boto3 clients per service + concurrency manager (e.g., `concurrent.futures.ThreadPoolExecutor`) with per-service rate caps.
4. **State:** local JSON/SQLite reports or S3 file storing candidate lists and actions taken.
5. **Safety:** backup hooks for stateful resources (EBS/RDS snapshots) prior to deletion; optional “confirm via prompt/flag”.

**Pros**

* Low operational overhead; easy to ship as `pipx`/container.
* Strong operator control; good for first roll-out.
* Works well in CI (e.g., nightly cleanup jobs in GitHub Actions/GitLab).

**Cons**

* Limited scheduling/observability without extra work.
* Harder to run continuously across dozens of accounts.

**Optional later features**

* “Pluggable” resource type modules.
* Export of metrics to Prometheus/CloudWatch via push gateway.

---

#### Pattern B — “Central Janitor Service” (Scale-Up)

**When to use**

* Many accounts (AWS Organizations), regulated environments, or continuous cleanup.
* Need for auditable, policy-driven, tag-driven cleanup with approvals.

**Core ideas**

* awswipe is deployed as:

  * **EventBridge-scheduled Lambdas** (per account/region) or Step Functions flows.
  * Shared **config state** (S3/YAML or DynamoDB) defining policies and tags.
  * **DynamoDB or S3** storing discovered candidates and their state (discovered/quarantined/deleted).([AWS Documentation][1])

**Migration from A**

* Reuse discovery/quarantine/delete logic from Pattern A.
* Replace local CLI “main” with Lambda handlers; state backend from local files → DynamoDB/S3.
* Add:

  * SNS/Slack notifications for approvals;
  * “quarantine for N days, then delete” flows;
  * per-account IAM roles (assume-role from central management account).

**Pros**

* Continuous, organization-wide hygiene and cost control.
* Better auditability and blast-radius control.
* Can be integrated with Trusted Advisor/Config/Compute Optimizer outputs.([CloudOptimo][4])

**Cons**

* Requires infra as code (CloudFormation/Terraform/CDK) and governance.
* More complex IAM; needs platform owner.

---

### 5. Conflicting Practices & Alternatives

Below are typical decision points where credible sources and teams differ.

#### A. Discovery strategy: Direct Boto3 enum vs AWS Config / Resource Explorer

* **Option A: Direct enumeration via Boto3 (sdk-driven)**

  * Pros: full control, minimal prerequisites, no extra AWS services.
  * Cons: more API calls, must implement relationships/orphan logic yourself, higher throttling risk.

* **Option B: Use AWS Config, Resource Explorer, Trusted Advisor feeds**([CloudOptimo][4])

  * Pros: built-in relationships/history, fewer API calls, native “unused resource” signals.
  * Cons: requires Config enabled (cost), may have lag, not all services covered.

* **When to choose which**

  * MVP (Pattern A): start with Boto3 direct enumeration; add Config/Explorer integration where available (EBS, snapshots, security groups, etc.).
  * Scale-up: prefer AWS-native signals as primary, with Boto3 enumeration as a fallback.

* **Trade-offs (relative):**

  | Metric          | A: Direct Boto3 | B: Config/Explorer                |
  | --------------- | --------------- | --------------------------------- |
  | PerfGain        | Medium          | High                              |
  | SecRisk         | Medium          | Low–Medium                        |
  | DevTime         | Low             | Medium                            |
  | Maintainability | Medium          | High (if org already uses Config) |
  | Cost            | Low             | Medium (Config charges)           |
  | DX              | High (simple)   | Medium                            |

#### B. Deletion policy: Tag-allowlist vs “catch-all with denylist”

* **Option A: Tag-based allowlist (“opt-in to deletion”)**([Cloud Solutions][11])

  * Only delete resources with specific tags (`cleanup=true`, `owner`, `env`) and matching age/type rules.
  * Safer, but might miss “truly forgotten” resources.

* **Option B: Catch-all with denylist (“delete unless protected”)**

  * Everything without certain tags is eligible; some tags mark exceptions (`keep`, `compliance`).
  * More aggressive savings, higher risk of deleting untagged but important infra.

* **Recommendation for awswipe:**

  * Use **allowlist** as default; provide **denylist mode** but force explicit `--dangerous-mode`/config flag and stronger approvals.

#### C. Execution model: Single-threaded vs highly concurrent

* **Low concurrency:** fewer throttling issues, simpler debugging, slower on large accounts.
* **Higher concurrency:** faster scans but needs per-service caps + retries/backoff.([Boto3][2])

For awswipe, default to moderate concurrency with adaptive retries; configuration of per-service limits should be exposed but bounded.

---

### 6. Priority 1 — Safety & Idempotent Deletion

**Why**

* Primary risks: accidental deletion and data loss.
* OWASP 2025 RC and API Security Top 10 2023 emphasize broken access control, misconfiguration, and unsafe resource operations as top risks.([OWASP][10])

**Scope**

* In: policies and flows around discovery/quarantine/delete, backups, tags, approvals.
* Out: organization-wide governance processes (these can be influenced but not owned by awswipe).

**Decisions**

* **D1:** Three-phase lifecycle per resource:

  * `DISCOVERED` → `QUARANTINED` (marked/tagged, maybe stopped) → `DELETED`.
* **D2:** **Dry-run** is default; destructive actions require explicit `--execute` flag.
* **D3:** For stateful resources (EBS, RDS, S3), create **backups (snapshots)** or verify existing policies before deletion.([AWS Documentation][1])
* **D4:** Implement **idempotency**:

  * Use idempotent delete operations and record actions in state (DynamoDB/S3/SQLite) to avoid repeated deletes.
* **D5:** Deletion requires passing *all* rules: tag policy, age, orphan status, allowlists, and optional manual approval.

**Implementation outline (3–6 steps)**

1. **Model resource state** in a small schema (e.g., `ResourceCandidate` with `id`, `type`, `region`, `account`, `tags`, `age_days`, `phase`, `reason`).
2. **Discovery:**

   * Enumerate via Boto3 paginators per resource type.([Boto3][6])
   * Apply built-in heuristics: unattached EBS, unattached ENIs, unused security groups, idle snapshots, etc.([AWS Documentation][1])
   * Store results in state backend.
3. **Quarantine:**

   * Tag resources (`awswipe:quarantine=true`, `awswipe:reason=unattached_ebs`, `awswipe:timestamp=...`).
   * Optionally stop instances, but do not delete.
   * Emit reports and notifications.
4. **Delete:**

   * After configurable TTL (e.g., 7–30 days), check: still orphaned, no “keep” tag added, no recent metric activity (if integrated).
   * Acquire final approval (flag/interactive/Slack) and call delete APIs with backoff/retries.
5. **Audit & rollback:**

   * Log each action with correlation ID; maintain per-run audit log.
   * For EBS and RDS, allow rollback from snapshots for a limited retention period.([AWS Documentation][1])

**Guardrails & SLOs**

* Max allowed **“false-positive delete” rate:** < 0.1% of deleted resources, measured by post-incident review.
* **Quarantine TTL:** ≥ 7 days by default.
* **Backups:** 100% of stateful resources have backups before delete; backup retention at least 30 days (configurable).
* **Security guardrail:** awswipe IAM role cannot delete certain protected resources (e.g. tagged `critical`, `compliance`).

**Failure Modes & Recovery**

* **Mode:** Deleting needed resource.

  * Detection: alert from monitoring; service outage.
  * Recovery: restore from snapshot/backup; review logs to identify policy gap; update allowlists/tags; add regression test.
* **Mode:** Partial execution (half of resources deleted, half not).

  * Detection: mismatch between state and AWS; high error rates in logs.
  * Recovery: repeat run; idempotent logic prevents double deletes; investigate throttling/permissions.

---

### 7. Priority 2 — Multi-Region/Account Scanning & Throttling

**Why**

* Orphaned resources accumulate across **all regions** and **all accounts**; ignoring some regions/accounts undermines cost savings. AWS throttles aggressively when you scan broadly.([Boto3][2])

**Scope**

* In: region discovery, profile/role management, concurrency/throughput caps, retry strategies.
* Out: high-level Org governance and account creation lifecycle.

**Decisions**

* **D6:** awswipe must support:

  * `--regions all|<list>` (discover via `ec2.describe_regions`).
  * `--accounts` from AWS profiles or assume-role ARNs.
* **D7:** Use **Boto3 config** for `retries = {"mode": "standard" or "adaptive", "max_attempts": N}`.([Boto3][2])
* **D8:** Central concurrency control with per-service rate caps (e.g., max N concurrent calls to `DescribeVolumes`).

**Implementation outline**

1. Build **region/account iterator**:

   * For each profile or assume-role, list enabled regions.
2. For each `(account, region)` pair:

   * Initialize Boto3 clients with shared `botocore.config.Config` (retry mode, timeouts).
3. Run resource-type scanners with:

   * `ThreadPoolExecutor` or `asyncio` with semaphores to cap concurrency per service.
4. Collect metrics:

   * API call counts, throttling errors, average call latency.
5. Make concurrency configurable with sane defaults and “safe mode” caps.

**Guardrails & SLOs**

* **Throttle error rate** (e.g. `ThrottlingException`, `SlowDown`) stays below 1% of AWS calls in normal runs.([DrDroid][12])
* **Scan coverage:** ≥ 95% of regions/accounts configured are scanned once per run.

**Failure Modes & Recovery**

* **Mode:** Global throttling.

  * Detection: spike in throttling errors.
  * Reaction: automatically reduce concurrency (`backoff on concurrency`) and requeue pages.

---

### 8. Priority 3 — Tagging & Governance Integration

**Why**

* Tagging underpins safe cleanup, ownership, and approvals. Tag-based programs in 2025 are considered best practice for AWS cleanup.([Cloud Solutions][11])

**Scope**

* In: tag schemas, awswipe tag usage, minimal tag governance alignment.
* Out: org-wide tag policy rollout.

**Decisions**

* **D9:** Define a minimal **required tag schema** for awswipe:

  * `Owner`, `Environment`, `CostCenter`, `awswipe:cleanup` (enum: `allow`, `deny`, `quarantine-only`).
* **D10:** awswipe writes only under its own namespace: `awswipe:*`.
* **D11:** For resources lacking required tags, default action is **discover + report**, not delete.

**Implementation outline**

1. Implement a **tag policy module** that:

   * Validates tags against allowed values.
   * Classifies resources into: `eligible`, `needs-tagging`, `protected`.
2. Provide **tag-fix mode**:

   * Optionally add owner/env tags based on heuristics (CloudTrail, CloudFormation stack, etc.) — keep this opt-in and conservative.
3. Generate periodic **tag coverage reports** for FinOps/Platform teams.

**Guardrails & SLOs**

* **Tag coverage** for *eligible* resources > 85% within 3 months of rollout.
* **Zero deletes** of untagged resources unless user explicitly enables aggressive mode.

---

### 9. Testing Strategy (Python/Boto3/AWS CLI)

**Types**

* **Unit tests:**

  * Pure logic (filters, heuristics, config parsing, tag policies).
* **Integration tests:**

  * Boto3 interactions using **botocore Stubber** or **moto**; verify that correct AWS calls are made.
* **E2E tests:**

  * Against a sandbox AWS account with test resources (e.g., create unattached EBS, snapshots, security groups, then run awswipe).
* **Performance tests:**

  * Simulate large inventories (via mocks) to test throughput and concurrency.
* **Security tests:**

  * Verify no logs contain secrets; IAM policies are least-privilege.

**Frameworks & patterns**

* `pytest` + `pytest-cov`, `moto` for AWS mocking, `botocore.stub.Stubber` where fine-grained.
* Use factories for `ResourceCandidate` to keep tests readable.
* Coverage targets:

  * Core logic > 80% line coverage.
  * AWS interactions: all delete flows and error-handling paths.

**Stubbing vs real AWS**

* Use **mocks/stubs** for:

  * Unit and most integration tests.
  * Error handling, throttling, pagination behavior.
* Use **real AWS** (sandbox) for:

  * E2E flows (discovery → quarantine → delete).
  * Regression tests on new AWS API versions or when reworking heuristics.

---

### 10. Observability & Operations

**Metrics**

* Per run:

  * `awswipe.discovered_resources{type, account, region}`
  * `awswipe.quarantined_resources{...}`
  * `awswipe.deleted_resources{...}`
  * `awswipe.api_calls{service, operation}` and `awswipe.api_errors{code}`
  * Estimated monthly savings for deleted idle resources (rough formulas from AWS pricing or Cost Explorer).([AWS Documentation][1])

**Logging**

* Structured JSON logs:

  * `run_id`, `resource_id`, `action`, `reason`, `actor`, `timestamp`.
* No secrets or credentials in logs (ever).
* Include AWS request IDs when possible.

**Tracing**

* For Lambda/Step Functions deployments, rely on **X-Ray** or similar.
* For CLI/CI, correlation IDs in logs are sufficient.

**Alerting**

* Alerts (CloudWatch, Prometheus, or external) on:

  * High error or throttling rates.
  * Unusually high number of deletions in a single run.
  * Failed backup or snapshot operations.

**Health**

* For service deployment: simple `/health` and `/ready` endpoints or lightweight health command (`awswipe health`) that checks credentials, IAM permissions, and AWS API connectivity.

---

### 11. Security Best Practices

**AuthN/AuthZ**

* Prefer **IAM Identity Center / AWS SSO** + short-lived session tokens over long-lived access keys.([AWS Documentation][3])
* Use **least-privilege IAM roles** for awswipe:

  * Scoped to specific services/actions and condition keys (e.g., tags).
* For central deployments, use **assume-role** from a secure management account.

**Data protection**

* Encrypt all state (DynamoDB, S3) with KMS.
* Ensure backups/snapshots are encrypted as per org standard.

**Secrets**

* No credentials in code or repo.
* Use AWS CLI v2 config + SSO or AWS Secrets Manager/SSM Parameter Store where needed.

**OWASP coverage**

* Align with OWASP Top 10 2025 RC and API Security Top 10 2023 where relevant (e.g., Security Misconfiguration, Broken Access Control, Unrestricted Resource Consumption, SSRF).([OWASP][10])
* Hardening steps:

  * Validate all input configs; no dynamic code execution.
  * Restrict any HTTP calls (if awswipe ever talks to external APIs) with allowlists.

**SSRF / input validation**

* If awswipe ever retrieves metadata or external URLs, restrict:

  * No metadata IP ranges (`169.254.169.254`).
  * Explicit domain/IP allowlists.

---

### 12. Performance & Cost

**Budgets (example starting point, tune per org)**

* **Tool runtime:** normal run finishes within 30–60 minutes across all regions/accounts.
* **API cost:** additional AWS API costs (Config/Trusted Advisor, etc.) remain below 1–2% of expected savings.([AWS Documentation][5])

**Optimization techniques**

* Use **paginators** and filter parameters (`MaxResults`, `Filters`) to avoid fetching useless data.([Boto3][6])
* Query AWS Config/Resource Explorer for pre-filtered candidates when available.([CloudOptimo][4])
* Cache common lookups (e.g. region lists, account aliases).
* Run heavier scans in off-peak hours.

**Cost monitoring**

* Integrate with **Cost Explorer** / **Budgets** and **Trusted Advisor Cost Optimization** to compare awswipe-detected candidates vs AWS recommendations.([AWS Documentation][5])

**Profiling tools**

* Python: `cProfile`, `py-spy`, or sampling profilers in dev to identify hotspots.
* Track per-service API call counts and time.

---

### 13. CI/CD Pipeline

**Build/Test**

* Lint + format: `black`, `isort`, `flake8`/`ruff`, `mypy`.
* Unit + integration tests via `pytest` on each push.
* Security scanning: `pip-audit` or similar for Python dependencies.

**Deploy**

* For CLI tool:

  * Build/publish wheel to internal index; optionally provide Docker image.
* For Lambda/Step Functions:

  * Use IaC (CDK/Terraform/CloudFormation) + pipeline (GitHub Actions, GitLab CI, CodePipeline).

**Quality gates**

* All tests green; coverage threshold met.
* Security scan must pass (no critical vulnerabilities).
* Optional: approval step for changes to deletion policies.

**Rollback**

* Version releases with semantic versioning.
* Ability to roll back to previous pipeline artifact or Lambda alias; ensure state migrations are backwards-compatible.

---

### 14. Code Quality Standards

* **Style:** PEP8; formatter enforced (black).
* **Typing:**

  * Type hints for all public functions.
  * mypy in strict(er) mode for core logic modules.
* **Docs:**

  * Clear README explaining safety model, dry-run, and config.
  * `doc/` including examples and runbooks.
* **Reviews:**

  * At least one reviewer for changes affecting deletion logic or IAM policies.
* **Refactoring policy:**

  * Small functions with single responsibility; no “god modules” for all resources.
  * Resource-specific modules (e.g. `resources.ebs`, `resources.snapshots`).

---

### 15. Anti-Patterns to Avoid

For Python/Boto3/AWS CLI/cloud-infra tools like awswipe.

1. **Mass delete without dry-run or backups**

   * Why bad: high data-loss risk; conflicts with AWS guidance on EBS and snapshot cleanup.([AWS Documentation][1])
   * Instead: three-phase lifecycle with quarantines and snapshots.

2. **Ignoring pagination and retries**

   * Why bad: missing resources, unpredictable failures, throttling.([Boto3][2])
   * Instead: always use paginators and configured retry modes.

3. **Using root or overly broad IAM roles**

   * Why bad: broken access control, compliance issues; raised by OWASP and AWS security best practices.([The Cloudericks Blog][9])
   * Instead: least-privilege roles scoped to awswipe operations.

4. **Hard-coding access keys in code or CI variables**

   * Why bad: credential leaks in repos/logs; rotation hard.([The Cloudericks Blog][9])
   * Instead: SSO, IAM roles, secure secrets management.

5. **No tagging / ad-hoc rules**

   * Why bad: impossible to align with owners and cost-centers; high false-positive risk.([Cloud Solutions][11])
   * Instead: enforce tag schemas and tag-driven deletion rules.

---

### 16. Red Flags & Smells

**Architectural**

* Single 2k+ line script doing everything — discovery, filtering, deletion, reporting.

  * Minimal remediation: split into modules; add clear data model.

**Operational**

* No **timeouts or retries** set on Boto3 clients; everything relies on defaults.([Boto3][2])
* No metrics/traces; only ad-hoc `print` logging.

**Process**

* No tests; changes to deletion logic go straight to production runs.
* No documented runbooks for rollback or incident handling.

For each smell, awswipe should at least:

1. Emit a **self-diagnostic** (`awswipe doctor`) highlighting missing safeguards.
2. Create a **janitor ticket** template (e.g., “Add retries and paginators to EBS scanner”).

---

### 17. Evidence & Citations (selected)

Some key references behind the recommendations:

* AWS guidance on detecting orphaned resources with **AWS Config** and automating EBS cleanup via Lambda/EventBridge.([CloudOptimo][4])
* Analysis of cost impact of **orphaned snapshots** and idle resources.([Zesty][13])
* AWS **Trusted Advisor** cost optimization checks and cost-savings ranges.([AWS Documentation][5])
* Boto3 official docs and modern blog posts on **retries, throttling, and pagination**.([Boto3][2])
* AWS CLI v2 docs and security best practices (SSO, least privilege).([AWS Documentation][3])
* OWASP Top 10 2025 RC / 2021 and OWASP API Security Top 10 2023 for security framing.([OWASP][10])
* Tag-based cleanup programs as a recommended structured approach.([Cloud Solutions][11])

For any organization adopting awswipe, periodically re-check these sources (and AWS release notes) for changes in APIs, pricing, and security guidance.

---

### 18. Verification

**Self-check checklist**

* Can awswipe run in **full dry-run** mode against a sandbox account and produce:

  * A list of candidates, all with reasons and tags?
* When enabling **quarantine**:

  * Are tags correctly applied and visible in the console?
* When enabling **delete** in sandbox:

  * Are backups created for stateful resources?
  * Are deletions logged with correlation IDs?

**Suggested verification scripts**

* `awswipe verify-safety`:

  * Creates temporary resources in a sandbox; runs full discover→quarantine→delete; ensures expected resources are deleted and protected resources remain.
* `awswipe benchmark`:

  * Simulates large inventories (mock) and asserts that API throttling stays below target.

**Confidence (subjective, based on current public info)**

* Architecture & safety model: **High**.
* Precise IAM policies and tag schemas: **Medium** (should be tailored per org; verify via internal security review).
* Long-term AWS pricing and new services: **Low–Medium** (must be revisited at least annually; TODO: check AWS cost optimization and Config/Explorer updates each 6–12 months).

---

### 19. Technical Debt & Migration Guidance

**Typical debt sources in awswipe-like tools**

* Accumulated inline heuristics for each service without central policy model.
* No separation between discovery and action logic.
* Old support for AWS CLI v1 or obsolete APIs.
* Hard-coded lists of regions/resource types.

**Strategies to control debt**

* **Continuous refactoring:**

  * Keep resource scanners modular; add new services via well-defined plugin interface.
* **Feature flags:**

  * Roll out new deletion heuristics or more aggressive policies guarded by feature toggles.
* **Janitor tickets:**

  * For each “TODO” (e.g. integrating AWS Config, Trusted Advisor), create explicit work items with rough impact estimates.

**Migration paths**

* From “single script” to **Pattern A**:

  * Extract config and state models; introduce CLI subcommands.
* From Pattern A to **Pattern B** (central service):

  * Introduce state backend (DynamoDB/S3) and EventBridge, then migrate flows to Lambda/Step Functions incrementally.([AWS Documentation][1])

A simple metric profile suitable for awswipe (relative weights; tune per org):

* **PerfGain:** 0.15
* **SecRisk:** 0.25
* **DevTime:** 0.10
* **Maintainability:** 0.20
* **Cost (savings vs tool cost):** 0.20
* **DX (usability for operators):** 0.10

This profile prioritizes security, maintainability, and cost savings — matching awswipe’s role as a safe, long-lived AWS janitor rather than a one-off script.

[1]: https://docs.aws.amazon.com/prescriptive-guidance/latest/optimize-costs-microsoft-workloads/ebs-delete-ebs-volumes.html?utm_source=chatgpt.com "Delete unattached Amazon EBS volumes"
[2]: https://boto3.amazonaws.com/v1/documentation/api/1.24.23/guide/retries.html?utm_source=chatgpt.com "Retries — Boto3 Docs 1.24.23 documentation - AWS"
[3]: https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html?utm_source=chatgpt.com "Getting started with the AWS CLI"
[4]: https://www.cloudoptimo.com/blog/detecting-orphaned-resources-using-aws-config-rules/?utm_source=chatgpt.com "Detecting Orphaned Resources Using AWS Config Rules"
[5]: https://docs.aws.amazon.com/awssupport/latest/user/cost-optimization-checks.html?utm_source=chatgpt.com "Cost optimization - AWS Support"
[6]: https://boto3.amazonaws.com/v1/documentation/api/1.12.24/guide/paginators.html?utm_source=chatgpt.com "Paginators — Boto 3 Docs 1.12.24 documentation - AWS"
[7]: https://medium.com/%40u.mair/12-best-practices-to-keep-your-boto3-scripts-from-breaking-in-production-f0f726bdfba0?utm_source=chatgpt.com "12 Best Practices to Keep Your Boto3 Scripts from ..."
[8]: https://docs.aws.amazon.com/cli/latest/userguide/cliv2-migration-changes.html?utm_source=chatgpt.com "New features and changes in the AWS CLI version 2"
[9]: https://cloudericks.com/blog/getting-started-with-aws-cli/?utm_source=chatgpt.com "Getting Started with AWS CLI - The Cloudericks Blog"
[10]: https://owasp.org/Top10/?utm_source=chatgpt.com "OWASP Top 10:2025 RC1"
[11]: https://thecloudsolutions.com/blog/aws-tag-based-resource-cleanup/?utm_source=chatgpt.com "AWS Tag Based Resource Cleanup: Unused Or Underutilized"
[12]: https://drdroid.io/stack-diagnosis/boto3-aws-sdk-slowdown-error-encountered-when-making-requests-to-aws-services-using-boto3?utm_source=chatgpt.com "boto3 aws sdk SlowDown error encountered when making ..."
[13]: https://zesty.co/finops-glossary/orphaned-snapshots-aws/?utm_source=chatgpt.com "Orphaned Snapshots in AWS: Costs, Causes, and ... - Zesty.co"
