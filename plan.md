# FocusOS Implementation Plan

Planning status: **no architecture option has been selected and no application has been implemented**. This document is the only deliverable of this session. Repository inspection found an empty repository apart from Git metadata. Future paths, schemas, commands, and examples below are specifications, not existing implementation.

## 1. Product Goal

FocusOS turns a small, authorized portion of personal work context into grounded tasks and useful actions. Its portfolio value is the complete agent lifecycle: ingestion, structured extraction, source-backed memory, tool selection, deterministic scheduling, authorization, approval, external execution, and an inspectable outcome.

The principal Day-7 demonstration is: sync a selected Gmail message; extract and review a task and deadline; ask the agent for work time; inspect Calendar availability; propose a focus block; approve its exact contents; create one real Google Calendar event; inspect the source and execution record. A dashboard supports this workflow. It is not the main deliverable.

## Architecture Decisions Requiring User Input

All entries are **OPEN**. The option descriptions appear at the point of use below. No option is ranked. Agree on choices before their gates; choices due later do not block independent earlier increments. Product scope limits and safety invariants are distinguished from these architectural choices.

| ID | Decision | Decide before | Dependent work | Can proceed beforehand |
|---|---|---|---|---|
| D1 | Next.js backend or Python backend; repository and hosting shape | 1.1 | All backend paths, deployment, validation/test tools | Planning and account readiness checks |
| D2 | Application identity and Google account connection | 1.4 | Sessions, RLS identity, OAuth callbacks, reconnect | 1.1–1.3 |
| D3 | Direct Supabase access or ORM/SQL access | 1.5 | Repositories, transactions, migrations, RLS context | 1.1–1.4 |
| D4 | Encrypted OAuth credentials: application encryption or database Vault | 2.1 | Token storage, refresh, scheduled sync | Step 1 |
| D5 | Store normalized email bodies or only metadata/evidence | 4.1 | Sources, reprocessing, retention, Gmail normalization | Steps 1–3 |
| D6 | Bounded tool loop or fixed workflow with model tool selection | 7.1 | Agent states, continuation, tests | Steps 1–6, including extraction |
| D7 | Relational project memory or explicit relational entity/edge memory | 3.5 | Project association, memory queries | 3.1–3.4 |
| D8 | Embed on confirmation or in a resumable batch | 7.5 | Embedding status, retrieval latency, sync load | Through 7.4 |
| D9 | User-triggered sync only or user-triggered plus daily schedule | 5.7 | Scheduler authentication, job triggers, settings | Through 5.6 |
| D10 | Per-event approvals or approval of a fixed multi-event batch | 8.1 | Approval payload, partial execution, UI | Steps 1–7 |
| D11 | Per-run context or persistent conversations | 7.1 | Message retention, follow-up commands, UI | Steps 1–6 |
| D12 | Existing LLM API/provider, model and embedding capability | 4.3; embedding part by 7.5 | SDK, schema compatibility, eval, vector dimension | Through 4.2 |
| D13 | Google consent timing and Calendar target/scope | 2.3 | Google grants, Calendar reads/writes and demo account | Through 2.2 |

Record each selected option and any consequence in this document before implementing dependent work. Selecting Python, custom identity, relational edges, persistent chat, or batch approval changes the relevant increments; it does not authorize implementing multiple increments together.

## 2. MVP Definition

### Acceptance scenario

Use a dedicated test Google account and a deliberately selected message with explicit temporal context. Example fixture: received Monday 2026-09-21 at 09:00 in Asia/Jakarta, “The final presentation is Friday September 25. Slides must be submitted one day before.” Extraction should identify the presentation date and a Thursday September 24 **date-only** deadline. It must not invent a presentation time or a 23:59 submission cutoff. An undated “Friday” needs a stated reference time and a clarification when the interpretation is ambiguous.

1. Sign in; set timezone and working hours; connect Google with the required grants.
2. Sync a limited mailbox selection; repeat sync without duplicate sources or tasks.
3. View the source, proposed task, date evidence, project candidate, and any uncertainty. Confirm or correct extraction before treating it as an actionable task.
4. Enter “Find three hours this week for these slides.” If duration, deadline cutoff, project, or calendar scope is missing, ask for it or explicitly present an assumption for confirmation.
5. The agent uses typed read tools, retrieves a relevant memory, and obtains slots from deterministic code.
6. Display one or more proposed blocks totaling the requested duration, or explain the available shortfall. Never fabricate availability.
7. Approve a concrete event payload. Refresh busy intervals and verify permission before writing.
8. Show Google event identity/link and an audit record. Repeated approval or request replay does not create another event.

### Scope boundary

One allowlisted owner/test user is the operational target; data ownership is still enforced and tested with a second synthetic user. One Google connection per user and one selected owned Calendar are sufficient. Scheduling refers only to the calendars explicitly included in the MVP, which the UI must disclose. No claim of global availability across every calendar.

MVP includes manual tasks, basic projects, Gmail text extraction, task/event candidate schemas, selected semantic memory, bounded agent orchestration, read Calendar tools, approved creation of focus events, source links, sync status, run logs, and an offline evaluation report. Extracted real-world events are candidates; they are not silently inserted into Calendar. Documents, email sending, email drafting, event rescheduling, complex task dependencies, and broad autonomy are outside the core deadline.

## 3. Constraints

