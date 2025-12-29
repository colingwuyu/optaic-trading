---
trigger: model_decision
description: Agent trigger: Load this file for any task adding specs/contracts/validators/invariants or wiring validation to resource create/update/promote/merge/run & audit events. Use bundles+reports; staging=warn, official=block; keep deps optional/lazy.
---

# Guardrails Framework v0 (Domain-Agnostic) — Developer & Agent Guide

This document defines **how to build business logic on OptAIC** while keeping the platform **robust, auto-governed, and auditable**.

**Important:** Guardrails v0 is intentionally **domain-agnostic**.  
Do **not** introduce concrete business contracts (e.g., dataset/signal/portfolio schemas) until the infra/framework is stable.  
Instead, implement new contracts incrementally using the extension points described here.

---

## 1) Purpose

OptAIC is a governed platform where all actions are auditable and controlled by strict segregation:

- **Spaces:** personal / team / system  
- **Subspaces:** staging / official  
- **Promotion lanes:** personal → team → system, always landing in **staging** before merge to **official**  
- **RBAC:** applies to all resources (including channels)

Guardrails provide a **contract-driven framework** that:

1) attaches **contracts** to any resource  
2) validates those contracts at lifecycle gates (create/update/promote/merge/run)  
3) enforces policy based on staging vs official  
4) stores **ValidationReports**  
5) emits **ActivityEvents** for audit, notifications, and compliance review

Guardrails are not “business logic.” They are a **framework** that business logic must use.

---

## 2) Key concepts

### 2.1 ContractRef, ContractInstance, ContractBundle

- **ContractRef**: identifies a contract kind and carries its JSON Schema
- **ContractInstance**: a concrete configuration for that schema + a deterministic `contract_hash`
- **ContractBundle**: a set of ContractInstances attached to a resource (active bundle)

Bundles are persisted and are auditable artifacts.

### 2.2 ValidationReport

Every guardrail evaluation produces a **ValidationReport**:
- scope: `resource | run | promotion | merge`
- target_id: resource_id / run_id / promotion_id / merge_id
- `ok`: whether the operation is allowed to proceed
- `enforced_as`: `warn|block` (effective enforcement derived from policy)
- issues: warnings/errors
- contract_hashes: list of contract hashes evaluated
- correlation_id: links to broader workflows (promotion, approval, run pipeline)

Reports are persisted and must be emitted as activity events.

### 2.3 Validators

A **ContractValidator** checks a contract instance against a target snapshot.

Guardrails v0 includes only:
- JSON Schema validation (config conforms to schema)
- No domain-specific checks yet

Domain-specific validation comes later via new validators.

---

## 3) Guardrails lifecycle gates

Guardrails must be evaluated at these platform gates:

### 3.1 Resource lifecycle
- resource create
- resource update
- definition submission (if you model it as a resource action)
- RBAC edits (optional gate if you later add RBAC policy contracts)

### 3.2 Governance lifecycle
- promotion request creation (including dependency-closure checks later)
- merge staging → official (approval/merge gate)

### 3.3 Execution lifecycle
- run submission (before starting execution)
- run start (optional; for additional runtime checks)
- run completion (optional; for output validation later)

**Rule:** guardrails are called from the service layer (not directly from plugins), so that every evaluation is logged and governed.

---

## 4) Enforcement policy (staging vs official)

Guardrails enforcement must be derived from **location + action**:

Baseline v0 policy:
- `official` subspace ⇒ **BLOCK** on errors
- `staging` subspace ⇒ **WARN** on errors (unless policy/config elevates to block)

This keeps iteration fast in staging while ensuring official is safe and compliant.

Later, you may refine policy:
- team staging stricter than personal staging
- certain actions always block (e.g., merge-to-official)
- allow admin-configured enforcement by contract kind

---

## 5) Activity events and audit requirements

Every guardrails evaluation must emit an ActivityEvent (outbox pattern):

- `guardrails.validated` (always)
- `guardrails.blocked` (when blocked by policy)

Activity payload should include:
- report_id
- target_id + scope
- ok
- enforced_as
- issue counts (errors/warnings)
- correlation_id (if any)

