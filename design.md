Cool — here’s a concrete “freeze-able” blueprint: **tables + key fields + indices**, then **permission matrix + activity catalog + SDK event contracts**. This is designed for **FastAPI + async SQLAlchemy + Postgres**, with **multi-tenant**, **branch/merge**, **promote with approvals**, **chat + notifications**, and **auditor**.

## Database schema

### A) Identity & principals

**tenants**

* `id (uuid pk)`, `name`, `created_at`

**principals**

* `id (uuid pk)`, `tenant_id`, `kind` (`user|agent|service`), `status`
* `display_name`, `email` (nullable for agents), `created_at`

**users** (optional split if you want)

* `principal_id (pk/fk)`, `profile_json`

**agents**

* `principal_id (pk/fk)`, `agent_type`, `config_json`

**Indexes**

* `principals(tenant_id, kind)`

---

### B) Resources (everything is a resource)

**resources**

* `id (uuid pk)`
* `tenant_id`
* `type` (enum)
* `parent_id` (nullable, fk resources.id)  ← hierarchy
* `owner_principal_id` (fk principals.id)
* `space_kind` (nullable: `personal|team|system` for Space only)
* `subspace_kind` (nullable: `official|staging|custom` for SubSpace only)
* `name`
* `status` (`active|archived|deleted`)
* `metadata jsonb`
* `created_at`, `updated_at`

**resource_edges** (optional but recommended once compositions grow)

* `tenant_id`
* `src_resource_id`, `dst_resource_id`
* `edge_type` (`contains|composes|references|derived_from|attaches_to|...`)
* `created_at`
* **unique** `(tenant_id, src_resource_id, dst_resource_id, edge_type)`

**Indexes**

* `resources(tenant_id, type)`
* `resources(tenant_id, parent_id)`
* `resources(tenant_id, owner_principal_id)`
* `resource_edges(tenant_id, src_resource_id)`
* `resource_edges(tenant_id, dst_resource_id)`

Resource types you’ll likely have:

* `Space, SubSpace, Project`
* `DataCatalog, Dataset, Pipeline, Store, Accessor`
* `Experiment, ExperimentTab, Expression`
* `Extension, OpsMacro`
* `Channel, Message`
* `MergeRequest, PromotionRequest, Invitation`

---

### C) Versioning / branching / merging

**resource_versions**

* `id (uuid pk)`
* `tenant_id`
* `resource_id` (fk resources.id)
* `parents uuid[]` (1 parent normally, 2+ for merges)
* `content jsonb` **or** `content_ref` (object store pointer)
* `created_by` (principal)
* `created_at`

**resource_refs** (branches/tags)

* `tenant_id`
* `resource_id`
* `ref_name` (e.g. `main`, `staging`, `feature/x`)
* `head_version_id`
* `updated_by`, `updated_at`
* **unique** `(tenant_id, resource_id, ref_name)`

**Indexes**

* `resource_versions(tenant_id, resource_id, created_at desc)`
* `resource_refs(tenant_id, resource_id)`

---

### D) RBAC (role bindings + policies)

**roles**

* `tenant_id`
* `role_name` (`owner|delegator|operator|viewer|auditor`…)
* `description`
* **unique** `(tenant_id, role_name)` *(or global roles table)*

**permissions**

* `perm_name` (e.g. `RESOURCE_READ`, `RESOURCE_UPDATE`, `RBAC_GRANT`, …) *(global)*

**role_permissions**

* `tenant_id`
* `resource_type` (nullable = applies to all)
* `role_name`
* `perm_name`
* **unique** `(tenant_id, resource_type, role_name, perm_name)`

**role_bindings**

* `id (uuid pk)`
* `tenant_id`
* `principal_id`
* `scope_resource_id` (resource where grant applies; can be Space/SubSpace/Project/etc.)
* `role_name`
* `conditions jsonb` (optional: expiry, attribute constraints, “only staging”, etc.)
* `granted_by`
* `granted_at`
* `revoked_at` (nullable)

**Indexes**

* `role_bindings(tenant_id, principal_id)`
* `role_bindings(tenant_id, scope_resource_id)`
* partial index where `revoked_at is null`

Inheritance rule: authorization walks up `parent_id` until tenant root (with optional “inheritance break” flag in resource metadata).

---

### E) Sharing / transfer / approvals

**invitations**

* `id (uuid pk)`
* `tenant_id`
* `resource_id`
* `inviter_principal_id`
* `invitee_principal_id`
* `proposed_role`
* `status` (`pending|accepted|rejected|expired|revoked`)
* `expires_at`
* `created_at`, `updated_at`

**ownership_transfers**

* `id`, `tenant_id`, `resource_id`
* `from_principal_id`, `to_principal_id`
* `status` (`pending|accepted|rejected|cancelled`)
* `created_at`, `decided_at`

**merge_requests**

* `resource_id (pk/fk resources.id)`  *(MR is a Resource)*
* `tenant_id`
* `target_resource_id`
* `source_ref`, `target_ref`
* `status` (`open|approved|merged|rejected|closed`)
* `required_approvals int`
* `created_by`, `created_at`

**promotion_requests**

* `resource_id (pk/fk resources.id)`  *(PR is a Resource)*
* `tenant_id`
* `moving_resource_id` (root of subtree)
* `from_scope_id`, `to_scope_id`
* `placement` (target subspace/project options)
* `rbac_template_ref` (policy to apply)
* `status` (`open|approved|promoted|rejected|closed`)
* `required_approvals int`
* `created_by`, `created_at`

**approvals**

* `id (uuid pk)`
* `tenant_id`
* `request_resource_id` (MR/PR resource id)
* `approver_principal_id`
* `decision` (`approve|reject`)
* `comment`
* `created_at`
* **unique** `(tenant_id, request_resource_id, approver_principal_id)`