- Seven focused days, approximately 45–52 engineering/review hours. Day estimates include a brief explanation, verification, and user review for each increment. Waiting for user responses, cloud account access, or OAuth review extends elapsed time; seven calendar days cannot be promised if these block.
- Additional infrastructure spend: $0. Existing LLM access is assumed; embedding access must be confirmed separately. No trials that automatically become paid, paid vector database, always-on worker, Redis, Kafka, or Kubernetes.
- Public portfolio viewing is distinct from allowing strangers to connect Gmail. The live integration remains a controlled test-user demonstration until access and verification requirements are resolved.
- Hosted quota assumptions were checked against official documentation on 2026-09-25; recheck at implementation because plans change. Supabase Free currently documents 500 MB database storage, 1 GB object storage, and 5 GB egress. Keep source caps far below quotas and monitor usage. [Supabase billing](https://supabase.com/docs/guides/platform/billing-on-supabase)
- Supabase Free projects can pause after low activity over a seven-day period. Resume and test before presenting the demo; do not promise uninterrupted service. [Project pausing](https://supabase.com/docs/guides/platform/free-project-pausing)
- Vercel Hobby is intended for personal, noncommercial use. Verify portfolio eligibility before deployment; local execution remains a $0 fallback. [Hobby plan](https://vercel.com/docs/plans/hobby)
- Vercel documents a 300-second Hobby function maximum with Fluid Compute, but runtime/configuration matters. Application work targets a much smaller deadline, initially 20 seconds per resumable request, and never relies on the maximum to finish a whole mailbox or agent run. [Function limits](https://vercel.com/docs/functions/limitations)
- Hobby cron runs at most daily per job and is not precisely timed. It cannot provide near-real-time Gmail ingestion. [Cron usage](https://vercel.com/docs/cron-jobs/usage-and-pricing)

## 4. Architecture Decisions: Backend, Identity, and Persistence

### DECISION D1 — Backend runtime and repository shape

**CONDITION**: Next.js can implement the whole web application; Python may better suit the desired AI engineering experience. A second runtime introduces deployment and contract work within a fixed week.

**OPTION A — One Next.js application**

**DESCRIPTION**: UI, authenticated Route Handlers, agent services, and integration clients run in one TypeScript application. Use the server runtime for secrets and provider SDKs.

**PROS**: One deployment; shared runtime schemas; no cross-service identity transport.

**CONS**: Python libraries cannot be reused directly; request duration and serverless concurrency remain constraints.

**IMPLICATIONS**: Paths below under `src/server` and `src/app/api` are literal candidates. A small function registry is sufficient; no microservices.

**OPTION B — Next.js UI with Python API/agent**

**DESCRIPTION**: Keep a single repository with `web/` and `backend/`. A small FastAPI application owns domain validation, integrations, agent, and writes; Next.js provides the UI and optionally a session-aware proxy. Validate deployment of the Python API as a bounded serverless service or on existing hardware in 1.8.

**PROS**: Python-native extraction/evaluation; clear API boundary; uses existing Python experience.

**CONS**: Two runtimes, duplicated transport types, token verification/proxy rules, two build paths; free hosting must pass a real smoke check.

**IMPLICATIONS**: Translate backend paths to `backend/app/` and Zod server schemas to Pydantic. Use pytest/httpx instead of TypeScript backend tests. Preserve the same increments, API contracts, and database. Add 3–5 hours of contingency by cutting optional UI; if deployment fails, explicitly choose local presentation or revisit D1. Do not quietly assume a paid Python host.

### DECISION D2 — Application sign-in versus Google authorization

**CONDITION**: An application session identifies the FocusOS user; a Google grant authorizes Gmail/Calendar. These are different credentials with different expiry and revocation behavior.

**OPTION A — Supabase Auth Google sign-in plus provider grants**

**DESCRIPTION**: Supabase manages the application session; a server callback captures Google provider credentials and stores them securely. Additional scopes are requested at the agreed consent stage.

**PROS**: Direct mapping to `auth.users` and RLS; fewer session-management components.

**CONS**: Supabase session refresh does not replace Google provider-token refresh; sign-in and integration consent UX must be handled carefully.

**IMPLICATIONS**: `profiles.id` references `auth.users.id`; use server-verified Supabase identity. Capture provider refresh tokens through the server callback, never return them in the UI session DTO. [Supabase Google auth](https://supabase.com/docs/guides/auth/social-login/auth-google)

**OPTION B — Supabase application login with separate Google connection**

**DESCRIPTION**: Use a provisioned email/password test account or another Supabase sign-in method; a separate server OAuth code flow connects Google after login.

**PROS**: Application identity remains usable after Google disconnects; integration consent is explicit and independent.

**CONS**: Two user flows; account-linking and callback state must bind to the current application user. Email-link delivery limits would need validation if that login method is chosen.

**IMPLICATIONS**: Keep `auth.users` and RLS; build `/api/integrations/google/start` and callback in Step 2. Do not automatically merge accounts by an unverified email address.

**OPTION C — Library-managed Google login and application sessions**

**DESCRIPTION**: An established authentication library handles Google OAuth and application sessions outside Supabase Auth.

**PROS**: One auth owner and configurable account/session handling.

**CONS**: More session persistence and security work; Supabase RLS does not automatically recognize this identity.

**IMPLICATIONS**: Add users/session storage in 1.4, with library-managed session verification. Before 1.5, explicitly implement a restricted database role with transaction-local user identity/RLS, or server-only repositories with browser database access denied and tested owner predicates. A service-role key alone is not user isolation. Budget 2–3 additional hours or revisit the scope.

### DECISION D3 — Database access and migrations

**CONDITION**: Supabase supports an HTTP database client and Postgres connections. Transactional claims and ownership checks are needed; a full ORM is not required by the product.

**OPTION A — Supabase client and versioned SQL migrations**

**DESCRIPTION**: User-scoped clients perform ordinary queries. Narrow SQL functions handle atomic job claims and approval transitions.

**PROS**: Fits Supabase JWT/RLS; no serverless connection pool to manage; direct SQL constraints.

**CONS**: Complex transactions use SQL functions; generated database types need refreshing.

**IMPLICATIONS**: SQL owns the schema. Restrict execute privileges and search paths on privileged functions; no public arbitrary query RPC.

**OPTION B — ORM/query builder over Postgres**

**DESCRIPTION**: Use a TypeScript ORM/query builder or Python SQLAlchemy/Alembic according to D1, with pooled connections.

**PROS**: Explicit application transactions and typed query composition.

**CONS**: Connection and migration tooling; the database role may bypass RLS unless deliberately configured.

**IMPLICATIONS**: Choose one migration owner, never competing SQL/ORM schema histories. Prove tenant context and pool cleanup in 1.5; use restricted roles and owner predicates, not an unqualified privileged connection.

## 5. Architecture Principles

1. Deliver a working path before adding breadth. The first useful slice is authenticated task persistence and display; extraction, Calendar reading, and approved writes follow.
2. The model proposes facts or tool requests. It never receives SQL, provider credentials, a general HTTP client, or authority to approve actions.
3. Validate both model output and backend tool results. TypeScript types disappear at runtime; a runtime schema rejects malformed or adversarial input.
4. Generate IDs, ownership, hashes, timestamps, risk class, approval status, and idempotency keys in backend code.
5. Store provenance before extraction and preserve uncertainty. A confidence score is an uncalibrated model signal, not proof.
6. Compute intervals, overlap, timezone conversion, resource ownership, and policy in deterministic code.
7. Persist checkpoints at request boundaries. Neither a sleeping process nor an open browser is required to preserve pending work.
8. Fail closed on unknown permissions, incomplete Calendar pages, expired approval, invalid source references, or uncertain write outcome.
9. One purpose per increment. Introduce tables, libraries, folders, and abstractions only when needed. Never generate a speculative architecture skeleton.

## 6. Proposed System Architecture

The logical architecture is independent of D1: Next.js UI calls an authenticated API; application services own tasks, sources, scheduling, approvals, and persistence; a bounded agent consumes narrow tools; Google and LLM clients are server-only. PostgreSQL is the sole persistent application store, with pgvector for selected semantic memory. No graph database is required.

Logical API contracts, introduced only by the matching increment:

| Route | Responsibility | Introduced |
|---|---|---|
| `GET /api/me` | Verified identity and nonsecret profile | 1.7 |
| `GET/POST /api/tasks` | Owned task listing/creation | 3.3 |
| `PATCH /api/tasks/:id` | Owned, version-checked task updates | 3.6 |
| `GET/POST /api/projects` | Small user-owned project collection | 3.5 |
| Google start/callback; `DELETE /api/connections/:id` | Consent, secure capture, disconnect | 2.3–2.4; 9.5 |
| `POST /api/sources/manual` | Small pasted text fixture or manual source | 4.1 |
| `POST /api/sources/:id/extract` | One bounded extraction operation | 4.5 |
| `POST /api/extractions/:id/confirm` | Validate reviewed candidate and commit task | 4.6 |
| `POST /api/sync/gmail`; `GET /api/sync/status` | One resumable sync page/status | 5.6–5.7 |
| `GET /api/calendar/events` | Complete bounded window or explicit incomplete status | 6.2 |
| `POST /api/agent/runs`; `POST /api/agent/runs/:id/continue` | Start/continue server-owned run | 7.2–7.3 |
| `GET /api/agent/runs/:id` | Owned run status and redacted trace | 7.9 |
| `GET /api/approvals`; `POST /api/approvals/:id/decision` | Review exact action; atomically approve/reject | 8.3 |
| `POST /api/approvals/:id/execute` | Resume approved action, with idempotency | 8.6 |

All mutations check verified identity, input size, ownership, same-origin/CSRF protections for cookie sessions, and request replay keys where relevant. Use 401 for missing identity, 403 for denied permissions, 404 for inaccessible owned resources, 409 for stale versions/conflicts, 422 for invalid domain data, and 429 for throttling. Return safe error codes and correlation IDs, not token/provider dumps.

## 7. Database Design

This is a target model, not one migration. Unless stated otherwise, rows use backend-generated UUID primary keys, `user_id` ownership, `created_at`/`updated_at` timestamptz, and foreign keys. Time instants use UTC; original local dates and IANA timezone names remain explicit. Add composite `UNIQUE(user_id,id)` where needed to enforce same-owner references through composite foreign keys. Do not allow a task owned by A to reference B's source even if a UUID is guessed.

### Tables and introduction order

| Entity; first increment | Important columns and constraints | Why it exists |
|---|---|---|
| `profiles`; 1.6 | `id` PK to chosen identity; timezone; working-hours JSON validated to weekday/minute ranges; active_calendar_id nullable; allowlisted flag server-controlled | Stable ownership and scheduling preferences; no duplicated provider credentials |
| `connections`; 2.1 | id/user_id; provider; provider_subject; display_email; granted_scopes; status; last_refresh_at; UNIQUE(user_id,provider) | Google grant metadata and capability checks |
| `oauth_credentials` in private schema; 2.1 | connection_id PK/FK; encrypted refresh/access values or Vault secret references; expiry; encryption_key_version; token_version; refresh_lease_until | Private token lifecycle; separate from browser-readable metadata |
| `tasks`; 3.1, extended 3.5/4.6 | title, description; status `open/done/archived`; priority enum; due_kind `none/date/datetime`; due_date DATE or due_at timestamptz; due_timezone; estimate_minutes nullable; estimate_origin; project_id nullable; source_id nullable; evidence JSON; confidence nullable; extraction_item_key nullable; version integer | Durable actionable state queried by SQL; original uncertainty preserved |
| `projects`; 3.5 | name; normalized_name; description; aliases JSON array; UNIQUE(user_id,normalized_name) | Small context taxonomy; matching uses known projects, never invented database IDs |
| `source_items`; 4.1, extended 5.4 | kind `manual/gmail/document`; provider_message_id and thread_id nullable; connection_id nullable; title; sender metadata; received_at; source_ref; normalized_body nullable per D5; body_hash; normalization_version; deletion marker | Canonical provenance and deduplication boundary; Gmail metadata lives here rather than a parallel email table |
| `agent_runs`; 4.4 | trigger `extraction/command/eval`; status; model/provider/schema/prompt versions; started_at/finished_at; context refs/counts; safe request summary; checkpoint JSON; iteration/tool counts; tokens/latency/cost nullable; safe error | Smallest audit capability, beginning with one extraction call |
| `extraction_results`; 4.5 | source_id; content_hash; schema_version; prompt_version; model_version; validated_payload JSON; status; reviewed_at; run_id; UNIQUE(source_id,content_hash,schema_version,prompt_version,model_version) | Review queue and reproducible processing; re-extraction does not overwrite accepted tasks |
| `sync_state`; 5.6 | connection_id; kind; selection_hash; committed_cursor text; pending_page_token; run_start_cursor; last_success_at; status; lease_owner/lease_until; retry_count; next_attempt_at; last_error; UNIQUE(connection_id,kind) | Resumable and serialized provider sync; cursor values are opaque strings |
| `tool_calls`; 7.1 | run_id; ordinal; tool_name/version; safe arguments; arguments_hash; risk; status; result JSON; external_id; idempotency_key; latency; retry_count; error; UNIQUE(run_id,ordinal), UNIQUE(user_id,idempotency_key) when key exists | Execution ledger and replay handling; browser clients cannot insert successful execution records |
| `memories`; 7.4 | project_id nullable; source_id nullable; text; kind `decision/fact/preference`; evidence; verified_at; superseded_at; content_hash; embedding_model nullable; embedding_version nullable; embedding_status; embedding vector(d) nullable | Small, traceable long-term semantic items; vector colocated because one chunk per small memory suffices |
| `approval_requests`; 8.1 | tool_call_id; immutable payload; payload_hash; target_connection_id; requested_at/expires_at; status; approved_by/at; decided_at; lease_until; result_ref; version; UNIQUE(tool_call_id) | Persist the exact proposed side effect and human decision across requests |

Task CHECK constraints ensure exactly the permitted date/date-time fields are populated, estimate is a positive bounded integer when present, and confidence lies in [0,1] when present. A date-only deadline is not silently converted to midnight. Extraction item keys derive from persisted extraction candidate identity; repeated confirmation returns the existing task via a unique partial constraint on `(user_id,source_id,extraction_item_key)`. If a new extraction version changes a confirmed task, require explicit reconciliation, not another task or silent replacement.

Source uniqueness is a partial UNIQUE on `(user_id,connection_id,provider_message_id)` for Gmail; manual sources use a client replay key, not global body uniqueness. Different legitimate emails can have identical text. For source edits, retain an immutable extraction evidence snapshot/hash; do not claim that an old quote is verified against a new body.

Indexes: tasks `(user_id,status,due_at)` and `(user_id,status,due_date)`, tasks `(user_id,project_id)`, sources `(user_id,received_at DESC)` and `(user_id,thread_id)`, runs `(user_id,started_at DESC)`, tool calls `(run_id,ordinal)`, approvals `(user_id,status,expires_at)`, and memories `(user_id,project_id)`. Add processing-status indexes only for the queries used. Start vector search with an exact scan over a small filtered memory set; add HNSW only after measured need. Vector dimension is fixed from D12 before migration; mismatched model/dimension must fail validation. [Supabase pgvector](https://supabase.com/docs/guides/database/extensions/pgvector)

### Explicitly evaluated but deferred entities

- `users`: use the chosen auth provider's identity plus `profiles`; only D2-C requires application-managed identity/session tables.
- `events`: Google remains the Calendar source of truth. MVP fetches bounded windows live and records created IDs in tool results. A durable event cache/table is unnecessary; introduce it later if offline views or high read volume require it.
- `email_messages`: folded into `source_items` with provider metadata; no duplicate bodies in two tables.
- `documents`: upload/object metadata and Storage are stretch. The source/extraction contract already supports a future document origin without implementing upload now.
- `embeddings`: colocated in `memories` for one-vector-per-item MVP. Add chunk/embedding tables only when larger documents or multiple models exist.
- `persons`, arbitrary entities/relations: D7-B can add a small edge table, but no general knowledge graph is required by the MVP.
- `conversations/messages`: only if D11-B is chosen. Run state is mandatory regardless.
- `jobs`: sync_state and extraction status are enough for the current two bounded workloads. A general queue is deferred.

### Migration and isolation progression

1. First database increment 1.5 proves connectivity without creating the domain schema; 1.6 adds **only profiles and its ownership policy** (auth-owned tables may already exist).
2. 2.1 adds the tightly coupled connection metadata/private-credential pair.
3. 3.1 adds tasks; 3.5 adds projects and the owned task relation.
4. 4.1 adds sources; 4.4 adds runs; 4.5 adds extraction results; 4.6 adds task provenance fields.
5. 5.6 adds sync state; 7.1 adds tool calls; 7.4 adds memories; 7.5 adds pgvector fields; 8.1 adds approvals.

Every table arrives with its access rules and ownership test. Ordinary reads use user context; elevated calls are narrow and server-only. RLS applies to reads and writes, and write checks prevent ownership reassignment. Private token tables have no authenticated/anonymous grants. Service-role credentials bypass RLS and must never be treated as a user-scoped client. [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)

Ownership alone does not authorize changing execution state. Browser roles may read their redacted run/approval views but cannot directly insert/update tool results, approval decisions, extraction claims, sync cursors, or audit status. Those mutations use narrow authenticated backend operations with explicit ownership and transition checks. Profile updates expose only timezone/working-hours fields; column grants or restricted update operations protect server-controlled allowlisting. Never grant a whole-row client update merely because the row belongs to that user.

Deletion semantics: disconnect stops sync, revokes/deletes credentials, and expires pending proposals; it does not delete external events. “Delete imported data” explicitly removes owned source text, dependent memories, and private extraction payloads; tasks may retain user-edited text only if the user chooses that behavior, with provenance marked removed. Keep only redacted execution IDs/statuses needed for the demo, not private text in an allegedly deleted audit copy.

## 8. Agent Architecture

### DECISION D6 — Orchestration

**CONDITION**: The product needs tool selection and multi-step behavior, but unrestricted loops are unnecessary and expensive to debug.

**OPTION A — Bounded model-driven tool loop**

**DESCRIPTION**: The model selects from an allowlisted registry; backend execution returns typed results until a final answer, clarification, approval pause, failure, or budget boundary.

**PROS**: Demonstrates adaptive tool selection and follow-up reasoning.

**CONS**: More trajectories to evaluate; repeated tool calls and invalid requests need explicit handling.

**IMPLICATIONS**: 7.2 introduces one call, 7.3 adds bounded continuation, and 7.8 adds planning. Checkpoints persist every successful boundary.

**OPTION B — Fixed workflow with model-selected intent/tools inside stages**

**DESCRIPTION**: The model classifies/extracts intent and requests eligible stage tools; application state dictates context gathering, slot computation, proposal, and approval.

**PROS**: Predictable transitions, simpler scheduling tests and failure recovery.

**CONS**: Less flexible beyond supported commands; new workflows require explicit transitions.

**IMPLICATIONS**: The same typed tools and audit trail exist. 7.3 implements bounded stage transitions rather than a general loop. Unsupported commands return a capability explanation.

### DECISION D11 — Conversation persistence

**CONDITION**: A run must survive an approval pause; that does not necessarily require permanent chat history.

**OPTION A — Per-run context with bounded retention**

**DESCRIPTION**: Persist the current run's structured state and only enough messages to resume it; user starts a new run for a new command.

**PROS**: Less private content and simpler context management.

**CONS**: Cross-run conversational references require explicit task/project selection.

**IMPLICATIONS**: No conversations table. UI clearly scopes commands to a run; memory remains explicit and separate.

**OPTION B — Persistent conversations**

**DESCRIPTION**: Add owned conversation/message records, retaining a bounded recent window plus explicit selected memory.

**PROS**: Natural follow-up commands and inspectable history.

**CONS**: Retention/deletion and summarization risks; more UI and schema work.

**IMPLICATIONS**: Split 7.1 into a dedicated chat-storage increment and run-storage increment before coding; add roughly one hour and reduce optional UI. Old messages never grant fresh permission.

### Runtime lifecycle and limits

1. Verify user and command length, apply user/run concurrency limits, deduplicate the client request ID, and create the run before the LLM call.
2. Resolve timezone, selected project/task references, current time, and allowed capabilities from trusted server state.
3. Gather a small SQL context: up to 20 open tasks in a bounded horizon, project metadata, and working hours. Search at most five relevant memories with ownership/project filters. Fetch Calendar only when needed and disclose its time window and freshness.
4. Supply only enabled tool names and JSON schemas. External content is labeled untrusted data with source IDs and lengths; it cannot redefine permissions or system instructions.
5. Validate the provider response shape, tool name, argument schema, ownership, foreign keys, reference existence, granted Google scope, and current resource state. Resolve model references only against server-issued candidate handles or owned IDs. Reject invented IDs and unauthorized email addresses.
6. Create a tool-call record before executing. Read tools execute through ordinary services. A write tool creates an approval request or requires the accepted internal-write policy; it never obtains approval from model text.
7. Return a bounded result envelope to the model. Redact secrets and trim source text; attach source identifiers and completeness flags.
8. Read calls may execute sequentially initially. Cap a returned multi-call list and validate each call before execution. Any proposed external write pauses the run; never execute subsequent side effects in the same model turn implicitly.
9. Persist checkpoint and status before returning HTTP. Approvals resume via a new authenticated request, not an open function waiting for a click.
10. Stop on final response, clarification, approval pause, no progress, exhausted budget, cancellation, or unrecoverable error.

Initial application budgets: at most four model turns, eight tool calls, two repeated identical read requests, one schema repair, one provider retry for transient model failure, and 20 seconds of work per request. Store counters across continuation requests so retries cannot reset the budget. A run can expire after 15 minutes; exact action approvals expire after 10 minutes. These are application design limits to test, not vendor guarantees. A request nearing its deadline yields a persisted continuation, not a fake success.

Transient read errors use short backoff with jitter and respect Retry-After; defer long waits through `next_attempt_at`. Nonretryable 4xx validation/auth errors fail or request reconnect. Provider write timeouts enter `unknown` and reconcile by stable external ID before any repeat. A model final sentence cannot mark a tool successful: only persisted provider evidence can.

Grounding controls: every factual extracted task/date has exact source evidence; availability derives from complete provider results; deadline arithmetic is checked against the source/reference timezone; unsupported facts are flagged; source deletion invalidates its retrieval eligibility. The model may explain why a plan helps, but scheduling validity is computed separately. Log concise decision summaries and evidence, not hidden chain-of-thought.

## 9. Tool Architecture

A small module registry contains name, version, input/output runtime schema, risk, required scopes, policy function, and handler. Avoid a plugin framework. Backend identity is injected separately and cannot be supplied in arguments. Each tool returns `{status, data, source_refs, observed_at, error_code?, retryable?}`. Unknown keys are rejected for write payloads. Date ranges are bounded; arrays and text have explicit size limits.

| TOOL NAME / order | PURPOSE | INPUT SCHEMA | OUTPUT SCHEMA | RISK LEVEL | REQUIRES APPROVAL? | VALIDATION REQUIRED | SIDE EFFECTS | POSSIBLE FAILURES |
|---|---|---|---|---|---|---|---|---|
| `tasks.list` / 1, 7.2 | Read actionable work | status enum, project_ref?, due_before?, limit 1–20 | task DTOs, source refs, truncated flag | Read | No | Owned project, valid date/filter | Audit only | Invalid filter, DB unavailable |
| `calendar.get_events` / 2, 7.3 | Read a complete busy window | start/end RFC3339; calendar_ref from server allowlist | normalized intervals, fetched_at, complete | Read | No | Range <=14 days, scope and calendar ownership | Provider read, audit | Scope denied, pagination timeout, reconnect |
| `calendar.find_free_time` / 3, 7.3 | Compute feasible slots | range, duration_minutes 15–480, split_allowed, task_ref? | slots with server handles, total_minutes, shortfall, calendar snapshot time | Read | No | Valid timezone/work hours; complete Calendar data; deadline bounds | Audit only | Incomplete data, invalid duration, no slot |
| `memory.search` / 4, 7.6 | Retrieve source-backed context | query <=1000 chars, project_ref?, limit <=5 | memory refs, text, evidence, similarity/rank | Read | No | Owned filters, active sources, model/dimension match | Query embedding call, audit | Embedding unavailable; falls back to marked lexical search |
| `calendar.create_event` / 5, 8.2–8.6 | Propose then execute a focus block | selected task/slot refs, title; backend resolves start/end/timezone/calendar into canonical payload | pending approval ID, or executed provider event ID/link | Medium | **Yes, always** | Fresh slot, payload hash, owned target/task, no guests/recurrence, granted write scope | Creates one Calendar event only after approved execution | Expired approval, conflict, unknown outcome, revoked scope |
| `tasks.create` / optional after core | Add an internal task | title, description?, due variant, estimate?, project_ref?, evidence? | canonical task ID/version | Low | Depends: extraction review or explicit user command; otherwise confirm | Runtime schema, source/owner checks, replay key | FocusOS task only | Duplicate, invalid date/project, ungrounded source |
| `tasks.update` / stretch | Modify owned task | task_ref, expected_version, allowed patch | updated task/version | Low/medium | Depends; deadline changes require explicit confirmation | Version/owner, allowlisted fields | Internal task update | Stale edit, missing task, invalid status |
| `email.get_messages` / stretch tool | Agent reads previously scoped messages | bounded selection/cursor, limit <=10 | source refs, subject/snippets, incomplete flag | Read/private | No within connected selection | Ownership and approved ingestion scope; no arbitrary mailbox expansion | Provider read if needed | Scope, quota, deleted message |
| `email.get_thread` / stretch tool | Retrieve context for ambiguity | existing thread_ref, limit <=10 | ordered messages with evidence refs | Read/private | No within selection | Owned source thread, bounded body sizes | Provider read | Large thread, missing message, selection mismatch |
| `email.draft_reply` / stretch | Generate editable local reply | thread_ref, intent, selected slot refs | local draft text and factual refs | Low if local only | No to propose; user reviews before export | Known recipients from source, no invented commitments | Local draft only; no Gmail draft write | Unsupported claims, stale slots, wrong reply recipient |
| `email.send_reply` / post-MVP | Send an approved exact reply | approved local draft reference | provider message/thread IDs | High | Yes; separate exact recipients/body confirmation | Fresh grant, recipients, MIME/thread headers, idempotency/reconciliation | Sends real email | Uncertain send result, duplicates, wrong recipient |

Provider Gmail draft creation is an external write and would require approval plus additional scope. Local draft generation must never masquerade as a Gmail draft. Gmail ingestion clients exist before email agent tools; exposing them to the agent is not necessary for the main slice. Calendar update/delete tools are excluded from the MVP registry, even if a broad provider scope technically permits them.

## 10. Structured LLM Outputs

### DECISION D12 — Model and embedding contract

**CONDITION**: Existing LLM access is unspecified. Native schema support, tool calling, data-use terms, latency, and embedding availability cannot be assumed.

**OPTION A — Existing provider with native structured output/tool calling and embeddings**

**DESCRIPTION**: Use the supplied provider SDK and its constrained schema/tool interface, validating results again locally.

**PROS**: Fewer providers and secrets; native constrained output where supported.

**CONS**: Provider-specific schema restrictions and model behavior; embeddings may use a separate quota.

**IMPLICATIONS**: Record model IDs, vector dimension, schema subset, timeout and usage fields in 4.3/7.5. No model name or pricing is invented in this plan.

**OPTION B — Existing generation provider with separately available embeddings or local embedding evaluation**

**DESCRIPTION**: Keep generation with the available API; use a confirmed no-additional-infrastructure embedding endpoint, or generate/query embeddings locally during the demo.

**PROS**: Works when the generation API has no embeddings; independently controlled retrieval model.

**CONS**: Extra contract and potentially local-only semantic retrieval; large local embedding models are inappropriate inside a small serverless function.

**IMPLICATIONS**: By 7.5 demonstrate both document and query embeddings with the same model. If neither is feasible, explicitly revise the MVP to SQL/lexical memory and record semantic retrieval as incomplete; do not label lexical search semantic retrieval. If native tool calling is absent, validated JSON tool requests are possible, but disclose this in the portfolio and evaluate malformed output.

### Schemas and examples

All examples are specification data, not application code. `schema_version` is required. Unknown properties are rejected; string/array limits and enum values are checked. LLM-generated references are local labels resolved against provided context, never authority-bearing database IDs.

**TaskExtraction v1**, introduced 4.2: title <=200 chars; description <=2000; deadline `{kind: none|date|datetime|unresolved, value: string|null, timezone: string|null, raw_text, reference_time, relation?}`; estimate_minutes nullable and origin `explicit|suggested|unknown`; priority_hint enum; project_candidate nullable from provided list; confidence 0–1; evidence array `{source_ref, quote}`; uncertainties string array. Evidence quotes must exist in the normalized source used for this extraction.

```json
{
  "schema_version": "1",
  "local_ref": "task-1",
  "title": "Submit final presentation slides",
  "description": "Submit the slides before the presentation day.",
  "deadline": {
    "kind": "date", "value": "2026-09-24", "timezone": "Asia/Jakarta",
    "raw_text": "Slides must be submitted one day before",
    "reference_time": "2026-09-21T09:00:00+07:00",
    "relation": {"event_ref": "event-1", "offset_days": -1}
  },
  "estimate_minutes": null, "estimate_origin": "unknown",
  "priority_hint": "unspecified", "project_candidate": null,
  "confidence": 0.9,
  "evidence": [{"source_ref": "source-1", "quote": "Slides must be submitted one day before"}],
  "uncertainties": ["Submission cutoff time is not stated", "Project is not stated"]
}
```

Backend checks the relative-date calculation against validated event-1; it does not schedule work after an unknown cutoff on the deadline date. Ask for a cutoff or propose finishing by the previous local day as an explicit user-confirmed policy.

**EventExtraction v1**, introduced 4.2 only for candidate recognition: local_ref, title, start `{kind:date|datetime|unresolved,value,timezone}`, end nullable, evidence, confidence, uncertainties. Example: `{"schema_version":"1","local_ref":"event-1","title":"Final presentation","start":{"kind":"date","value":"2026-09-25","timezone":"Asia/Jakarta"},"end":null,"evidence":[{"source_ref":"source-1","quote":"The final presentation is Friday September 25"}],"confidence":0.95,"uncertainties":["Time and duration are missing"]}`. It is not a Calendar insert payload.

**Email/DocumentExtraction v1**, introduced 4.2: `schema_version`, `source_ref`, `tasks: TaskExtraction[]`, `events: EventExtraction[]`, `facts: [{text,kind,evidence}]`, `requests: [{kind,text,evidence}]`, `project_candidates`, `uncertainties`. All arrays may be empty for a nonactionable message. Cap total candidates at ten. A complete scheduling-request example is `{"schema_version":"1","source_ref":"source-2","tasks":[],"events":[],"facts":[],"requests":[{"kind":"scheduling_request","text":"Check availability Tuesday afternoon","evidence":[{"source_ref":"source-2","quote":"Are you available Tuesday afternoon for a meeting?"}]}],"project_candidates":[],"uncertainties":["Meeting date, duration and afternoon time range need confirmation"]}`. For the presentation source, populate tasks/events with the complete objects above. Person/request/decision extraction is optional evidence-bearing metadata, not separate tables in the MVP.

**AgentToolRequest v1**, introduced 7.1: a discriminated union of known `name`, `arguments`, and `schema_version`. Provider call IDs may be captured for transport correlation but cannot serve as execution authority. Example: `{"schema_version":"1","name":"tasks.list","arguments":{"status":"open","limit":10}}`. For create-event requests the model selects server-provided slot/task handles; backend constructs the immutable provider payload.

**PlanningResponse v1**, introduced 7.7: `status: proposed|needs_clarification|insufficient_time`; `task_refs`; `blocks: [{slot_ref,task_ref,title,reason,evidence_refs}]`; `requested_minutes`; `scheduled_minutes`; `shortfall_minutes`; `assumptions`; `questions`; `summary`. Example: `{"schema_version":"1","status":"proposed","task_refs":["owned-task-1"],"blocks":[{"slot_ref":"slot-1","task_ref":"owned-task-1","title":"Prepare presentation slides","reason":"Complete work before the confirmed deadline","evidence_refs":["source-1"]}],"requested_minutes":180,"scheduled_minutes":180,"shortfall_minutes":0,"assumptions":[],"questions":[],"summary":"One available three-hour block is ready for your review."}`. Backend computes totals and validates slot membership; model totals cannot authorize execution. Preview labels proposed blocks as proposals until tool results prove creation.

**Backend-owned fields**: UUIDs, user and connection identity, UTC conversion result, trusted current time, evidence offsets/hash, normalized project ID, source URL, approval requirement/status, tool ordinal, calendar ID, request/payload hash, idempotency key, model telemetry, execution outcome. Model-owned candidates are descriptions, entity relationships, intent, proposed priority/estimate, and explanatory text, all subject to validation and review.

Introduce one schema family when its feature appears. Do not create all contracts in 1.1. A schema failure produces one controlled repair attempt; another failure leaves the item unconfirmed with an actionable error, not partially saved tasks.

## 11. Gmail Integration

### DECISION D4 — Credential encryption ownership

**CONDITION**: Background access needs a refresh token; ordinary profile storage and browser sessions are not appropriate secret stores.

**OPTION A — Application encryption into a private database table**

**DESCRIPTION**: Server code uses authenticated encryption with a deployment secret, a random nonce per value, associated connection identity, and a key version.

**PROS**: Portable between backend runtimes and local/hosted deployment; explicit lifecycle.

**CONS**: Application owns correct encryption use, key backup/rotation, and deployment consistency.

**IMPLICATIONS**: Use established crypto primitives, not custom cryptography. Keep the key outside PostgreSQL and out of public environment variables. Verify tamper failure in 2.2; loss of key means reconnect.

**OPTION B — Supabase Vault with restricted access**

**DESCRIPTION**: Store provider secrets through Vault and retain private references in connection credentials.

**PROS**: Database-managed encrypted secret storage; less application encryption code.

**CONS**: SQL privileges and decrypted access paths require care; stronger Supabase coupling.

**IMPLICATIONS**: Verify availability and exact access behavior in the selected project before 2.2. Only a narrow server function/role can access decrypted values; browser roles cannot. If unavailable, revisit D4 instead of storing plaintext. [Supabase Vault](https://supabase.com/docs/guides/database/vault)

### DECISION D13 — Consent timing and Calendar scope

**CONDITION**: Gmail is needed for extraction, while Calendar writes arrive later. OAuth permission can be broader than the application's tool policy, and consent timing affects the early risk test.

**OPTION A — Incremental consent, selected owned Calendar**

**DESCRIPTION**: Request Gmail read and Calendar event read at connection; request an owned-events write grant when enabling approved scheduling. A dedicated test calendar can be selected from owned calendars.

**PROS**: Write access is requested when its purpose is visible; a controlled calendar limits demo mistakes.

**CONS**: A second consent interaction; scope upgrade must be tested early rather than left until Day 6.

**IMPLICATIONS**: 2.6 verifies the scope-upgrade path without creating an event. 8.6 still requires approval for writes. Read/list scopes must match whether selecting calendars or using a known primary calendar ID.

**OPTION B — Combined consent for Gmail read and owned Calendar events**

**DESCRIPTION**: Request the needed read/write event permission at connection, selecting one owned calendar for all scheduling.

**PROS**: One consent pass tests the final required grant early.

**CONS**: Write-capable permission exists before the app supports writes; users see a broader initial prompt.

**IMPLICATIONS**: Backend policy still disables all writes until Step 8. Token scope alone never permits a tool action. Shared-calendar support is a later scope/product expansion.

Scope planning: Gmail body extraction requires `https://www.googleapis.com/auth/gmail.readonly`; metadata-only access cannot provide message bodies. Gmail readonly is a restricted scope. A public app may require verification and, depending on handling, additional assessment; the seven-day target is an authorized test-user demo, not verified public Gmail onboarding. Never request Gmail modify, compose, or send for the core slice. [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)

For Calendar, evaluate `calendar.events.readonly` for reads and `calendar.events.owned` for writes to calendars the user owns; include `calendar.calendarlist.readonly` only if building a calendar picker. Request `openid email profile` only for the selected identity flow. Check returned grants, not the requested list. [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth)

OAuth flow: configure consent screen, test-user list, enabled APIs, exact localhost and stable hosted redirect URIs; initiate authorization with CSRF state bound to the session and a short expiry; use the selected library's code-flow/PKCE protection; exchange server-side; validate account binding and scopes; encrypt credentials before returning a minimal success page. Request offline access; preserve an existing refresh token if a later response omits one. Serialize refresh using a connection lease/version so competing requests do not overwrite newer credentials. `invalid_grant` marks reconnect required; do not repeatedly retry it. Google test-mode refresh tokens with these scopes can expire after seven days, so rehearse reconnect before the final presentation. [Google OAuth lifecycle](https://developers.google.com/identity/protocols/oauth2)

### DECISION D5 — Email body retention

**CONDITION**: Extraction and evidence validation need message content; retaining complete bodies increases private data and storage.

**OPTION A — Retain capped normalized text**

**DESCRIPTION**: Store selected plaintext bodies, source metadata, content hashes, and evidence; use a stated short retention period such as 30 days.

**PROS**: Repeat extraction and source inspection do not need another Google read; deterministic evidence checks.

**CONS**: More private data at rest; deletion and log redaction must cover copies.

**IMPLICATIONS**: Store at most 20 KB normalized text per source initially; mark truncation. Only selected messages qualify, and retention cleanup runs in bounded requests.

**OPTION B — Retain metadata, hashes, and minimal evidence**

**DESCRIPTION**: Process body in memory, retaining confirmed quotes and extraction results; re-fetch the body when reprocessing.

**PROS**: Smaller raw-source footprint.

**CONS**: A deleted message or revoked grant prevents reprocessing; quotes and derived facts still contain private content.

**IMPLICATIONS**: Persist evidence snapshots and original hashes at extraction time. The UI distinguishes unavailable source text from a missing task. Re-fetch failures never erase confirmed user data automatically.

Under Option B, a manual-source client retains the entered text until extraction completes and submits it to the extraction endpoint, which checks its hash against the owned source record. A retry requires resubmitting that text. Gmail extraction re-fetches the selected message on demand and verifies its current hash; a changed body becomes a new extraction version. Do not build a deferred extractor that expects an unstored body to remain in server memory across requests. Only validated evidence/results survive afterward under the chosen retention rules.

### Bounded synchronization algorithm

1. User chooses a dedicated pre-existing label or a restricted query such as a recent date window plus explicit senders. Do not equate unread mail with unprocessed mail. Initial cap: 50 IDs, fetch pages of at most ten, normalize at most three bodies per request. Explain and display the selection.
2. Capture a mailbox history anchor before the initial listing. Fetch IDs/metadata first; fetch bodies only for selected candidates. Preserve a pending page token when the bounded request ends. If the initial cap truncates a selection, mark it incomplete and require user continuation or narrower selection; do not label it fully synced.
3. Normalize headers, decode base64url and MIME charsets, prefer text/plain, convert HTML to text without executing/rendering it, and cap content. Preserve message/thread IDs and received time. Quoted replies are source context, not automatically fresh tasks.
4. Upsert each source by provider message identity. Selection and content hash determine whether extraction is necessary; schema/prompt/model version determines whether an explicit reprocess differs. Previously confirmed output is never re-created merely because labels change.
5. For subsequent sync, consume history changes after the committed history ID, paginate, fetch affected message metadata, and apply the same selection filter. Added/deleted messages and relevant label changes update source status. History IDs are strings, not JavaScript numbers, and are not consecutive counters.
6. Commit durable source changes/page checkpoint before advancing the committed cursor to the completed history response. AI extraction is separate; ingestion can complete while a source awaits extraction. A crashed extraction therefore cannot cause a missed message.
7. On an expired history cursor/404, mark a bounded rescan required and reuse the initial selection, not a full-mailbox download. Dedupe still applies. A user must continue if a rescan exceeds the cap. Google documents full/partial sync and expired history recovery. [Gmail synchronization](https://developers.google.com/workspace/gmail/api/guides/sync)
8. Use a per-connection lease and atomic checkpoint update to prevent competing tabs or scheduled invocations from racing. Rate-limit sync and persist retry time on quota errors.

Threading: keep every message's own evidence; later messages may supersede earlier deadlines, which produces a review item rather than silently overwriting a task. MVP fetches selected messages only; thread expansion is optional and bounded. Attachments are not fetched, OCRed, or sent to the model in the MVP. Display “Attachment not processed” when relevant. Source links are constructed from trusted provider IDs; retain canonical provider references even if an account-specific Gmail deep link is unavailable.

Only selected sources enter the extraction queue. Cheap filters remove empty, oversized, or excluded messages; avoid a brittle keyword filter that silently drops relevant deadlines. Let the extractor emit empty candidate arrays. User-visible processing states: `pending`, `processing`, `needs_review`, `confirmed`, `ignored`, `failed`, `source_unavailable`; claims expire and can be resumed.

## 12. Calendar Integration

Use an owned, explicitly selected calendar. Fetch a bounded planning horizon, initially 14 days, with `singleEvents=true` so Google expands recurring occurrences. Follow all pages before returning `complete=true`; provider cancellation/deletion and recurring exceptions must be respected. A page or timeout failure means availability is unknown. Normalize provider IDs, recurring-event ID/original start when available, status, transparency, response state, all-day bounds, and observed time. [Calendar list semantics](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)

MVP does a fresh bounded read for planning and immediately before writing. It does **not** maintain a durable Calendar sync-token cache. Later incremental synchronization needs a separate consistent query: Google's sync-token mode excludes time-window parameters, and a 410 requires full synchronization. Do not combine a rolling window with a sync token. This limitation is a reason to defer Calendar caching, not to drop pagination.

Timezone rules:

- Profile timezone must be an IANA name; propose Asia/Jakarta in UI only as a confirmed user preference, not a universal hardcode.
- Provider timed events preserve offsets and zone information, then convert to UTC instants for comparisons.
- All-day events use date ranges whose end is exclusive; expand midnight boundaries in the calendar's timezone before comparing. Conservatively treat busy all-day events as blocking working hours.
- Exclude cancelled events and transparent events from busy intervals. Treat tentative events as busy; declined invitations can be excluded according to a documented deterministic rule.
- Test a DST-observing zone, including nonexistent/ambiguous local times. Do not calculate “tomorrow” by adding 24 hours to a local timestamp; use calendar-date arithmetic.

Free-time algorithm: clip intervals to each working-hours window; include a fixed configurable buffer; sort; merge overlapping/touching busy intervals; subtract from working windows; intersect with task deadline constraints; generate slots meeting minimum length; select deterministically until requested duration is filled. User input controls contiguous versus split work. Tie-break by due date, explicit priority, then stable task ID/start time. LLM reasoning explains project relevance and chooses among valid candidates; it does not produce the busy/free calculation. Task dependency graphs and optimal scheduling are post-MVP; unresolved stated dependencies produce clarification.

Calendar write payloads have summary, start/end, timezone, selected calendar, task reference, and private FocusOS action marker. No attendees, recurrence, conferencing, reminders that contact others, or arbitrary provider fields in the MVP. Request no notification sends. Re-read busy data and serialize FocusOS writes per connection before insert. A new external event can still appear between read and insert because Google offers no cross-system transaction; disclose this residual race and show any detected conflict after execution.

Idempotency: generate one stable provider-compatible event ID from the stored action UUID, for example lowercase UUID hex without hyphens (allowed characters, ample uniqueness), before the first insert. Retries reuse it. Store a private action marker. On timeout or duplicate-ID response, get the event by ID and verify its marker and expected payload; never blindly retry with a new ID or treat any collision as success. Google documents allowed ID characters and uniqueness considerations. [Calendar insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)

## 13. Memory and Retrieval

### DECISION D7 — Personal knowledge representation

**CONDITION**: The application must relate projects, tasks, and evidence; a general graph may add little to a small dataset but could demonstrate relationship queries.

**OPTION A — Relational projects, tasks, sources, and memories**

**DESCRIPTION**: Explicit foreign keys and a small set of typed records represent current context.

**PROS**: Simple SQL, constraints, ownership checks, and straightforward UI.

**CONS**: Arbitrary person/decision/dependency traversals need later schema changes.

**IMPLICATIONS**: The table design above applies directly. A project page and filtered memory search are enough.

**OPTION B — Relational model with a small typed edge table**

**DESCRIPTION**: Keep core task/source tables, and add `context_edges` for only proven relations such as `supersedes` or `supports`.

**PROS**: Explicit provenance relationships and limited traversal without another database.

**CONS**: More endpoint validation, cross-owner checks, and relation semantics.

**IMPLICATIONS**: Split 3.5 before implementation into projects and one concrete relation increment, with tests for both edge endpoints. Do not generate a universal graph ontology; budget the additional review time.

| Memory class | Contents | Access and retention |
|---|---|---|
| Short-term context | Current command, bounded recent tool results, checkpoint, pending proposal | Per-run state; not all past conversations in every prompt |
| Structured long-term memory | Projects, confirmed tasks/deadlines, working hours, user-corrected facts | SQL ownership/project/date/status filters; authoritative for scheduling |
| Semantic memory | Small confirmed decision/fact summaries with exact source evidence | Selected embeddings; similarity supplements facts, never replaces constraints |
| Raw source data | Selected email metadata/body per D5; future documents | Provenance and reprocessing; not all automatically embedded |

Smallest useful memory is tasks plus projects queried with SQL. At 7.4 add a few short confirmed facts, e.g. “The project demo must include a Calendar write,” then at 7.5 embed those records. Do not embed access tokens, entire mailboxes, duplicate signatures, every task update, or raw audit logs.

### DECISION D8 — Embedding timing

**CONDITION**: Embedding a confirmed memory may add request latency, while deferring it requires durable progress and a way to trigger work.

**OPTION A — Embed when the user confirms a memory**

**DESCRIPTION**: Confirmation writes the memory; a bounded follow-on request embeds that one item and marks it ready.

**PROS**: Immediate relevance and simple user-visible progress.

**CONS**: Confirmation-to-search latency depends on the provider; failures need a retry button.

**IMPLICATIONS**: Save the memory before external work; an embedding failure cannot lose confirmed content. Search can use SQL while pending.

**OPTION B — Embed pending items in a resumable batch**

**DESCRIPTION**: A bounded manual/dashboard/scheduled invocation claims a few pending memories.

**PROS**: Predictable confirmation latency and grouped provider calls.

**CONS**: Delayed search freshness and another pending state to explain.

**IMPLICATIONS**: Reuse persisted claim/retry behavior; no new worker/queue service. UI shows pending count and last completion.

Search: apply owner and project constraints in the database, discard superseded/deleted-source items, calculate cosine similarity for ready vectors, return up to five with evidence. Combine exact SQL matches for project/task names with semantic results using a simple documented rank merge and ID dedupe. Keep dates/statuses in SQL. Never fetch all users' nearest vectors and filter ownership in application code. Query/model mismatch or embedding failure produces a visibly labeled lexical/SQL fallback. No reranker or elaborate memory framework is needed for the small corpus.

## 14. Approval and Permission System

### DECISION D10 — Approval unit

**CONDITION**: A three-hour plan may contain several events. Approval granularity affects review effort and partial failures.

**OPTION A — One approval per event**

**DESCRIPTION**: Each event has its own immutable request and approve/reject controls.

**PROS**: Small failure boundary; clear independent consent and retry.

**CONS**: More clicks for split schedules.

**IMPLICATIONS**: One `approval_requests` row per tool call. A multi-block plan does not imply consent for the remaining blocks.

**OPTION B — Approve one immutable batch of events**

**DESCRIPTION**: The user approves a complete displayed list; each event still has its own execution and idempotency record.

**PROS**: One review for an entire proposed schedule.

**CONS**: Partial success and stale subsets need more UI and state.

**IMPLICATIONS**: Add a parent batch reference in a separate increment before 8.3. On partial failure, preserve successes and ask again for changed items. No automatic rollback deletion. Budget an extra hour; never treat approval as a distributed transaction.

Permission policy lives in backend code, not model prompts. Reads require user session and relevant grants. Internal task creation requires user confirmation of extraction or an explicit task-creation request; unsolicited agent-created tasks remain proposals. Calendar create always requires approval. Send/delete/reschedule tools are absent in the MVP.

State progression: `pending -> approved|rejected|expired`; `approved -> executing -> succeeded|failed|unknown|stale`. Approval binds to authenticated user, connection/calendar, tool version, canonical payload hash, expiry, and task version. The decision endpoint accepts the approval ID and decision only, not replacement event arguments. Editing a proposal creates a new version/approval and invalidates the old one.

Use compare-and-swap/row locking to claim execution. Concurrent clicks return the same action status. A crash during execution leaves a lease and unknown result; after expiry reconcile provider ID before retry. Freshly changed busy intervals, task deadlines, connection status, or permissions can invalidate an approved action. Rejecting approval cannot be overridden by the agent. Pending approval state survives reload and does not occupy a serverless invocation.

Preview includes event title, exact date/time/timezone, duration, calendar/account, linked task/source, any assumptions, and whether guests/notifications are absent. Execution result separately shows actual provider outcome. User can cancel a pending proposal; deleting a created event remains a manual Calendar action during MVP.

## 15. Background Processing

### DECISION D9 — Sync triggers

**CONDITION**: Free hosting has bounded invocations and cannot promise continuously running workers or frequent cron execution.

**OPTION A — Manual and dashboard-triggered bounded processing**

**DESCRIPTION**: “Sync Now” starts one page; the UI can request the next while open. Dashboard opening may request a refresh only if stale and not already leased.

**PROS**: No scheduler setup; obvious progress and error feedback.

**CONS**: No ingestion while the app is closed; user must reopen/resume pending work.

**IMPLICATIONS**: Label synchronization as on-demand. Persist progress so closing a tab loses no committed work; do not claim background completion continues after response termination.

**OPTION B — Same flow plus a daily scheduled invocation**

**DESCRIPTION**: One authenticated daily cron invokes the same bounded processing service for allowlisted active connections, resuming remaining work on the next trigger.

**PROS**: Some unattended freshness without another service.

**CONS**: Coarse timing and partial completion under limits; cron authentication and overlap handling required.

**IMPLICATIONS**: Protect the endpoint with a server secret; scope its work explicitly; reject ordinary anonymous requests. Missed runs are visible, not silently assumed successful. The free-tier daily restriction remains. [Vercel cron](https://vercel.com/docs/cron-jobs/usage-and-pricing)

Gmail push is evaluated and deferred: watches, Pub/Sub delivery, subscription authorization, renewal, duplicate notifications, and reconciliation add deployment surfaces without improving the required demo. It is post-MVP, not an unstated dependency. A future push message would only trigger the same history consumer.

Work states and leases are PostgreSQL records. Claim a bounded unit atomically, perform provider work outside long database transactions, then atomically record the outcome/checkpoint. Do not keep locks during model/provider HTTP calls. Backoff timestamps survive request termination. An abandoned claim is recoverable; an uncertain write requires reconciliation. No fire-and-forget promise, in-process timer, or local filesystem queue is considered durable.

## 16. Security

Controls arrive with their feature, not on the last day:

| Control | First increment | Concrete verification |
|---|---|---|
| Private/public environment separation; ignored secret files | 1.2 | Missing secret fails safely; client bundle contains no provider/service key |
| Verified server session and protected routes | 1.4/1.7 | Forged/missing/expired session cannot read profile/tasks |
| Ownership policies and same-owner foreign keys | 1.6 then each table | User B cannot read, create references to, or mutate A's records |
| Encrypted credentials and strict private grants | 2.1–2.2 | Anonymous/user roles cannot select tokens; tampered ciphertext cannot decrypt |
| OAuth CSRF/account binding/redirect validation | 2.3–2.4 | Wrong state, reused callback, or external redirect is rejected |
| Input validation and mutation CSRF/origin checks | 3.2–3.3 | Overlong title, invalid dates and cross-origin writes fail |
| Source sanitization and no remote fetching | 4.1/5.3 | Script HTML becomes text; image/URL in email causes no network request |
| Prompt-injection containment | 4.3, 7.1–7.3 | “Ignore instructions and send mail” remains data; forbidden tools cannot dispatch |
| Per-user rate/concurrency limits | 4.5/5.6/7.3 | Repeated requests are throttled across instances using persisted timestamps/counters |
| Exact approvals and replay-safe writes | 8.1–8.6 | Payload substitution, duplicate clicks, and stale proposals cannot create unintended events |
| Redaction, retention, disconnect/delete | 4.4 then 9.5 | Logs contain no credentials; disconnect disables work; data removal covers derived copies |

Never trust a model-provided URL for an arbitrary server fetch; trusted source links are display-only and restricted to expected provider hosts. User-controlled source HTML is not rendered unsanitized. Treat tool results from external systems as untrusted content too. Grant checks, registry allowlists, and ownership checks remain effective even when a prompt defense fails.

Show connected data usage before sync, including that selected content is sent to the configured LLM provider. Before using real mail, confirm provider retention/data-use settings and the user's willingness to use them. The demo dataset contains synthetic content and never commits private mail, credentials, token-bearing URLs, or production database exports. This is an application data-flow requirement, not a plan to implement legal/compliance infrastructure.

Environment contract grows incrementally: app origin; Supabase URL and publishable key; private server DB/service credential only where needed; Google client ID/secret; token encryption key or Vault access configuration; LLM key/model; embedding model/dimension; optional cron secret. Exact names depend on D1–D4. Public environment prefixes are reserved for genuinely public values. Never create actual secrets during this planning task.

## 17. Observability

Start with one `agent_runs` record in 4.4: trigger, status, model/schema/prompt version, timing, usage if provided, and safe error. Add context counts/IDs and tool-call records in 7.1; add approval transitions in Step 8; expose a minimal run-details page in 7.9 and enrich it in 8.7.

A demo trace should show: run ID; triggering user command or extraction source; five tasks/three events/two memories retrieved; observed Calendar time and completeness; model latency; tool name and sanitized arguments; required approval and human decision time; provider event ID; success/failure/unknown; aggregate tokens. These are measured fields, not hardcoded example success data.

Store token categories separately when provider supplies them; otherwise record unknown. Calculate estimated LLM cost only with a user-supplied dated model-price configuration, and label it an estimate. No assumed provider price or exact cost when usage is missing. Log provider latency, tool latency, total run duration, attempt count, and correlation IDs. Never log refresh tokens, authorization headers, raw full prompts, or chain-of-thought. A concise grounded explanation is sufficient.

Use database records, local JSON output, and hosting logs; no paid monitoring platform. Pending/failed sync counts and a reconnect indicator are more useful than elaborate charts. Keep metrics low-volume and apply retention to private arguments/results as well as sources.

## 18. AI Evaluation

Build a versioned synthetic JSONL dataset in 9.1, with early smoke fixtures in 4.2. Target 24 held-out cases: eight task/date extraction, four ambiguity/no-action, four scheduling, four tool/approval policy, and four adversarial/injection/ownership cases. Use six separate development examples; do not tune prompts on the held-out set and report it as unseen performance. Include at least two fixtures each for date-only deadlines, explicit local time, missing project, and conflicting/newer email information across these groups.

Each case has `case_id`, `category`, `reference_now`, `user_timezone`, source text/IDs, owned task/project context, provider fixture events, and expected outcomes. Expected outcomes contain normalized facts, required evidence spans, permissible titles/intent labels, expected tool/clarification, forbidden actions, and scheduling invariants. Example input: “Please submit Assignment 3 by Friday at 23:59,” anchored to Monday 2026-09-21 in Asia/Jakarta. Expected due instant is 2026-09-25T23:59:00+07:00 only under that explicit week convention; a deliberately ambiguous counterpart should request clarification.

Runner behavior: load versioned cases; call the real extractor/model in a separate opt-in command; capture output and provider metadata; apply the same validators as the app; execute tool fixtures through mocks only; write machine-readable results and a short Markdown/HTML report. The normal unit-test/CI suite uses recorded synthetic fixtures and never sends real mail or writes Google events. Freeze time and provider fixtures for reproducibility. A separate manual live smoke test proves Google access and the approved Calendar write.

| Metric | Calculation / judgment | Target for demo, not an asserted result |
|---|---|---|
| Structured-output validity | First-attempt and post-repair valid outputs / attempted calls | >=95% after bounded repair; report small sample counts |
| Task extraction precision/recall/F1 | Match expected semantic task to candidate one-to-one, then count TP/FP/FN | >=0.85 F1 on labeled set |
| Deadline correctness | Exact normalized date/instant and granularity for resolvable cases; correct abstention on ambiguous ones | >=90% on resolvable cases; no fabricated time in ambiguous cases |
| Tool selection | Correct allowed tool/stage or clarification / decision cases | >=90%; report confusion/errors |
| Evidence correctness | Quoted span exists and supports the claimed fact; exact match plus human semantic check | 100% quoted-span validity; report support judgments |
| Unsupported-action rate | Proposed writes lacking source/user intent or valid resources / proposed writes | 0 in safety fixtures |
| Permission safety | External writes without valid approval, cross-user reads/writes | 0; release blocker regardless of average |
| Scheduling validity | No overlaps, deadline/work-hour constraints, requested duration or correct shortfall | 100% deterministic fixtures |
| Tool success | Successful mock/live calls / attempts, separately reported | No mixed simulated/live denominator |
| Latency/usage | Median and observed tail, sample count, input/output tokens, configured estimated cost | Report actual values; no unsupported SLA |

Titles/paraphrases require a short human rubric: same action, object, and obligation. Dates, refs, tool schemas, ownership, approval, and time arithmetic are deterministic. Do not use an LLM judge for the safety gate. Include a case where a syntactically valid quote supports the wrong task: string match alone is insufficient factual grounding. Repeat a small subset three times if budget permits to expose model variability; otherwise state single-run limitations.

9.2 first runs extraction; 9.3 adds exact/semantic scoring and aggregate metrics; 9.4 adds adversarial/tool/scheduling regression gates. A static report linked from Agent Runs is enough; an evaluation dashboard is optional.

## 19. UI Architecture

Use basic accessible forms, lists, loading/error states, keyboard controls, and visible timezone labels. Avoid a design system project or drag-and-drop calendar. Component libraries and styling choices can follow the selected scaffold's minimal setup; no custom visual assets are needed.

| Surface | First useful version | Later addition |
|---|---|---|
| Shell/login | 1.1, 1.4: app name, sign-in state | Small navigation as screens exist |
| Tasks/Today | 3.4: create/list real tasks | 3.6 done/edit; 6.5 schedule with fetched-at indicator |
| Settings | 1.6 timezone/hours; 2.4 connection status | 5.7 sync selection; 9.5 disconnect/delete |
| Inbox/Activity | 4.7: one extraction review and evidence | 5.7 processing/error counts and Sync Now |
| Agent | 7.9: command input, grounded result, continuation/clarification | 8.3 links/cards for pending approvals |
| Approvals | 8.3: exact immutable preview, approve/reject | 8.7 executed/unknown/stale result |
| Memory/Projects | 3.5 tiny project selector; 7.4 compact memory list | Separate browsing screen only if time remains |
| Agent Runs | 7.9: run details and tool history | 8.7 approval/provider outcome; optional eval report link |

“Move my work to Wednesday” must return an unsupported-capability explanation during MVP, rather than pretending rescheduling exists. Confirmation dialogs cannot use a vague “Approve AI action”; they must display the actual destination and time. Error views include retry/reconnect/clarify actions appropriate to the error category.

## 20. Repository Structure

These are eventual responsibilities, **not folders to generate now or all at 1.1**. D1-A candidate paths:

```text
plan.md
src/
  app/                      pages/layout and thin authenticated API adapters
    api/                    routes introduced with each capability
  components/               only reused UI pieces that actually exist
  domain/                   task/source/calendar/plan runtime contracts
  server/
    auth/                   session verification and ownership context
    db/                     narrow owned queries and transaction/RPC helpers
    integrations/google/    OAuth, token refresh, Gmail and Calendar clients
    ingestion/              normalization, sync checkpoints, extraction claims
    ai/                     provider adapter, extraction prompts/validators
    agent/                  run state, bounded orchestration, context assembly
    tools/                  typed registry and thin service-backed handlers
    scheduling/             deterministic interval/timezone calculations
    approvals/              policy, payload canonicalization, execution state
    memory/                 selected memories, embedding and retrieval
    observability/          redacted run/tool logging
supabase/migrations/        ordered SQL migrations if D3-A
tests/                      unit/integration/security tests with provider mocks
evals/                      labeled JSONL, runner and generated redacted reports
docs/                       setup/demo notes only when needed
```

D1-B mapping: `web/src/app` and `web/src/components` retain UI; `backend/app/{api,domain,auth,db,integrations,ingestion,ai,agent,tools,scheduling,approvals,memory,observability}` owns backend behavior; `backend/tests` uses pytest; `backend/evals` runs evaluation. Migrations live in one chosen root/tool. There is no duplicated agent in the UI layer. Shared API contracts are documented/generated from the runtime schemas rather than hand-maintained parallel business logic.

Tooling, installed only when the applicable increment is authorized: TypeScript runtime validation/test runner (e.g. Zod/Vitest) or Pydantic/pytest for Python; provider SDK after D12; Google client library or narrow HTTP wrapper; a timezone-aware date library once scheduling needs it; SQL migrations chosen in D3; a small Playwright smoke test only for the critical UI workflow near release. No agent framework, ORM, queue, or UI library is added merely because it is popular.

## 21. Detailed Dependency-Ordered Implementation Plan

Phase 0 is this plan and decision recording. Phases 1–9 below correspond to STEP 1–9, not whole-day coding commands. The critical path is foundation -> Google risk probes -> task slice -> extraction slice -> durable Gmail ingestion -> deterministic Calendar availability -> read/planning agent -> approved write -> release evidence. The early raw Google probes are deliberately separate from complete integrations.

All paths are illustrative D1-A paths; use Section 20's Python mapping if D1-B is selected. Exact commands are finalized with the selected tooling: `npm run typecheck`, `npm run lint`, `npm run build`, and `npm test -- <test-file>` for a TypeScript implementation; `python -m pytest <test-file>` plus the selected Python checker for the backend alternative. These scripts do not exist yet. Each verification below names the behavior a check must establish, not just “tests pass.” Run relevant focused checks during each increment; broaden to release checks in Step 9.

Sizes: **tiny** means one contract/config or focused function; **small** means a cohesive function/route/table with verification, typically 1–3 implementation files; **moderate** means a tightly coupled boundary with a few files and meaningful tests. A moderate increment is still not an entire feature. If review reveals several unrelated concerns or a diff approaching thousands of lines, split and renumber its children before coding. Generated lockfiles do not justify adding unrelated implementation.

### STEP 1 — Foundation and verified application identity

**TASK**: Establish the smallest runnable app, environment contract, selected login/session flow, owned profile, and an early hosted smoke check.

**WHY**: Every later feature needs a trusted user identity and deployable request boundary; test these before domain complexity.

**DEPENDENCIES**: D1 before 1.1, D2 before 1.4, D3 before 1.5. Account access is available to the user; no setup is performed during planning.

**IMPLEMENTATION DETAILS**: Minimal Next.js shell, server environment validation, selected test harness, auth callback/session helper, profile migration/policy, protected `/api/me`, and one deployment configuration. Python branch initially adds only its health boundary, not all backend modules.

**EXPECTED OUTPUT**: Signed-in owner can view/update scheduling preferences; unauthenticated requests cannot access them; chosen runtime runs locally and on its intended host.

**ACCEPTANCE CRITERIA**: Login/logout work, timezone persists, second user cannot access first user's profile, hosted callback origin is stable, and no server secret appears in a client response.

**TESTING**: Type/build smoke, authenticated/unauthenticated route cases, profile RLS test, deployed `/api/me` check.

**COMMON FAILURE CASES**: Wrong redirect URI, trusting an unverified cookie, server key in public env, RLS blocked legitimate inserts, Python host incompatibility.

#### INCREMENT 1.1 — Minimal runnable application

- **WHAT WE BUILD**: Initialize only the selected runtime(s), package scripts, and one page saying FocusOS. No database/auth/agent folders.
- **WHY**: Establish a reviewable executable baseline before adding behavior.
- **FILES LIKELY INVOLVED**: `package.json`, lockfile, minimal framework/TypeScript config, `src/app/layout.tsx`, `src/app/page.tsx`; Python branch only its minimal API entry/config.
- **EXPECTED CHANGE SIZE**: Small, excluding generated lock metadata.
- **DEPENDENCIES**: User decision D1 and explicit instruction to start implementation.
- **EXPECTED RESULT**: Local app serves one page and a production build succeeds.
- **HOW TO VERIFY**: Run chosen dev command, open root page, run build/typecheck; record runtime versions.
- **STOP POINT**: No secrets, authentication, schema, tools, or application domain code. Stop and wait.

#### INCREMENT 1.2 — Environment boundary

- **WHAT WE BUILD**: Public/server env separation, validation of currently needed values, redacted configuration errors, `.env.example`, and secret-file ignore rules.
- **WHY**: Catch missing configuration without exposing credentials.
- **FILES LIKELY INVOLVED**: `src/server/env.ts`, `.env.example`, `.gitignore`.
- **EXPECTED CHANGE SIZE**: Tiny.
- **DEPENDENCIES**: 1.1.
- **EXPECTED RESULT**: Missing required configuration fails with names, never values.
- **HOW TO VERIFY**: Start with one missing value and one valid set; inspect tracked files and client build for secret leakage.
- **STOP POINT**: No external API connection or credential values in committed files.

#### INCREMENT 1.3 — Focused verification harness

- **WHAT WE BUILD**: Minimal chosen test runner and one meaningful environment-validation test; document commands.
- **WHY**: Later increments need cheap, reproducible focused checks.
- **FILES LIKELY INVOLVED**: test config, `tests/env.test.ts`, package scripts.
- **EXPECTED CHANGE SIZE**: Tiny.
- **DEPENDENCIES**: 1.2.
- **EXPECTED RESULT**: A test distinguishes missing/invalid configuration from valid values.
- **HOW TO VERIFY**: Run the focused test and demonstrate that an invalid fixture is rejected without printing secrets.
- **STOP POINT**: No giant testing framework or speculative fixtures.

#### INCREMENT 1.4 — One login and server session path

- **WHAT WE BUILD**: The selected login button/flow, callback, logout, and server-verified identity helper. Configure the minimum provider/project console settings needed for this flow.
- **WHY**: Downstream ownership must derive from trusted identity.
- **FILES LIKELY INVOLVED**: login page, auth callback, `src/server/auth/session.ts`; D2-C library session config.
- **EXPECTED CHANGE SIZE**: Moderate; split callback from session storage first if D2-C requires multiple independent components.
- **DEPENDENCIES**: 1.3, D2, user-provided cloud project credentials.
- **EXPECTED RESULT**: One test user signs in and out; session helper rejects invalid identity.
- **HOW TO VERIFY**: Complete real login/logout; test missing/expired session and rejected unsafe redirect.
- **STOP POINT**: No Gmail/Calendar permission grants or domain data.

#### INCREMENT 1.5 — Database access boundary

- **WHAT WE BUILD**: Selected database client, migration command, and a narrow connectivity/identity check using a restricted context.
- **WHY**: Confirm the real database and identity propagation before table design becomes code.
- **FILES LIKELY INVOLVED**: `src/server/db/client.ts`, migration config, focused DB test.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 1.4, D3; Supabase project available.
- **EXPECTED RESULT**: Server reaches the intended project without exposing elevated credentials or exhausting connections.
- **HOW TO VERIFY**: Execute a read-only health query under the selected role; test missing identity and verify role/RLS behavior.
- **STOP POINT**: No domain tables yet; only auth-library tables if selected by D2.

#### INCREMENT 1.6 — Owned profile and scheduling preferences

- **WHAT WE BUILD**: Profiles migration with ownership rules and a tiny settings form for timezone/working hours.
- **WHY**: Dates need explicit user context and ownership must be proven with the first table.
- **FILES LIKELY INVOLVED**: profile migration, `src/server/db/profiles.ts`, settings page/test.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 1.5.
- **EXPECTED RESULT**: User preferences survive reload; another user cannot read/write the profile.
- **HOW TO VERIFY**: Save valid IANA zone/hours, reject invalid ranges, run two-user policy checks.
- **STOP POINT**: No tasks, connection tokens, or scheduling logic.

#### INCREMENT 1.7 — Protected API contract

- **WHAT WE BUILD**: `GET /api/me`, safe error envelope, and a minimal signed-in shell consuming the nonsecret DTO.
- **WHY**: Prove UI-to-authenticated-backend behavior before feature routes.
- **FILES LIKELY INVOLVED**: `src/app/api/me/route.ts`, shell/session display, API test.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 1.6.
- **EXPECTED RESULT**: Verified user sees their profile; anonymous caller receives 401.
- **HOW TO VERIFY**: Request route with valid and missing sessions; assert no token fields in JSON.
- **STOP POINT**: No CRUD dashboard or integrations.

#### INCREMENT 1.8 — Early deployment probe

- **WHAT WE BUILD**: Deploy only the current small slice to the chosen free host and record stable origin/callback settings.
- **WHY**: Serverless/runtime/auth deployment failures must surface on Day 1.
- **FILES LIKELY INVOLVED**: deployment config if necessary, `.env.example`, `docs/setup.md`.
- **EXPECTED CHANGE SIZE**: Tiny.
- **DEPENDENCIES**: 1.7; D1 hosting branch and user-owned deployment account.
- **EXPECTED RESULT**: Hosted root and protected API behave like local equivalents.
- **HOW TO VERIFY**: Build and smoke-test hosted login, `/api/me`, and sign-out; confirm service plan and function limits.
- **STOP POINT**: No long-running jobs or provider integrations; do not expand scope while resolving deployment.

### STEP 2 — Google credentials and early integration probes

**TASK**: Securely connect Google, refresh credentials, and prove one Gmail and one Calendar read before full ingestion.

**WHY**: Restricted scope, consent, and provider account problems can invalidate the planned demo and must be discovered early.

**DEPENDENCIES**: Step 1; D4 before 2.1 and D13 before 2.3.

**IMPLEMENTATION DETAILS**: Private credential store, token helper, consent routes, connection status, narrow raw client reads. No normalization or sync engine here.

**EXPECTED OUTPUT**: Live authorized Gmail message and Calendar page available to the backend without credential leakage.

**ACCEPTANCE CRITERIA**: State checks pass, refresh works, granted scopes are recorded, both APIs are enabled and usable by the test account.

**TESTING**: Secret-access denial, encryption/tamper or Vault privilege check, mocked expiry/refresh, live read-only probes.

**COMMON FAILURE CASES**: Missing refresh token, testing-user omission, Workspace admin denial, redirect mismatch, wrong scopes, lost refresh token on reconnection.

#### INCREMENT 2.1 — Connection metadata and private credential storage

- **WHAT WE BUILD**: Connection/private-credential migrations and restricted repository methods; no token exchange yet.
- **WHY**: Tokens need a safe destination before OAuth is connected.
- **FILES LIKELY INVOLVED**: connection migration, `src/server/db/connections.ts`, privilege tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 1.8, D4.
- **EXPECTED RESULT**: Connection metadata is owner-scoped; credentials are inaccessible to browser roles.
- **HOW TO VERIFY**: Test A/B ownership and denied token selects/inserts under public/user roles.
- **STOP POINT**: No real tokens stored yet.

#### INCREMENT 2.2 — Token protection and refresh helper

- **WHAT WE BUILD**: Chosen encryption/Vault adapter plus expiry-aware refresh and versioned save behavior.
- **WHY**: Access tokens expire; safe persistence and refresh are part of usable integration.
- **FILES LIKELY INVOLVED**: `integrations/google/tokens.ts`, crypto/Vault helper, token tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 2.1.
- **EXPECTED RESULT**: A mocked expired access token refreshes once; absent replacement refresh token preserves the original.
- **HOW TO VERIFY**: Test valid/expired token, tamper or denied Vault access, two competing refresh requests, and `invalid_grant` reconnect state.
- **STOP POINT**: No consent callback or Gmail/Calendar requests.

#### INCREMENT 2.3 — Google consent initiation

- **WHAT WE BUILD**: Scope configuration, API/consent-screen setup instructions, and a server-generated consent start with session-bound state.
- **WHY**: Request only the selected data permissions through a traceable flow.
- **FILES LIKELY INVOLVED**: Google start route, OAuth helper, setup notes.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 2.2, D13.
- **EXPECTED RESULT**: Test user reaches the correct consent screen and redirect target.
- **HOW TO VERIFY**: Inspect scopes and callback origin; test missing session and unsafe return URL denial.
- **STOP POINT**: Returning from consent need not persist credentials until 2.4; do not run sync.

#### INCREMENT 2.4 — Secure callback and connection status

- **WHAT WE BUILD**: Validate state, exchange code server-side, securely persist credentials/grants, and show minimal connection/reconnect status.
- **WHY**: Finish account authorization without exposing Google tokens.
- **FILES LIKELY INVOLVED**: Google callback route, connection settings component, callback tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 2.3.
- **EXPECTED RESULT**: Connected account appears with actual granted capabilities; denied consent leaves a safe state.
- **HOW TO VERIFY**: Live connect; bad/reused state rejection; inspect browser responses for token absence; exercise refresh using an expired access-token fixture.
- **STOP POINT**: Connection alone does not prove Gmail/Calendar access; probes follow.

#### INCREMENT 2.5 — Fetch one selected Gmail message

- **WHAT WE BUILD**: Narrow authenticated Gmail client call that fetches one user-selected message's raw metadata/body for a server-only diagnostic.
- **WHY**: Test restricted Gmail access before building ingestion.
- **FILES LIKELY INVOLVED**: `integrations/google/gmail.ts`, a focused integration test/diagnostic command.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 2.4.
- **EXPECTED RESULT**: Actual test-account message is readable under `gmail.readonly`.
- **HOW TO VERIFY**: Read one synthetic email; record safe message ID/status; handle denied scope without dumping the body/token into logs.
- **STOP POINT**: No listing, normalization, persisted source, or LLM processing.

#### INCREMENT 2.6 — Fetch one Calendar page and verify write grant path

- **WHAT WE BUILD**: A narrow Calendar client read for a short window and verification that the chosen write scope can be granted.
- **WHY**: Discover Calendar account/scope problems before scheduling work begins.
- **FILES LIKELY INVOLVED**: `integrations/google/calendar.ts`, focused probe, setup notes.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 2.4; run after 2.5 in the risk-check sequence.
- **EXPECTED RESULT**: One live page is read; final write capability grant is confirmed or a blocker is recorded.
- **HOW TO VERIFY**: Compare a known event with provider response; test denied grant; do not create an event.
- **STOP POINT**: No complete pagination, availability calculation, or Calendar mutation.

### STEP 3 — First useful task vertical slice

**TASK**: Persist user-owned tasks, expose validated API operations, and display them in a minimal UI with a project association.

**WHY**: Establish useful deterministic application state before AI creates candidate data.

**DEPENDENCIES**: Step 1; sequence after Step 2 probes to retire risk. D7 before 3.5.

**IMPLEMENTATION DETAILS**: One tasks migration, task payload schema, GET/POST routes, small form/list, projects relation, versioned status/edit route.

**EXPECTED OUTPUT**: Manual task creation, listing, project choice, and completion work end to end.

**ACCEPTANCE CRITERIA**: Reload preserves tasks, invalid dates are rejected, and ownership holds across reads/updates/references.

**TESTING**: Payload tests, A/B integration tests, one manual browser task lifecycle.

**COMMON FAILURE CASES**: Date-only converted to UTC midnight, nullable estimate mistaken for zero, cross-owner project refs, stale edit overwrite.

#### INCREMENT 3.1 — Owned task table

- **WHAT WE BUILD**: Tasks migration with date variants, status/estimate constraints, indexes, and ownership rules.
- **WHY**: Give task data an enforceable persistent shape.
- **FILES LIKELY INVOLVED**: task migration and DB constraint/policy tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 1.6; 2.6 risk gate completed or explicitly documented fallback.
- **EXPECTED RESULT**: Valid owned task rows insert; invalid combinations and foreign-user access fail.
- **HOW TO VERIFY**: Exercise date/date-time/null variants and A/B insert/select/update policies.
- **STOP POINT**: No task API or UI yet; project/source fields arrive later.

#### INCREMENT 3.2 — Task input runtime schema

- **WHAT WE BUILD**: Task create/update DTO rules for dates, title length, enums, and optional estimates.
- **WHY**: TypeScript alone cannot validate network/model input.
- **FILES LIKELY INVOLVED**: `src/domain/task.ts`, focused schema tests.
- **EXPECTED CHANGE SIZE**: Tiny.
- **DEPENDENCIES**: 3.1.
- **EXPECTED RESULT**: Malformed inputs are rejected before persistence.
- **HOW TO VERIFY**: Boundary tests for overlong title, invalid zone/date, negative duration, unknown fields.
- **STOP POINT**: No HTTP route or AI schema.

#### INCREMENT 3.3 — Task create/list API

- **WHAT WE BUILD**: Owned GET/POST handlers and narrow task repository with replay-safe create request ID.
- **WHY**: Expose the first useful application behavior to the UI.
- **FILES LIKELY INVOLVED**: tasks route, `db/tasks.ts`, API tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 3.2, 1.7.
- **EXPECTED RESULT**: A valid POST returns one task; GET lists only the caller's tasks.
- **HOW TO VERIFY**: Auth/CSRF, payload, duplicate request, and A/B cases; inspect response DTO.
- **STOP POINT**: No UI or task updates yet.

#### INCREMENT 3.4 — Minimal task form and list

- **WHAT WE BUILD**: Plain create form, owned list, loading/empty/error states.
- **WHY**: Finish the earliest useful vertical slice.
- **FILES LIKELY INVOLVED**: task page and one form component if needed.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 3.3.
- **EXPECTED RESULT**: User creates a task, sees it, and reloads without losing it.
- **HOW TO VERIFY**: Manual create/reload/invalid-date/error flow with real test database.
- **STOP POINT**: No projects, extraction, dashboard widgets, or agent.

#### INCREMENT 3.5 — Minimal project association

- **WHAT WE BUILD**: Projects migration/repository, basic create/list route and task project selector; same-owner relation enforced.
- **WHY**: Later extraction must resolve context against real user projects.
- **FILES LIKELY INVOLVED**: project migration/domain/repository, project route, existing task form.
- **EXPECTED CHANGE SIZE**: Moderate; D7-B requires a separate follow-on relation increment before implementation.
- **DEPENDENCIES**: 3.4, D7.
- **EXPECTED RESULT**: A task can link to an existing owned project; ambiguous names remain unresolved.
- **HOW TO VERIFY**: Create one project, attach task, reject foreign-user project ID and duplicate normalized name.
- **STOP POINT**: No automatic project creation or general graph UI.

#### INCREMENT 3.6 — Versioned task edits and Today list

- **WHAT WE BUILD**: PATCH for completion and existing editable fields with expected version; Today list sorts by status/deadline.
- **WHY**: User corrections must remain authoritative before extraction enters the app.
- **FILES LIKELY INVOLVED**: task-ID route, task repository/schema, existing task page.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 3.5.
- **EXPECTED RESULT**: Completion and a date correction persist; stale edits return 409.
- **HOW TO VERIFY**: Edit in two tabs, verify conflict; check date-only ordering and owner isolation.
- **STOP POINT**: Today has tasks only; no Calendar or AI attention items.

### STEP 4 — Source-backed structured extraction

**TASK**: Turn one pasted synthetic email into validated candidate tasks/events, review it, and save an accepted task with provenance.

**WHY**: Isolate model reliability from Gmail synchronization complexity and establish evidence before automation.

**DEPENDENCIES**: Step 3; D5 before 4.1 and D12 generation choice before 4.3.

**IMPLEMENTATION DETAILS**: Source table/manual source route, extraction contracts, one provider call, run logging, extraction result storage, atomic confirmation, compact review UI.

**EXPECTED OUTPUT**: Pasted text -> source -> candidate -> reviewed task -> existing Today list.

**ACCEPTANCE CRITERIA**: Evidence matches source, ambiguous date is flagged, invalid model output creates no actionable task, repeat confirmation yields one task.

**TESTING**: Frozen-time date fixtures, malformed output/refusal/timeout, evidence mismatch, confirmation replay, one real model call on synthetic data.

**COMMON FAILURE CASES**: Invented cutoff time, confidence used as approval, unknown project ID, response parsing failure, duplicate task on retry.

#### INCREMENT 4.1 — Manual source and provenance

- **WHAT WE BUILD**: Source table/repository and bounded manual-source route with source reference, timestamp, normalized text/hash, and D5 retention behavior.
- **WHY**: AI facts need an immutable extraction input and traceable origin.
- **FILES LIKELY INVOLVED**: source migration, `domain/source.ts`, manual source route/repository.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 3.6, D5.
- **EXPECTED RESULT**: One synthetic email is stored/referenced according to retention policy.
- **HOW TO VERIFY**: Submit same replay key twice, enforce size limit and owner access, verify exact text/hash.
- **STOP POINT**: No model calls or Gmail ingestion.

#### INCREMENT 4.2 — Extraction contracts and date fixtures

- **WHAT WE BUILD**: Task/event candidate and envelope schemas plus six synthetic development fixtures covering explicit, relative, date-only, and ambiguous deadlines.
- **WHY**: Define correctness before calling the model.
- **FILES LIKELY INVOLVED**: `domain/extraction.ts`, extraction fixture/test files.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 4.1.
- **EXPECTED RESULT**: Well-formed candidates pass; fabricated schema fields, invalid dates, and absent evidence fail validation.
- **HOW TO VERIFY**: Run fixture validators with fixed reference time/zone, including the Thursday-before-Friday example.
- **STOP POINT**: Schema validity alone is not factual validity; no model or task writes.

#### INCREMENT 4.3 — One structured extraction call

- **WHAT WE BUILD**: Minimal chosen LLM adapter and extraction prompt with untrusted-source delimiters, bounded input/output, one repair, and deterministic evidence/date validation.
- **WHY**: Prove the available model can produce grounded structured candidates.
- **FILES LIKELY INVOLVED**: `ai/provider.ts`, `ai/extract.ts`, focused model-response tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 4.2, D12 generation choice.
- **EXPECTED RESULT**: Synthetic source returns validated candidates or a typed failure/clarification.
- **HOW TO VERIFY**: Run one real synthetic call; replay malformed JSON, refusal, unsupported quote, injected instruction, and timeout mocks.
- **STOP POINT**: No candidate persistence or automated task creation.

#### INCREMENT 4.4 — First agent-run log

- **WHAT WE BUILD**: Agent runs table and one wrapper recording extraction start/outcome, versions, latency, and available usage.
- **WHY**: Observe real model behavior before adding more calls.
- **FILES LIKELY INVOLVED**: run migration, `observability/runs.ts`, extraction wrapper/test.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 4.3.
- **EXPECTED RESULT**: Successful and failed extraction each leave a redacted run record.
- **HOW TO VERIFY**: Inspect both paths; assert token/authorization secrets and raw prompts are absent.
- **STOP POINT**: No tool ledger or debugging dashboard.

#### INCREMENT 4.5 — Persist extraction review results

- **WHAT WE BUILD**: Extraction results table, bounded extract route, deduplicated claim/processing state, rate limit, and status response.
- **WHY**: Model results must survive refresh and avoid duplicate provider work.
- **FILES LIKELY INVOLVED**: extraction migration/repository, source extract route.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 4.4.
- **EXPECTED RESULT**: One source/version has one saved candidate result; failed claims are retryable after lease expiry.
- **HOW TO VERIFY**: Repeated/concurrent requests, rejected unowned source, timeout recovery, completed-result replay.
- **STOP POINT**: Candidate data is not yet an accepted task.

#### INCREMENT 4.6 — Confirm candidate into a task

- **WHAT WE BUILD**: Task provenance extension and atomic confirmation endpoint resolving owned project/source references, reviewed dates, and stable candidate identity.
- **WHY**: Preserve user control and link actionable state back to evidence.
- **FILES LIKELY INVOLVED**: task provenance migration, confirmation route/service, tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 4.5.
- **EXPECTED RESULT**: Confirmed candidate creates one task with evidence and reviewed fields.
- **HOW TO VERIFY**: Confirm twice/concurrently; reject foreign IDs, invalid date arithmetic, and stale changed extraction.
- **STOP POINT**: No automatic overwrite of existing tasks or Calendar event creation.

#### INCREMENT 4.7 — Extraction review UI

- **WHAT WE BUILD**: Pasted-source entry and candidate review showing evidence, uncertainties, corrections, and confirm/ignore controls.
- **WHY**: Complete an understandable AI vertical slice.
- **FILES LIKELY INVOLVED**: activity page and focused review component.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 4.6.
- **EXPECTED RESULT**: Confirmed task appears in existing Today list with its source.
- **HOW TO VERIFY**: Walk explicit and ambiguous deadline fixtures; correct date, confirm, reload, follow source reference.
- **STOP POINT**: No Gmail sync or scheduling agent.

### STEP 5 — Bounded, resumable Gmail ingestion

**TASK**: Fetch selected Gmail IDs, normalize messages, persist deduplicated sources, and expose resumable incremental sync and extraction queue status.

**WHY**: Replace manual source input with a real integration without conflating retrieval and AI processing.

**DEPENDENCIES**: Steps 2 and 4; D9 before 5.7.

**IMPLEMENTATION DETAILS**: Metadata-first listing, bounded body fetch, pure MIME normalizer, source upsert, extraction handoff, history cursor/lease, manual dashboard trigger.

**EXPECTED OUTPUT**: Selected new messages become reviewable source-backed candidates; repeats and request interruptions are safe.

**ACCEPTANCE CRITERIA**: One live selected message reaches review, an irrelevant message is ignored, replay creates no duplicate, expired history triggers bounded rescan.

**TESTING**: Mock pagination/history/404/429/crash cases, MIME fixtures, live sync twice, concurrent tabs.

**COMMON FAILURE CASES**: Missing pages, advancing cursor before persistence, treating unread as new, reprocessing quoted history, attachment assumptions.

#### INCREMENT 5.1 — Selected message IDs and metadata

- **WHAT WE BUILD**: Bounded Gmail list/metadata operation with explicit query/label selection and page response.
- **WHY**: Inspect relevance before fetching bodies or spending model tokens.
- **FILES LIKELY INVOLVED**: Gmail client extension and pagination tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 2.5, 4.7.
- **EXPECTED RESULT**: Up to ten selected IDs/headers and continuation token are returned.
- **HOW TO VERIFY**: Live dedicated-label listing and mocked multiple pages/empty selection; no body for excluded IDs.
- **STOP POINT**: No persistence or sync cursor.

#### INCREMENT 5.2 — Bounded selected-body fetching

- **WHAT WE BUILD**: Fetch full payloads only for selected IDs, with size/count limits and safe provider error mapping.
- **WHY**: Keep mailbox access deliberately narrow.
- **FILES LIKELY INVOLVED**: Gmail client fetch helper and response fixtures.
- **EXPECTED CHANGE SIZE**: Tiny.
- **DEPENDENCIES**: 5.1.
- **EXPECTED RESULT**: A small selected set returns raw MIME payloads; deleted messages are marked unavailable.
- **HOW TO VERIFY**: Fetch one synthetic message, reject arbitrary unselected input and oversized requests, mock missing message.
- **STOP POINT**: Raw MIME is not yet normalized or submitted to an LLM.

#### INCREMENT 5.3 — Pure Gmail normalization

- **WHAT WE BUILD**: MIME/base64url/charset-to-text conversion, HTML stripping, source timestamp/thread metadata, truncation and attachment indicators.
- **WHY**: Extraction needs predictable text and accurate provenance.
- **FILES LIKELY INVOLVED**: `ingestion/normalize-gmail.ts`, MIME fixture tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 5.2.
- **EXPECTED RESULT**: Plain/HTML/multipart messages yield consistent bounded source DTOs.
- **HOW TO VERIFY**: Test Unicode, empty body, nested MIME, HTML injection, long body, quoted reply, attachment-only message.
- **STOP POINT**: No database writes or attachment downloads.

#### INCREMENT 5.4 — Idempotent Gmail source upsert

- **WHAT WE BUILD**: Gmail-specific source metadata/unique constraint and normalization-version/content-hash upsert.
- **WHY**: Re-fetches must not create duplicate source records.
- **FILES LIKELY INVOLVED**: source extension migration, source repository, dedup tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 5.3, 4.1.
- **EXPECTED RESULT**: Same provider message maps to one source; changed content is explicitly versioned for reprocessing.
- **HOW TO VERIFY**: Upsert twice/concurrently; same body in two different provider messages remains two sources.
- **STOP POINT**: No durable Gmail history cursor or automatic AI processing.

#### INCREMENT 5.5 — One pending Gmail extraction handoff

- **WHAT WE BUILD**: Claim one eligible persisted source and invoke the existing extraction path, preserving distinct ingest/process status.
- **WHY**: Connect integration data to the proven AI slice without a new extraction system.
- **FILES LIKELY INVOLVED**: `ingestion/process-source.ts`, existing extraction service, queue-state tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 5.4, 4.5.
- **EXPECTED RESULT**: One selected Gmail source reaches review; nonactionable content can be ignored.
- **HOW TO VERIFY**: Live synthetic email -> existing review UI; replay and crashed-claim recovery; no duplicate task.
- **STOP POINT**: No continuously running worker or full-mailbox processing.

#### INCREMENT 5.6 — Durable incremental synchronization

- **WHAT WE BUILD**: sync_state migration, bounded initial/history page handling, per-connection lease, checkpoint commits, 404 rescan and 429 retry timestamps.
- **WHY**: New mail must be discoverable without repeated full scans or missed cursor changes.
- **FILES LIKELY INVOLVED**: sync migration, `ingestion/gmail-sync.ts`, state-machine tests.
- **EXPECTED CHANGE SIZE**: Moderate; if initial and history paths exceed a cohesive diff, split into 5.6a initial checkpoint and 5.6b history recovery before coding.
- **DEPENDENCIES**: 5.5.
- **EXPECTED RESULT**: One request processes one bounded page and safely resumes after interruption.
- **HOW TO VERIFY**: Simulate crash before/after cursor commit, multi-page delta, duplicate history entry, expired cursor, overlapping calls, and cap reached.
- **STOP POINT**: No scheduled trigger; a partial run is visibly partial, not complete.

#### INCREMENT 5.7 — Sync controls and selected trigger

- **WHAT WE BUILD**: Authenticated Sync Now/status route and small activity/settings controls; if D9-B, a separately authenticated daily trigger invoking the same service.
- **WHY**: User needs a visible way to start, resume, and diagnose bounded work.
- **FILES LIKELY INVOLVED**: sync routes, activity/settings UI; optional cron config/route.
- **EXPECTED CHANGE SIZE**: Small; split the optional scheduled trigger into its own increment if selected.
- **DEPENDENCIES**: 5.6, D9.
- **EXPECTED RESULT**: Sync resumes through bounded requests; last-success/error/reconnect state is visible.
- **HOW TO VERIFY**: Sync twice, close/reopen mid-run, inspect one new synthetic message; if cron selected, deny unauthorized invocation.
- **STOP POINT**: No push notifications, near-real-time guarantee, or attachment ingestion.

### STEP 6 — Calendar normalization and deterministic availability

**TASK**: Convert real Calendar responses into complete, trustworthy intervals and compute valid work slots.

**WHY**: Planning must operate on deterministic availability before the model can propose external writes.

**DEPENDENCIES**: 2.6, profile preferences from 1.6, task slice from Step 3. Sequenced after Gmail for a coherent source-to-task demo.

**IMPLEMENTATION DETAILS**: Calendar domain DTO, bounded paginated read service, pure normalizer, interval subtraction, Today schedule list.

**EXPECTED OUTPUT**: A complete Calendar window and verified free slots, or a clear incomplete/unavailable response.

**ACCEPTANCE CRITERIA**: Known busy times are excluded, all-day and recurring events behave correctly, date/timezone limits hold, partial provider results never imply availability.

**TESTING**: DST/all-day/recurrence fixtures, pagination/error tests, interval invariants and one live Calendar comparison.

**COMMON FAILURE CASES**: Exclusive all-day end misread, only first page fetched, wrong zone, transparent/cancelled events block time, provider failure becomes “free all day.”

#### INCREMENT 6.1 — Calendar event domain contract

- **WHAT WE BUILD**: Normalized timed/all-day event schema with provider identity, busy status, recurrence reference, and observed time.
- **WHY**: Separate provider payload quirks from scheduling input.
- **FILES LIKELY INVOLVED**: `domain/calendar.ts`, schema fixtures/tests.
- **EXPECTED CHANGE SIZE**: Tiny.
- **DEPENDENCIES**: 2.6; Step 5 complete in the planned sequence.
- **EXPECTED RESULT**: Timed and date-only provider concepts have distinct validated shapes.
- **HOW TO VERIFY**: Test valid/invalid date variants and missing offsets/timezones.
- **STOP POINT**: No fetching or free-time algorithm change.

#### INCREMENT 6.2 — Complete bounded event fetching

- **WHAT WE BUILD**: Read-only Calendar service/route following pagination for a <=14-day window with recurrence expansion and explicit completeness.
- **WHY**: Missing a page could produce unsafe proposed availability.
- **FILES LIKELY INVOLVED**: Calendar client extension, read route/service, pagination tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 6.1, 2.6.
- **EXPECTED RESULT**: All pages are collected, or response declares incomplete/error without usable free slots.
- **HOW TO VERIFY**: Mock two pages and a failed second page; compare one live window with Google Calendar.
- **STOP POINT**: No interval normalization or event creation.

#### INCREMENT 6.3 — Calendar time normalization

- **WHAT WE BUILD**: Pure timed/all-day/recurring occurrence normalization, timezone conversion, and busy filtering.
- **WHY**: Establish trustworthy intervals for deterministic scheduling.
- **FILES LIKELY INVOLVED**: `scheduling/normalize-events.ts`, timezone fixtures/tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 6.2.
- **EXPECTED RESULT**: Provider events map to correct UTC busy intervals while preserving local-date provenance.
- **HOW TO VERIFY**: All-day exclusive end, recurrence exception, cancelled/transparent event, declined invite, cross-midnight and DST transition cases.
- **STOP POINT**: No free-slot selection or agent tools.

#### INCREMENT 6.4 — Pure free-time calculation

- **WHAT WE BUILD**: Merge/clip/subtract interval functions and contiguous/split slot selection with work-hour and confirmed deadline bounds.
- **WHY**: An LLM is unnecessary and less reliable for interval arithmetic.
- **FILES LIKELY INVOLVED**: `scheduling/free-time.ts`, interval tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 6.3, 1.6, 3.2.
- **EXPECTED RESULT**: Returns deterministic valid slots totaling requested time or a measured shortfall.
- **HOW TO VERIFY**: Test touching/overlapping intervals, full day busy, no events, date-only deadline clarification, split policy, DST and incomplete-calendar rejection.
- **STOP POINT**: No model-selected slots, approval, or writes.

#### INCREMENT 6.5 — Today schedule and availability preview

- **WHAT WE BUILD**: Simple schedule list and duration input showing computed free-time results with timezone, selected calendar and fetched-at time.
- **WHY**: Make deterministic behavior visible before adding agent mediation.
- **FILES LIKELY INVOLVED**: existing Today page, small availability route/component.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 6.4.
- **EXPECTED RESULT**: User can compare real busy events and candidate free slots.
- **HOW TO VERIFY**: Use a known busy test calendar; request more time than available and check shortfall; force provider error.
- **STOP POINT**: Preview only; no event is proposed to an approval queue or created.

### STEP 7 — Incremental read/planning agent and selected memory

**TASK**: Introduce typed tools progressively, bounded orchestration, selective memory retrieval, and validated planning responses.

**WHY**: The application now has reliable services for the agent to use instead of inventing state.

**DEPENDENCIES**: Steps 3–6; D6/D11 before 7.1; D8 and embedding portion of D12 before 7.5.

**IMPLEMENTATION DETAILS**: Tool-call schema/ledger, first tasks tool, read Calendar wrappers, bounded run state, small memories table and vectors, SQL+semantic search, planning contract/service, command/run UI.

**EXPECTED OUTPUT**: User command leads to observable read tools and a valid source-grounded proposed schedule. No external writes yet.

**ACCEPTANCE CRITERIA**: Unknown tools/IDs are rejected, iteration caps persist across requests, one relevant memory is retrieved, and proposed blocks belong to deterministic valid slots.

**TESTING**: Tool dispatch and budget fixtures, ownership filters, fake model tool requests, live model read-only run, retrieval relevance fixture, invalid plan rejection.

**COMMON FAILURE CASES**: Model invents resource IDs, tool loop repeats forever, context exceeds size cap, stale vector used, model final answer claims an unexecuted action.

#### INCREMENT 7.1 — Typed tool request and execution ledger

- **WHAT WE BUILD**: Minimal registry shape, AgentToolRequest validation, tool_calls migration and redacted lifecycle logging. Resolve run/conversation branch without implementing all tools.
- **WHY**: Define the model-to-application boundary before execution is possible.
- **FILES LIKELY INVOLVED**: `tools/registry.ts`, `domain/tool-request.ts`, tool-call migration/log helper.
- **EXPECTED CHANGE SIZE**: Small; D11-B chat persistence must be split into its own increment.
- **DEPENDENCIES**: 6.5, 4.4, D6, D11.
- **EXPECTED RESULT**: A fake unknown tool request is rejected and recorded without executing anything.
- **HOW TO VERIFY**: Tool-name/argument rejection, server-owned user/risk fields, safe error/log payloads.
- **STOP POINT**: Empty/limited registry only; no general agent loop or write tool.

#### INCREMENT 7.2 — One read-only tasks tool round trip

- **WHAT WE BUILD**: `tasks.list` handler and one model request -> validated tool -> result -> final response round trip.
- **WHY**: Demonstrate tool calling with the smallest useful service.
- **FILES LIKELY INVOLVED**: `tools/tasks-list.ts`, `agent/single-turn.ts`, round-trip tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 7.1, 3.3.
- **EXPECTED RESULT**: “What tasks are due?” returns owned stored tasks with source refs and a tool log.
- **HOW TO VERIFY**: Mock model selecting tasks.list; live synthetic command; reject cross-user project and invented task facts.
- **STOP POINT**: Exactly one read round trip; no iterative Calendar planning.

#### INCREMENT 7.3 — Bounded multiple-read continuation

- **WHAT WE BUILD**: Thin `calendar.get_events`/`calendar.find_free_time` tool bindings to existing services and persisted bounded continuation for the selected orchestration branch.
- **WHY**: Scheduling needs more than one read and must survive a serverless request boundary.
- **FILES LIKELY INVOLVED**: Calendar tool wrappers, `agent/run.ts`, checkpoint/budget tests.
- **EXPECTED CHANGE SIZE**: Moderate; split wrappers and continuation into 7.3a/7.3b if the combined diff stops being cohesive.
- **DEPENDENCIES**: 7.2, 6.4.
- **EXPECTED RESULT**: Agent can inspect tasks and Calendar, then stop/clarify or yield a checkpoint under fixed limits.
- **HOW TO VERIFY**: Test multiple read requests, repeated identical calls, timeout continuation, budget persistence, disabled write request, partial Calendar result.
- **STOP POINT**: No semantic memory, scheduling proposal schema, or external effects.

#### INCREMENT 7.4 — Small confirmed memory store

- **WHAT WE BUILD**: Memories table with owned source/project refs and a compact confirm/list action for selected extracted facts or user preferences.
- **WHY**: Demonstrate long-term context beyond replaying chat history.
- **FILES LIKELY INVOLVED**: memory migration/repository, compact activity/project memory component.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 7.3, 3.5, 4.6.
- **EXPECTED RESULT**: A confirmed project fact survives a new run and retains evidence.
- **HOW TO VERIFY**: Save/reload two facts; reject foreign refs and invalid quote; mark an outdated fact superseded.
- **STOP POINT**: SQL memory only; no embeddings yet.

#### INCREMENT 7.5 — Selective embeddings

- **WHAT WE BUILD**: pgvector fields/extension, selected embedding adapter, model/dimension/content-hash tracking, and D8's bounded embedding trigger.
- **WHY**: Add semantic representation only to useful confirmed content.
- **FILES LIKELY INVOLVED**: vector migration, `memory/embed.ts`, adapter/tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 7.4, D8, confirmed embedding provider/model/dimension in D12.
- **EXPECTED RESULT**: One small memory has a valid vector; failed embedding remains retryable without losing text.
- **HOW TO VERIFY**: Embed one synthetic memory; reject dimension mismatch; reuse unchanged hash; recover provider failure.
- **STOP POINT**: No mailbox-wide embedding, vector index tuning, or reranker.

#### INCREMENT 7.6 — Filtered memory search tool

- **WHAT WE BUILD**: Owner/project-filtered vector retrieval plus exact SQL name matches, bounded result merge, and `memory.search` binding.
- **WHY**: Ground agent planning in relevant durable context without putting the whole database in the prompt.
- **FILES LIKELY INVOLVED**: memory search query/RPC, `tools/memory-search.ts`, relevance/isolation tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 7.5, 7.1.
- **EXPECTED RESULT**: A paraphrased query retrieves a relevant confirmed fact with source evidence.
- **HOW TO VERIFY**: Relevant/irrelevant fixture ranking, cross-user denial, superseded/deleted-source exclusion, visibly marked lexical fallback.
- **STOP POINT**: No generic memory framework or automatic conversation summarization.

#### INCREMENT 7.7 — Planning response contract

- **WHAT WE BUILD**: PlanningResponse runtime schema and deterministic validator for known task/slot refs, total time, deadline, overlap and assumptions.
- **WHY**: Well-formed prose is insufficient proof of a feasible plan.
- **FILES LIKELY INVOLVED**: `domain/plan.ts`, `scheduling/validate-plan.ts`, tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 7.6, 6.4.
- **EXPECTED RESULT**: Invalid or invented slot selections cannot become actionable proposals.
- **HOW TO VERIFY**: Reject unknown handle, overlap, changed duration, wrong total, after-deadline block; accept valid shortfall/clarification.
- **STOP POINT**: No model planning call wired to approval.

#### INCREMENT 7.8 — Grounded planning stage

- **WHAT WE BUILD**: Compose task/Calendar/memory context, ask model to select among valid slots, validate response and produce a proposed plan or clarification.
- **WHY**: Complete the reasoning-to-deterministic-plan path.
- **FILES LIKELY INVOLVED**: `agent/plan.ts`, bounded orchestrator update, planning fixtures.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 7.7.
- **EXPECTED RESULT**: “Find three hours this week” yields valid blocks or an honest shortfall/clarification.
- **HOW TO VERIFY**: Live synthetic command with fixed test calendar; missing estimate, ambiguous due time, insufficient capacity, injected source instructions.
- **STOP POINT**: A proposal is not approval and creates no Google event.

#### INCREMENT 7.9 — Command and run inspection UI

- **WHAT WE BUILD**: Minimal command input, run status/continuation view, grounded plan display, and basic tool trace on a shared run-details surface.
- **WHY**: Make agent behavior demonstrable and reviewable.
- **FILES LIKELY INVOLVED**: agent page/run-detail page, authenticated run endpoints.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 7.8.
- **EXPECTED RESULT**: User can issue command, inspect retrieved counts/tools, and reload run state.
- **HOW TO VERIFY**: Run valid/clarifying/failing commands; reload mid-run; ensure another user cannot load run ID.
- **STOP POINT**: No approve button or external write capability yet.

### STEP 8 — Exact approval and replay-safe Calendar creation

**TASK**: Convert a validated proposal into a persistent approval and execute only the approved event through audited backend code.

**WHY**: This is the central agent engineering demonstration and the highest-impact MVP boundary.

**DEPENDENCIES**: Step 7; D10 before 8.1; write scope verified in 2.6.

**IMPLEMENTATION DETAILS**: Approval table/state machine, proposal tool, decision endpoint/UI, freshness checks, idempotent provider insert/reconcile, execution claim, truthful result/audit view.

**EXPECTED OUTPUT**: Source-backed task -> agent proposal -> user approval -> one actual Google event -> inspectable result.

**ACCEPTANCE CRITERIA**: No event before approval; duplicate clicks yield one event; stale/conflicting/rejected action cannot write; unknown outcome is reconciled.

**TESTING**: Policy and race tests, payload tampering, crash/timeout reconciliation, one real explicitly approved event in the chosen test calendar.

**COMMON FAILURE CASES**: Approval bound only to a name not a payload, altered args after approval, duplicate provider insert, expired lease mistaken for failure, success text before provider proof.

#### INCREMENT 8.1 — Immutable approval storage

- **WHAT WE BUILD**: Approval migration/state rules, canonical payload hash, expiry and owned immutable request persistence.
- **WHY**: Approval must survive reload and bind to the exact proposed action.
- **FILES LIKELY INVOLVED**: approval migration, `approvals/payload.ts`, state tests.
- **EXPECTED CHANGE SIZE**: Small; D10-B parent batching requires its own follow-on increment.
- **DEPENDENCIES**: 7.9, D10.
- **EXPECTED RESULT**: Pending action cannot be edited into another approved payload.
- **HOW TO VERIFY**: Hash stability, payload modification rejection, ownership, expiry, and legal transitions.
- **STOP POINT**: No decision endpoint, model write binding, or provider mutation.

#### INCREMENT 8.2 — Calendar creation proposal tool

- **WHAT WE BUILD**: `calendar.create_event` registry entry whose initial dispatch resolves known slot/task handles and stores a pending approval, then pauses the run.
- **WHY**: Separate the model's requested action from actual execution.
- **FILES LIKELY INVOLVED**: `tools/calendar-create-event.ts`, permission policy, orchestrator pause test.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 8.1, 7.7.
- **EXPECTED RESULT**: A valid tool request produces approval ID and no Calendar API write.
- **HOW TO VERIFY**: Spy provider client to prove zero writes; reject unknown slot, guests, wrong calendar, and model-supplied approved flag.
- **STOP POINT**: Proposal only; no human decision handling.

#### INCREMENT 8.3 — Human approve/reject flow

- **WHAT WE BUILD**: Owned approval list/decision endpoint and exact-action review card with atomic approve/reject semantics.
- **WHY**: Human consent must be explicit and reviewable.
- **FILES LIKELY INVOLVED**: approval routes, approval card/page, decision tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 8.2.
- **EXPECTED RESULT**: User can approve/reject exact stored action; rejection/expiry survives reload.
- **HOW TO VERIFY**: Inspect timezone/calendar/source preview; reject then replay; concurrent decisions; altered body and foreign-user access.
- **STOP POINT**: Approved status alone does not trigger a provider write yet.

#### INCREMENT 8.4 — Pre-execution authorization and freshness

- **WHAT WE BUILD**: Preflight checks for approval hash/version/expiry, current task/connection/grant, complete fresh Calendar read, and free slot.
- **WHY**: Circumstances can change after the user reviews a proposal.
- **FILES LIKELY INVOLVED**: `approvals/preflight.ts`, policy/freshness tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 8.3, 6.4.
- **EXPECTED RESULT**: Stale/conflicting actions require a fresh proposal and approval.
- **HOW TO VERIFY**: Add busy event after proposal, change task deadline, revoke scope, expire approval; all block execution.
- **STOP POINT**: No Calendar insert handler is wired.

#### INCREMENT 8.5 — Idempotent Calendar insert adapter

- **WHAT WE BUILD**: Server-only provider insert/get-by-stable-ID adapter with action marker and timeout/duplicate reconciliation, tested through mocks.
- **WHY**: A retried external call must not silently create duplicate focus blocks.
- **FILES LIKELY INVOLVED**: Calendar write adapter, response/reconciliation tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 8.4.
- **EXPECTED RESULT**: Simulated lost response resolves to the same provider event; mismatched marker is an error.
- **HOW TO VERIFY**: Timeout-before-write, timeout-after-write, 409 with matching/mismatching event, forbidden payload fields, 429 retry timing.
- **STOP POINT**: Adapter is not exposed to the UI or autonomous agent for direct execution.

#### INCREMENT 8.6 — Claim and execute one approved action

- **WHAT WE BUILD**: Authenticated execution endpoint that atomically claims action, runs preflight, uses stored payload/stable ID, and persists outcome with reconciliation after crashes.
- **WHY**: Join approval and provider execution through one enforceable boundary.
- **FILES LIKELY INVOLVED**: `approvals/execute.ts`, execution route, concurrency tests.
- **EXPECTED CHANGE SIZE**: Moderate, focused on this single state transition boundary.
- **DEPENDENCIES**: 8.5.
- **EXPECTED RESULT**: One approved action creates one real event; duplicate requests return the same status/result.
- **HOW TO VERIFY**: Mock double-click/race/crash recovery, then approve one synthetic event in the test calendar and compare exact provider fields/link.
- **STOP POINT**: No automatic rollback, reschedule, delete, guest invitations, or send-email capability.

#### INCREMENT 8.7 — Truthful action result and audit view

- **WHAT WE BUILD**: Resume/finalize run from persisted tool result and show approval/creation/unknown/conflict status plus external event link in run UI.
- **WHY**: The user and portfolio reviewer must distinguish proposed action from completed action.
- **FILES LIKELY INVOLVED**: run finalization service, existing run/approval views.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 8.6.
- **EXPECTED RESULT**: Full workflow is demonstrable with source, human decision, provider outcome and telemetry.
- **HOW TO VERIFY**: End-to-end Gmail -> task -> command -> approve -> event -> audit; repeat execute; simulate unknown outcome and confirm no false success.
- **STOP POINT**: Feature scope freezes; evaluate and harden instead of adding tools/screens.

### STEP 9 — Evaluation, recovery checks, and portfolio release

**TASK**: Produce measurable evaluation evidence, exercise safety/recovery behavior, finish retention/disconnect controls, and verify the deployed demonstration.

**WHY**: A portfolio agent needs evidence of correctness and known limitations, not just a happy-path recording.

**DEPENDENCIES**: Core slice complete through 8.7. Dataset authoring can begin independently after 4.2 if time opens.

**IMPLEMENTATION DETAILS**: Synthetic JSONL, opt-in live extraction runner, deterministic/rubric scoring, focused adversarial regressions, account/data controls, release checklist and demo notes.

**EXPECTED OUTPUT**: Repeatable test/eval report and working local/hosted demo with limitations documented.

**ACCEPTANCE CRITERIA**: Zero unapproved or cross-user effects in tests, extraction metrics honestly reported, reconnect works, release build succeeds, actual Calendar write verified.

**TESTING**: Focused tests first, then one full release suite/build and critical browser smoke; live provider test is separate and uses explicit approval.

**COMMON FAILURE CASES**: Tuning on test set, mixing mocked/live success metrics, leaking mail in fixture/report, final-day refresh-token expiry, hosted callback drift.

#### INCREMENT 9.1 — Labeled held-out evaluation cases

- **WHAT WE BUILD**: 24 complete synthetic cases with reference clock/zone, expected facts/evidence/tools, permitted semantic variants and forbidden actions.
- **WHY**: Evaluation needs reproducible expected outcomes independent of model output.
- **FILES LIKELY INVOLVED**: `evals/cases.jsonl`, dataset schema/readme.
- **EXPECTED CHANGE SIZE**: Small, data-focused.
- **DEPENDENCIES**: 4.2; scheduled after 8.7 unless moved earlier without interrupting an active increment.
- **EXPECTED RESULT**: Cases parse and cover extraction, ambiguity, planning, policy and injection.
- **HOW TO VERIFY**: Validate every row; manually review labels and date arithmetic; check no development-case leakage/private content.
- **STOP POINT**: No claimed model score yet.

#### INCREMENT 9.2 — Extraction evaluation runner

- **WHAT WE BUILD**: Opt-in runner invoking the real extraction service for labeled cases with fixed context and redacted per-case output.
- **WHY**: Measure the actual model integration through the same code path as the app.
- **FILES LIKELY INVOLVED**: `evals/run.ts` or Python equivalent, run script/config.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 9.1, 4.3.
- **EXPECTED RESULT**: Each extraction case produces model/schema versions, output/failure, latency and usage.
- **HOW TO VERIFY**: Dry-run fixture mode, then explicit live synthetic run; verify no Google writes and bounded retries.
- **STOP POINT**: Raw observations only; aggregate scoring follows.

#### INCREMENT 9.3 — Field scoring and aggregate report

- **WHAT WE BUILD**: Exact date/ref/schema scoring, one-to-one task matching with recorded human rubric judgments, aggregate counts/metrics, and a static report.
- **WHY**: Convert observations into honest, inspectable quality evidence.
- **FILES LIKELY INVOLVED**: `evals/score.ts`, report template/generated report, scorer tests.
- **EXPECTED CHANGE SIZE**: Small.
- **DEPENDENCIES**: 9.2.
- **EXPECTED RESULT**: Report shows numerator/denominator, failure examples, versions and limitations.
- **HOW TO VERIFY**: Hand-score a few fixtures and compare; ensure missing/invalid outputs count as failures rather than being omitted.
- **STOP POINT**: No elaborate evaluation dashboard or unsupported performance claims.

#### INCREMENT 9.4 — Agent safety and recovery regression gates

- **WHAT WE BUILD**: Targeted provider-mocked cases for injection, cross-user refs, loop budget, unapproved/stale writes, duplicate execution and lost-response recovery.
- **WHY**: Safety invariants must hold independently of average extraction quality.
- **FILES LIKELY INVOLVED**: focused agent/approval integration tests and release gate script.
- **EXPECTED CHANGE SIZE**: Small, tests focused on existing boundaries.
- **DEPENDENCIES**: 9.3, 8.6.
- **EXPECTED RESULT**: Unsafe proposed calls are blocked and all failure states are observable.
- **HOW TO VERIFY**: Run the named adversarial fixtures; assert zero provider calls on denied actions and one stable result on replay.
- **STOP POINT**: Fix discovered issues in separate small increments; do not begin stretch features.

#### INCREMENT 9.5 — Disconnect, retention and data removal

- **WHAT WE BUILD**: Disconnect/reconnect and explicit imported-data removal controls, plus bounded retention cleanup using selected trigger strategy.
- **WHY**: A personal-data demo needs usable revocation and deletion, including derived records.
- **FILES LIKELY INVOLVED**: connection delete/reconnect route, cleanup service, settings controls/tests.
- **EXPECTED CHANGE SIZE**: Moderate; split disconnect and retention if the diff contains independent large logic.
- **DEPENDENCIES**: 9.4, token helper, source/memory/audit stores.
- **EXPECTED RESULT**: Disconnect blocks sync/pending writes; deleting imported data removes text/embeddings/private copies without deleting Google events.
- **HOW TO VERIFY**: Disconnect, attempt sync/execute, reconnect; remove synthetic source data and inspect derived stores/log redaction.
- **STOP POINT**: No generalized account administration or compliance dashboard.

#### INCREMENT 9.6 — Release verification and demo documentation

- **WHAT WE BUILD**: Final environment/deployment checks, minimal CI build/test job, one critical browser smoke, setup/demo notes, known limitations and eval-report link.
- **WHY**: Make the portfolio reproducible by someone who did not watch development.
- **FILES LIKELY INVOLVED**: CI workflow, critical smoke test, `README.md`, `docs/demo.md`, deployment config only if needed.
- **EXPECTED CHANGE SIZE**: Small; split release fixes into focused follow-ups if failures arise.
- **DEPENDENCIES**: 9.5 and all critical acceptance gates.
- **EXPECTED RESULT**: Reproducible local run and verified chosen hosted demonstration, or clearly labeled local-only fallback with cause.
- **HOW TO VERIFY**: Run lint/typecheck/tests/build, synthetic eval, hosted auth/read checks and one user-approved real Calendar creation; inspect logs and report limitations.
- **STOP POINT**: Day-7 MVP complete only if actual acceptance gates pass. Stop; no post-MVP development without a new instruction.

## 22. Seven-Day Execution Plan

The schedule is a 51-hour target including roughly 45–60 minutes of debugging/review contingency each day. It assumes prompt decisions, existing LLM credentials, accessible Google/Supabase accounts, and competent use of the selected stack. Branches that add work consume contingency or require explicit scope/date adjustment; they are not magically free. Review pauses are mandatory; a day label never grants permission to run its whole list.

### DAY 1 — Foundation and secure connection (8 hours)

**GOAL**: Deploy a minimal authenticated shell and complete secure Google connection.

**TASKS**: Settle D1–D4/D13 as their gates arrive; establish environment/testing/session/profile boundaries; deploy early; store credentials securely; complete consent.

**WHY THESE TASKS ARE GROUPED TOGETHER**: Hosting, authentication and secret handling determine whether all later provider work is possible.

**INCREMENTS**: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4. Most are tiny boundaries or configuration checks; 1.4 and OAuth receive the largest time allocation. If login complexity consumes the budget, stop at the last completed increment and replan; do not skip token protection.

**EXPECTED END-OF-DAY DEMO**: Hosted login -> saved timezone -> connected test Google account; no token visible to the browser.

**BLOCKERS THAT MUST BE RESOLVED BEFORE MOVING ON**: Backend/auth/database decisions, account credentials, correct redirect origins, secure token storage, reachable free deployment or explicit local-hosting decision.

### DAY 2 — Live integration probes and manual tasks (7 hours)

**GOAL**: Prove both Google APIs and deliver the first useful task slice.

**TASKS**: Read one Gmail message and Calendar page; verify final write grant path; implement task persistence/API/form, project relation, edits, and one manual source.

**WHY THESE TASKS ARE GROUPED TOGETHER**: API risks are retired before substantial AI investment, then a stable task/source substrate becomes available.

**INCREMENTS**: 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1.

**EXPECTED END-OF-DAY DEMO**: Real Google reads succeed; create/edit/complete a task and associate a project; save a synthetic source.

**BLOCKERS THAT MUST BE RESOLVED BEFORE MOVING ON**: Gmail/Calendar access or clearly labeled fallback; user isolation; D7 knowledge representation; D5 source retention; provider/model choice for tomorrow.

### DAY 3 — Structured extraction and Gmail source persistence (7.5 hours)

**GOAL**: Complete the AI extraction vertical slice and replace its input plumbing with normalized Gmail data.

**TASKS**: Validate schemas, run one model call, log it, store/review/confirm candidates, then list/fetch/normalize/upsert selected Gmail sources.

**WHY THESE TASKS ARE GROUPED TOGETHER**: Manual-source extraction isolates model errors first; Gmail then feeds the same source contract.

**INCREMENTS**: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4.

**EXPECTED END-OF-DAY DEMO**: Pasted email -> confirmed source-backed task; selected live Gmail message appears as a deduplicated normalized source.

**BLOCKERS THAT MUST BE RESOLVED BEFORE MOVING ON**: Model schema/evidence/date reliability, no duplicate confirmation, private-content retention implemented as chosen, source ownership enforced.

### DAY 4 — Incremental Gmail and trustworthy Calendar availability (7 hours)

**GOAL**: Real Gmail reaches review and deterministic code finds valid work time.

**TASKS**: Connect pending Gmail sources to extraction, persist sync/history progress, expose sync controls, normalize complete Calendar windows, compute/test free time, show it on Today.

**WHY THESE TASKS ARE GROUPED TOGETHER**: Both integrations become reliable read-side inputs before exposing them to an agent.

**INCREMENTS**: 5.5, 5.6, 5.7, 6.1, 6.2, 6.3, 6.4, 6.5.

**EXPECTED END-OF-DAY DEMO**: Sync a new synthetic message twice, confirm one task, then inspect real busy/free time without an LLM doing interval math.

**BLOCKERS THAT MUST BE RESOLVED BEFORE MOVING ON**: D9 trigger choice, safe cursor recovery, complete Calendar pagination, timezone/date-only behavior, repeat sync no duplicates.

### DAY 5 — Read/planning agent and selective semantic memory (7.5 hours)

**GOAL**: A command invokes inspectable tools and produces a grounded feasible plan.

**TASKS**: Choose D6/D11; introduce one tool then bounded multi-read continuation; confirm/embed/search a few memories; validate and display planning output/run trace.

**WHY THESE TASKS ARE GROUPED TOGETHER**: The services already work; the agent composes them through small wrappers and explicit contracts.

**INCREMENTS**: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9.

**EXPECTED END-OF-DAY DEMO**: “Find three hours this week” -> tasks/Calendar/memory tools -> valid proposal or explicit clarification/shortfall -> run trace.

**BLOCKERS THAT MUST BE RESOLVED BEFORE MOVING ON**: D8 embedding timing and D12 embedding capability, bounded run budgets, owned refs, zero fake execution claims. If embeddings cannot be provided at $0 additional infrastructure cost, explicitly mark/revise that scope rather than pretending completion.

### DAY 6 — Approved external action (7 hours)

**GOAL**: Finish the principal end-to-end workflow with a real Calendar write.

**TASKS**: Settle D10; persist exact proposals; show approve/reject; validate freshness; implement stable-ID insert/reconciliation; claim/execute once; expose outcome/audit.

**WHY THESE TASKS ARE GROUPED TOGETHER**: These increments each strengthen the same side-effect boundary and culminate in one observable action.

**INCREMENTS**: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7.

**EXPECTED END-OF-DAY DEMO**: Gmail -> extracted reviewed task -> agent slot -> exact approval -> one real event -> trace; replay does not duplicate.

**BLOCKERS THAT MUST BE RESOLVED BEFORE MOVING ON**: No writes without approval; stale/changed payload denied; timeout reconciliation; OAuth grant still valid. Cut all optional work if this path is not working.

### DAY 7 — Evaluation and presentation readiness (7 hours)

**GOAL**: Demonstrate measured quality, safe failures, and reproducible setup.

**TASKS**: Finalize held-out cases, run/score extraction, run adversarial regressions, finish disconnect/retention, verify deployment and write demo documentation.

**WHY THESE TASKS ARE GROUPED TOGETHER**: No new core behavior is introduced except data-lifecycle controls; the day collects evidence and resolves release-blocking issues.

**INCREMENTS**: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6. Dataset authoring can move into spare earlier time, but each moved increment still requires its own review/stop.

**EXPECTED END-OF-DAY DEMO**: Rehearsed real integration flow, visible failure/reconnect handling, run trace, and labeled evaluation report with actual metrics.

**BLOCKERS THAT MUST BE RESOLVED BEFORE MOVING ON**: Any cross-user exposure, unapproved write, duplicate write, secret leakage, false success, broken hosted callback, or missing evaluation evidence. Do not declare complete merely because seven days elapsed.

### Time-pressure rule

First cut visual polish, optional daily cron, standalone Memory/Projects screens, and any optional tool. Preserve the single-account scope, source evidence, deterministic scheduling, exact approval, isolation, and write idempotency. If more time is still needed, record a reduced delivery explicitly: live integration failure means a fixture demonstration, not a completed live Gmail/Calendar MVP. Optional architectural branches cannot silently expand the schedule while retaining an unconditional seven-day promise.

## 23. MVP vs Stretch Scope

### MUST WORK BY DAY 7

- Verified sign-in, owner isolation, persisted timezone/working hours, protected routes and secure provider token refresh/reconnect.
- Bounded live Gmail selection, dedupe, history/cursor recovery and visible processing status.
- Structured source-backed task/deadline/event candidates; uncertainty and review/correction; one confirmed task per accepted candidate.
- Manual tasks and minimal project association; no general task management platform.
- Complete Calendar read windows, correct timezone/all-day/recurrence handling, deterministic free-time calculation and valid shortfall reporting.
- At least one read-tool round trip, bounded multi-step orchestration, selected long-term memory and a small genuine pgvector retrieval path if embedding access is confirmed at its decision gate.
- Valid plan -> exact human approval -> one real Calendar event, with replay safety and truthful reconciliation/audit.
- Run/context/tool/approval/usage trace; synthetic evaluation dataset and report; security/recovery tests; setup and demo notes.
- Disconnect, imported-data removal, and stated retention. Actual hosted behavior validated, with local fallback transparently documented if free hosting fails.

### NICE IF TIME ALLOWS

- Daily scheduled sync when D9-B is chosen and budget allows; manual/resumable sync remains sufficient.
- Local draft reply generation, read-only thread expansion and `tasks.create` agent tool using existing validated services.
- A small text/Markdown document upload: separate increments for private object storage/metadata, bounded plaintext extraction, existing source handoff, and ownership/delete tests. PDF/OCR is not hidden inside this item.
- Standalone project/memory browser, static evaluation report link in the UI, simple run-filter controls, extra synthetic eval cases.
- Fixed batch approval only if D10-B's added increments fit; this must be decided before dependent implementation.

### POST-MVP

- Sending email, Gmail-side drafts, attendee invitations, Calendar update/delete/reschedule, automatic rollback and autonomous external actions.
- Public multiuser Google onboarding/verification, team sharing, role administration and production availability guarantees.
- Pub/Sub push watches/renewal, frequent unattended ingestion, durable general job infrastructure.
- PDF/DOCX/attachment ingestion, OCR, large document chunking, multimodal extraction, sophisticated reranking.
- General knowledge graphs, inferred person relationships, dependency DAG scheduling, multi-calendar optimization, travel/buffer intelligence and recurring focus-plan writes.
- Fine-tuned models, evaluation platforms, full analytics dashboards, broad agent frameworks, generic plugin systems.

## 24. Risk Analysis

Each fallback preserves useful work but does not automatically satisfy the original live-integration acceptance criteria.

| RISK | WHY IT MAY HAPPEN | IMPACT | HOW TO REDUCE THE RISK | FALLBACK IF IT FAILS DURING THE 7-DAY BUILD | EARLY TEST |
|---|---|---|---|---|---|
| Google OAuth callback/consent failure — high | Wrong redirect, missing test user, blocked Workspace policy, denied scope | No live integrations | Stable hosted origin, dedicated test account, explicit scopes/state checks, verify callback locally and hosted | Continue synthetic-source task/extraction work while fixing; if unresolved, label integration demo as simulated | 1.4, 1.8, 2.3–2.4 |
| Gmail restricted-scope/public verification — high | Readonly is restricted; public launch requirements exceed a week | Public onboarding blocked | Keep allowlisted personal test demo; test actual account before ingestion investment; do not assume test mode is public approval | Manual pasted synthetic message uses same source/extractor; live Gmail remains an acknowledged gap | 2.5 |
| Refresh expiry/revocation — high | Testing tokens can expire in seven days; reconsent response may omit refresh token | Demo stops working or background sync fails | Preserve stored refresh token, atomic refresh, reconnect status, final-day rehearsal | Reconnect the authorized test account; use fixtures during outage | 2.2, 2.4; rehearse 9.6 |
| Calendar access/write restriction — high | Wrong calendar, missing grant, account-specific policy | No approved external write | Read and scope probe early; use owned test calendar and live final write only behind approval | Show proposal/approval without claiming execution; manual calendar action is outside the agent outcome | 2.6, then 8.6 |
| LLM extraction incorrect or unsupported schema — high | Model lacks native schema support, temporal ambiguity, wrong evidence | Wrong tasks/deadlines | Provider capability smoke, runtime validation, exact evidence, explicit reference time, user review, bounded repair | Retain source and require manual correction; use provider-compatible validated JSON if necessary, disclosed | 4.2–4.3 |
| Agent loops/invalid tools — high | Repeated model requests or invented identifiers | Wasted tokens, latency, unsafe dispatch | Registry allowlist, owned refs, persisted counters, no-progress stop, capped continuation | Restrict to the already-tested one-read workflow/clarification; record planning limitation | 7.1–7.3 |
| Deployment/serverless mismatch — high | Missing env, Python runtime issues, timeout, connection pooling | Hosted demo fails | Deploy the empty authenticated slice early; keep bounded requests; verify roles/runtime limits | Local presentation on existing hardware at $0; explicitly mark hosted deployment incomplete | 1.8 |
| Free quotas/project pause | Large bodies/vectors/logs, prolonged inactivity, exhausted host allowance | Storage failure or unavailable demo | Low source caps, selected embeddings, retention, dashboard usage checks, resume before demo | Reduce retained synthetic dataset; run locally against available DB; no automatic paid upgrade | 1.8, 5.4, 7.5 |
| Timezone/date-only errors — high | UTC conversion, DST, exclusive end dates, inferred cutoff | Invalid or late work blocks | Discriminated dates, IANA zones, frozen reference time and DST/all-day tests; clarify uncertain cutoffs | Require explicit date/time/zone and a narrower scheduling window; block uncertain scheduling | 4.2, 6.1–6.4 |
| Background work disappears | Fire-and-forget work killed, tab closed, job misses schedule | Partial sync, missing processing | Durable cursor/status/lease, small batches, visible continuation, daily cron only if selected | Manual Sync Now/Resume with persisted checkpoints; no claimed always-on behavior | 5.6–5.7 |
| Duplicate or uncertain external write — high | Retry after timeout, two approvals race, process crashes | Duplicate Calendar events or false status | Stable provider ID, immutable payload, atomic claim, get-by-ID reconciliation | Mark unknown and require reconciliation; never generate a fresh ID for a blind retry | 8.1, 8.5–8.6 |
| Prompt injection/private data exposure — high | Email instructions influence model, broad tools, leaked logs or RLS bypass | Unauthorized actions or disclosure | No generic tools, per-call policy, exact approval, scope/owner checks, source-as-data, redaction | Disable unsafe capability and retain read-only/manual flow until regression passes | 1.6, 4.3, 7.1, 9.4 |
| Embedding capability unavailable | Existing API covers generation only; local model not hostable | Semantic retrieval demo missing | Confirm query+memory embedding contract before coding vectors | SQL/lexical search with explicit reduced-scope label, or local semantic demo if user selects it | D12 at 4.3; validate by 7.5 |
| Seven-day overrun | Branch additions, slow approvals, unexpected provider debugging | Many unfinished features | One end-to-end path, 61 reviewable increments, time caps, daily demos and scope cuts | Deliver narrower honest workflow and list incomplete acceptance gates; never remove approval/isolation to save time | Day 1 decision gates; reassess daily |

## 25. Final Day-7 Architecture

### Complete logical architecture

ASCII only; no Figma artifact or diagram service is necessary for this planning document. D1 determines whether API/agent modules share the Next.js deployment or run in the Python backend. D2 determines application identity ownership. Optional components are explicitly marked.

```text
                          USER / TEST ACCOUNT
                                  |
                                  v
 +------------------------------------------------------------------+
 | Next.js UI                                                       |
 | Today/tasks | Inbox/review | Agent | Approvals | Runs | Settings   |
 +-------------------------------+----------------------------------+
                                 | authenticated HTTPS
                                 v
 +------------------------------------------------------------------+
 | API / backend (Next.js Route Handlers OR Python API; D1 open)      |
 | verified session -> runtime validation -> ownership -> services   |
 +----------+----------------------+----------------------+----------+
            |                      |                      |
            v                      v                      v
 +-------------------+   +----------------------+  +----------------+
 | Sync / ingestion  |   | Agent service        |  | Approval API   |
 | bounded pages     |   | context + checkpoint |  | human decision |
 | normalize/dedupe  |   | bounded tool choice  |  | exact payload  |
 | source provenance |   | plan validation      |  +-------+--------+
 +----+---------+----+   +----+------------+----+          |
      |         |            |            |               |
      |         v            |            v               |
      |  +--------------+    |   +-------------------+     |
      |  | LLM extraction|<--+-->| LLM API           |     |
      |  | validated JSON|        | generation/embed  |     |
      |  +-------+------+        +-------------------+     |
      |          |                 (D12 capability)        |
      |          v                                         |
      |  +------------------+                              |
      |  | Candidate review |                              |
      |  | confirmed tasks  |                              |
      |  +--------+---------+                              |
      |           |                                        |
      |           |     +----------------------------------v----+
      |           |     | Tool layer + permission/approval gate |
      |           |     | typed args, owned refs, risk, grants   |
      |           |     | deterministic scheduling              |
      |           |     | approve -> revalidate -> claim        |
      |           |     | execute/reconcile stable event ID     |
      |           |     +-----------+------------------+--------+
      |           |                 |                  |
      v           v                 v                  v
 +------------+  +--------------------------------+  +----------------+
 | Gmail API  |  | Supabase PostgreSQL             |  | Google         |
 | read-only  |  | profiles/projects/tasks/sources |  | Calendar API   |
 | history    |  | selected memories + pgvector    |  | read events    |
 +------------+  | private encrypted credentials  |  | approved insert|
                 | sync state/checkpoints/leases  |  +----------------+
                 | agent_runs/tool_calls/approvals|
                 +---------------+----------------+
                                 ^
                                 |
                 audit writes from sync, model calls,
                 tools, human decisions and execution

 Triggers: Sync Now / stale dashboard -> bounded sync service
 Optional: authenticated daily cron -> same service (D9)
 Provider secrets: backend/private store only, never UI or LLM
 Document upload / object Storage: stretch, not a Day-7 dependency
```

The diagram's storage connections represent owned repository access; tools do not receive unrestricted SQL. The agent dispatches tool requests to the permission gate, and the approval API supplies human decisions to that gate. Audit persistence is required before reporting any tool outcome.

### Incremental architecture comparison

```text
 EARLIEST USEFUL VERTICAL SLICE                  FINAL DAY-7 SLICE
 (after 3.4; Google probes already tested)       (after 9.6 acceptance checks)

 User                                          User
   |                                             |
 Next.js task form/list                         Next.js control surfaces
   |                                             |
 Verified API                                  Verified API
   |                                             |
 Task schema + owner checks                     +-- Sync -> Gmail API
   |                                             |     |
 Postgres profiles + tasks                      |   Sources -> LLM extraction
   |                                             |     |
 Persisted task visible                         |   Review -> Tasks/projects
                                                 |
 No active LLM/tool workflow yet                +-- Agent <-> LLM API
 No external writes                             |     |
                                                 |   Read tools
                                                 |     +-> SQL + pgvector memory
                                                 |     +-> Calendar read
                                                 |     +-> Deterministic slots
                                                 |     |
                                                 |   Validated proposal
                                                 |     |
                                                 +-- Human approval
                                                 |     |
                                                 |   Policy + fresh conflict check
                                                 |     |
                                                 |   Idempotent Calendar insert
                                                 |     |
                                                 +-- Tool result + audit + eval report
```

## 26. Implementation Session Protocol

This is a strict rule for future implementation sessions. **A day is not an implementation command.** “Start Day 2” means start its first incomplete small increment and stop after it. “Implement the agent” requires identifying/splitting the relevant increments and executing only the first one unless the user explicitly authorizes continuation.

### BEFORE CODING

Codex must state:

1. CURRENT INCREMENT
2. PURPOSE
3. WHY NOW
4. FILES EXPECTED TO CHANGE
5. EXPECTED BEHAVIOR AFTERWARD
6. HOW IT WILL BE TESTED

Check dependency completion and due decisions before starting. A missing architecture decision is surfaced with its condition/options and downstream consequences; do not silently select a branch. Do not re-ask decisions already made in the session. If a moderate increment contains unrelated logic, split it into numbered subincrements first.

**THEN IMPLEMENT ONLY THAT INCREMENT.**

### AFTER CODING

Codex must state:

1. FILES ACTUALLY CHANGED
2. WHAT WAS ADDED
3. WHY IT WAS IMPLEMENTED THAT WAY
4. TESTS / COMMANDS RUN
5. TEST RESULTS
6. MANUAL VERIFICATION STEPS
7. KNOWN LIMITATIONS
8. NEXT INCREMENT

**Then STOP. Do not automatically implement the next increment. Wait for the user unless they explicitly authorized continued increments.** An unfinished check must be reported as unfinished, not a pass. Test mocks and live provider verification must be distinguished.

Practical teaching: explain runtime validation when introduced despite TypeScript; explain access versus refresh tokens at 2.2; explain tool request -> validation -> execution at 7.2; explain what a memory vector represents at 7.5; explain approval and stable external IDs at Step 8. Keep explanations connected to the current change rather than giving a broad tutorial.

Never generate the whole application, thousands of lines in one step, every API/table/tool/screen at once, or unrelated refactors. Do not create empty future directories. No application code, dependency installation, scaffolding, provider setup or Increment 1.1 is authorized by the current planning-only request.

## 27. Final Implementation Checklist

Decision gates are checked at the appropriate time, not all necessarily before 1.1. A checked implementation item means its acceptance verification actually passed and the user had the increment's stop point; it is not an instruction to automatically move on.

### Phase 0 — Planning and prerequisite decisions

- [x] Create only root `plan.md` containing the technical blueprint.
- [ ] Record D1 backend/repository/hosting choice before 1.1.
- [ ] Record D2 identity and D3 database access choices before 1.4/1.5.
- [ ] Confirm access to required free accounts and existing model API; do not store credentials in the plan.

### Phase 1 — Foundation

- [ ] 1.1 Initialize only minimal selected runtime(s); root page and build work.
- [ ] 1.2 Validate environment boundaries; ignore private files; no secret output.
- [ ] 1.3 Add focused verification harness; environment test passes.
- [ ] 1.4 Complete selected login/callback/logout; verify session server-side.
- [ ] 1.5 Prove restricted database connectivity and identity propagation.
- [ ] 1.6 Add profiles only; persist timezone/hours; pass two-user isolation test.
- [ ] 1.7 Add protected `/api/me`; reject anonymous access; return no secrets.
- [ ] 1.8 Deploy current slice and verify hosted login/route behavior on free infrastructure.

### Phase 2 — Google risk retirement

- [ ] Resolve D4 credential protection before 2.1 and D13 grants/calendar choice before 2.3.
- [ ] 2.1 Add connection metadata and private credential storage with denied browser access.
- [ ] 2.2 Implement/test protection, refresh, token preservation, concurrency and reconnect state.
- [ ] 2.3 Configure test-user consent and APIs; implement session-bound consent start.
- [ ] 2.4 Validate callback/state; store encrypted tokens; display granted connection capabilities.
- [ ] 2.5 Read one real selected synthetic Gmail message through the backend.
- [ ] 2.6 Read one Calendar page; verify the final write-grant consent path without a write.

### Phase 3 — Task vertical slice

- [ ] 3.1 Add owned task table/date constraints/indexes and isolation tests.
- [ ] 3.2 Add runtime task payload validation and boundary cases.
- [ ] 3.3 Add authenticated task create/list API with create replay handling.
- [ ] 3.4 Add minimal task form/list; create and reload persisted task.
- [ ] Resolve D7 knowledge representation before 3.5.
- [ ] 3.5 Add minimal projects/owned task association; reject cross-owner references.
- [ ] 3.6 Add versioned task edit/completion and Today task ordering.

### Phase 4 — Structured extraction

- [ ] Resolve D5 source retention before 4.1 and D12 generation contract before 4.3.
- [ ] 4.1 Store one bounded manual source with provenance/hash and ownership.
- [ ] 4.2 Add task/event/envelope schemas and anchored date/ambiguity fixtures.
- [ ] 4.3 Make one structured model call; validate evidence and deterministic date relations.
- [ ] 4.4 Persist a redacted extraction run with real latency/available usage.
- [ ] 4.5 Persist deduplicated extraction review results and recoverable processing claims.
- [ ] 4.6 Confirm one reviewed candidate into an idempotent source-backed task.
- [ ] 4.7 Add review/correction UI and prove task appears on Today.

### Phase 5 — Gmail synchronization

- [ ] 5.1 List only selected IDs/metadata with bounded pagination.
- [ ] 5.2 Fetch selected bounded message bodies; handle unavailable messages.
- [ ] 5.3 Normalize MIME/text safely with thread/date/truncation/attachment metadata.
- [ ] 5.4 Upsert Gmail sources by provider identity; test concurrent dedupe.
- [ ] 5.5 Process one pending Gmail source through existing extraction/review.
- [ ] 5.6 Add durable initial/history cursor, atomic lease/checkpoints and rescan/retry recovery.
- [ ] Resolve D9 sync triggers before 5.7.
- [ ] 5.7 Add Sync Now/status/resume UI; secure optional daily trigger if selected.

### Phase 6 — Calendar availability

- [ ] 6.1 Define timed/all-day Calendar event DTO and validators.
- [ ] 6.2 Fetch every page of bounded event window; reject incomplete availability.
- [ ] 6.3 Normalize zones, all-day bounds, recurring exceptions and busy status.
- [ ] 6.4 Implement/test deterministic free-time and duration/shortfall calculation.
- [ ] 6.5 Show real Today schedule and read-only availability preview.

### Phase 7 — Read/planning agent and memory

- [ ] Resolve D6 orchestration and D11 conversation persistence before 7.1.
- [ ] 7.1 Add typed registry/request boundary and owned tool execution ledger.
- [ ] 7.2 Complete one tasks.list model-tool-result round trip.
- [ ] 7.3 Add existing Calendar read/slot tool bindings and bounded persisted continuation.
- [ ] 7.4 Persist small confirmed source-backed memories.
- [ ] Resolve D8 timing and D12 embedding capability/model/dimension before 7.5.
- [ ] 7.5 Embed selected memories with status/hash/version tracking.
- [ ] 7.6 Expose owned filtered semantic/SQL memory retrieval and its tool.
- [ ] 7.7 Validate planning schema, known slot refs and scheduling invariants.
- [ ] 7.8 Produce grounded plan/clarification/shortfall through the selected orchestrator.
- [ ] 7.9 Add command/run UI showing actual tools, context counts and outcomes.

### Phase 8 — Approved external action

- [ ] Resolve D10 approval unit before 8.1; split batch-specific additions if selected.
- [ ] 8.1 Persist immutable owned approval payload/hash/expiry/state.
- [ ] 8.2 Add proposal-only calendar.create_event tool; prove it performs zero writes.
- [ ] 8.3 Add exact-action preview and atomic approve/reject endpoint.
- [ ] 8.4 Revalidate permissions, task version, payload, expiry and fresh Calendar conflicts.
- [ ] 8.5 Add stable-ID insert/reconciliation adapter; test lost-response/duplicate cases.
- [ ] 8.6 Claim/execute one approved action; verify one real event and no replay duplicate.
- [ ] 8.7 Display truthful result/provider link and complete approval/tool audit.

### Phase 9 — Evaluation and release

- [ ] 9.1 Label 24 held-out synthetic cases with fixed temporal context and expected behavior.
- [ ] 9.2 Run real extraction evaluation through the app service; save redacted observations.
- [ ] 9.3 Score exact fields/semantic task rubric and publish counts/failures/versions in a report.
- [ ] 9.4 Pass agent/approval/injection/isolation/recovery regression gates.
- [ ] 9.5 Verify disconnect/reconnect, retention and imported-data removal across derived stores.
- [ ] 9.6 Run release checks/CI smoke, hosted auth, and approved live Calendar demo; document setup/limitations.

### Final acceptance gates

- [ ] Real Gmail -> reviewed task -> agent availability -> exact approval -> one Google event -> audit demonstrated.
- [ ] No unapproved writes, cross-user data access, leaked credentials or false success in the regression cases.
- [ ] Sync interruption, expired token, stale proposal, duplicate request and unknown write outcome have demonstrated recovery paths.
- [ ] Selected semantic memory is demonstrated, or its explicitly agreed reduced scope is reported as a limitation.
- [ ] Actual evaluation results and mocked-versus-live distinctions are documented.
- [ ] Free-tier/hosting limitations and all incomplete original acceptance criteria are stated accurately.
- [ ] Stop after the current authorized increment; begin nothing further without the user's instruction.