**Auditor subscriptions** must be RBAC-driven; do not hardcode special access.

---

## 6) How to add business contracts later (the approved pattern)

When the platform is ready to add a domain contract (e.g., dataset schema, signal bounds, PIT policy), follow this pattern:

### Step 1 — Define contract kind + JSON schema
Create a new contract kind name, for example:
- `"dataset.schema"`
- `"signal.bounds"`
- `"pit.policy"`
- `"portfolio.constraints"`

Add the JSON Schema for contract configuration.

### Step 2 — Register it in ContractRegistry
Register:
- kind + version
- schema_json
- default validator name

### Step 3 — Implement a ContractValidator (if needed)
If JSON Schema is not enough, add a validator:
- deterministic, side-effect free
- uses only `target_snapshot` and contract config
- returns structured ValidationIssues with codes

### Step 4 — Attach bundles during resource lifecycle
Business logic should attach/update contract bundles when:
- a resource is created
- a resource config changes
- a resource is promoted or merged (bundle can be copied or updated)

### Step 5 — Add tests
Required tests:
- schema validation passes for valid configs
- validator returns correct issues for invalid cases
- enforcement behaves correctly in staging vs official

---

## 7) Target snapshots (what validators receive)

Guardrails validators must not depend on internal DB session access.

Instead, validators receive a **target snapshot**:
- a dict of relevant fields the service layer provides
- minimal and explicit (so validation is reproducible)

Examples of snapshot contents (future):
- resource metadata, type, location (space/subspace/project)
- proposed config JSON
- declared I/O schema references
- promotion closure summary

Do not stuff huge objects into snapshots; keep them auditable and stable.

---

## 8) Optional dependencies and import rules (critical)

OptAIC supports selective installs (`optaic[sdk]`, `optaic[server]`, `optaic[all]`).

Guardrails must respect this:

- **No heavy imports at module import time**
- Domain-specific validators that require extra packages must:
  - live behind optional extras (e.g., `optaic[guardrails-data]`)
  - import those packages lazily inside validators
  - raise actionable errors: `pip install "optaic[guardrails-data]"`

This prevents deployment breakage for clients who only use SDK or remote engines.

---

## 9) Interaction with promotion dependency-closure (future)

Promotion/share workflows must include **dependency closure**. Guardrails will later gain:
- a `promotion.closure` contract kind
- a validator that checks closure completeness or mapping requirements

For now:
- keep the guardrails framework generic
- ensure promotion flows call guardrails gate so future contracts can block merges to official

---

## 10) Folder conventions (expected by agents)

Guardrails code lives in:
- `optaic/guardrails/` (framework)
- business/domain contracts later in:
  - `optaic/domain/<area>/contracts.py` (or extensions), but always registered via ContractRegistry
- docs:
  - `docs/GUARDRAILS.md` (this file)

---

## 11) Minimum acceptance criteria for guardrails work

When adding or modifying guardrails-related code, ensure:

1) **Deterministic hashing** for contract instances
2) **Reports persisted** for each gate evaluation (even when no bundle exists)
3) **Activity events emitted** for validation and blocking
4) **Policy honored** (official blocks; staging warns by default)
5) **Selective installs** do not break imports

---

## 12) Quick reference: “Do / Don’t”

✅ Do:
- attach contract bundles to resources
- validate at lifecycle gates
- log and emit validation results
- keep validators deterministic
- keep heavy deps optional and lazily imported

❌ Don’t:
- embed business-domain specs in guardrails v0
- let plugins bypass the service layer to mutate state
- add top-level imports that break `optaic[sdk]` installs
- skip validation on merges to official

---

## Appendix: Example contract kind list (NO IMPLEMENTATION YET)

- dataset.schema (Arrow schema)
- dataset.freshness (schedule + grace)
- signal.bounds ([-1,1] and index requirements)
- pit.policy (no lookahead constraints)
- portfolio.constraints (weights/leverage/turnover)
- execution.policy (order types, limits, venues)
- promotion.closure (dependency closure + mapping completeness)

These are placeholders to guide future work, not implemented now.