---

### F) Chat + attachments (fully controlled)

**channels**

* `resource_id (pk/fk resources.id)` *(channel is a Resource)*
* `tenant_id`
* `channel_kind` (`dm|group|team|system`)
* `topic`, `settings jsonb`

**messages**

* `id (uuid pk)`
* `tenant_id`
* `channel_id` (resource id)
* `sender_principal_id`
* `body` (text) or `body_json` (for rich)
* `status` (`active|deleted`)
* `edited_at`
* `created_at`

**message_attachments**

* `id`, `tenant_id`, `message_id`
* `object_key`, `filename`, `content_type`, `bytes`, `checksum`
* `created_at`

**read_receipts**

* `tenant_id`, `channel_id`, `principal_id`
* `last_read_message_id`, `updated_at`
* **unique** `(tenant_id, channel_id, principal_id)`

(You can add per-message delivery receipts later if needed.)

---

### G) Activities + outbox (the heart)

**activities**

* `id (uuid pk)`
* `tenant_id`
* `actor_principal_id`
* `resource_id`, `resource_type`
* `action` (string)
* `target_principal_id` (nullable)
* `visibility` (`private|resource|scope|tenant|system`)
* `payload jsonb`
* `authz_decision` (`allow|deny`) *(optional but very useful)*
* `correlation_id` (uuid)
* `created_at`

**outbox**

* `id (bigserial pk)`
* `tenant_id`
* `topic` (e.g. `activity`)
* `key` (e.g. `activity_id`)
* `payload jsonb`
* `created_at`
* `published_at` (nullable)

Subscribers:

* auditor (durable)
* notification router
* search/indexing
* agent runtime

---

## Permission matrix (starter)

Define perms globally, then map them per resource type.

**Core perms**

* `RESOURCE_READ`, `RESOURCE_CREATE_CHILD`, `RESOURCE_UPDATE`, `RESOURCE_DELETE`
* `RBAC_GRANT`, `RBAC_REVOKE`, `RBAC_VIEW`
* `INVITE_CREATE`, `INVITE_ACCEPT`, `INVITE_REJECT`
* `OWNER_TRANSFER_REQUEST`, `OWNER_TRANSFER_ACCEPT`
* `BRANCH_CREATE`, `MERGE_REQUEST_CREATE`, `MERGE_APPROVE`, `MERGE_EXECUTE`
* `PROMOTE_REQUEST_CREATE`, `PROMOTE_APPROVE`, `PROMOTE_EXECUTE`
* `SUBSCRIBE_RESOURCE`, `SUBSCRIBE_DESCENDANTS`, `VIEW_ACTIVITY_FEED`
* Chat: `CHANNEL_POST`, `CHANNEL_EDIT_OWN`, `CHANNEL_DELETE_OWN`, `CHANNEL_MODERATE`, `CHANNEL_VIEW_HISTORY`
* Extensions: `EXTENSION_RUN_TEST`, `EXTENSION_PUBLISH`

**Role intent**

* owner: all
* delegator: RBAC + invites + create/organize, but not destructive deletes in system space
* operator: edit/run/execute, but no RBAC/transfer
* viewer: read + subscribe + view activity where allowed
* auditor: `VIEW_ACTIVITY_FEED` on assigned scopes (and maybe `RESOURCE_READ` metadata only)

---

## Activity catalog (examples you should freeze)

Everything below becomes an `activities.action` value with a consistent payload:

**Resource**

* `resource.created` `{resource_id, type, parent_id}`
* `resource.updated` `{fields_changed}`
* `resource.deleted` `{soft:true}`
* `resource.moved` `{from_parent,to_parent}`

**RBAC**

* `rbac.granted` `{principal_id, role, scope_resource_id}`
* `rbac.revoked` `{principal_id, role, scope_resource_id}`
* `rbac.policy_updated` `{resource_type?, diff}`

**Share/Transfer**

* `invite.created` `{resource_id, invitee, role}`
* `invite.accepted` `{invitation_id}`
* `invite.rejected` `{invitation_id}`
* `owner.transfer_requested` `{to}`
* `owner.transfer_accepted` `{to}`

**Branch/Merge**

* `branch.created` `{ref_name, from_version}`
* `merge.requested` `{mr_id, source_ref, target_ref}`
* `merge.approved` `{mr_id, decision}`
* `merge.executed` `{mr_id, new_version}`

**Promotion**

* `promote.requested` `{pr_id, from_scope, to_scope, placement}`
* `promote.approved` `{pr_id, decision}`
* `promote.executed` `{pr_id, new_ids?}`

**Chat**

* `message.posted` `{channel_id, message_id}`
* `message.edited` `{message_id}`
* `message.deleted` `{message_id}`
* `receipt.read` `{channel_id, last_read_message_id}`

---

## SDK contract (what you expose)

**REST**

* Resource CRUD + move + list tree
* RBAC grant/revoke/list effective permissions
* Share/invite + accept/reject
* Branch/ref ops + MR/PR ops + approvals
* Chat: create channel, history, send/edit/delete message, receipts
* Attachments: create upload session (presigned), finalize attachment
* Activity feed: list activities user can view (filtered by scope)

**Realtime**
All realtime payloads are just `ActivityEvent`:

* channel = `t:{tenant}:u:{user}` for personal notifications
* channel = `t:{tenant}:r:{resource_id}` for resource-scoped watchers (optional)
* channel = `t:{tenant}:c:{channel_id}` for chat

---

If you want, I can turn the above into:

1. a Postgres DDL draft (Alembic-friendly),
2. a Casbin model (`sub, dom, obj, act`) that matches your scopes,
3. and an “effective permission resolution” algorithm (inheritance + overrides + conditions) suitable for async SQLAlchemy.
