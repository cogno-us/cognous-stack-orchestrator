# Recovery resolution contract proposal

**Status: DRAFT FOR REVIEW.** Proposed identifier: `cognous-recovery-resolution/0.1-draft`. This is a design proposal, not an accepted producer schema, implementation, qualification result, C1–C8 amendment or release-selection decision. Operational trust [#30](https://github.com/cogno-us/cognous-stack-orchestrator/issues/30) remains **HOLD / NOT ESTABLISHED**.

## 1 Purpose and ownership

Allow admissible later evidence to resolve uncertainty about an existing attempt while retaining the initial observation, subsequent evidence and disagreements. This optional evidence profile never authorizes execution, dispatches effects, creates replacement attempts or permits retry.

The Runtime owns persisted attempt identity and the eventual ledger implementation. The orchestrator owns observation intake and integration. Replay and Evidence Pack own versioned consumer mappings if needed. The hub retains release-selection authority. This document does not transfer those responsibilities or modify their accepted contracts.

Review lineage: [O6 parent #65](https://github.com/cogno-us/cognous-stack-orchestrator/issues/65), accepted [Q6 #82](https://github.com/cogno-us/cognous-stack-orchestrator/issues/82), and [Governor #14](https://github.com/cogno-us/cognous-stack-orchestrator/issues/14). The accepted Q6 issue stays completed for its original scope; this proposal addresses its disclosed limitations.

## 2 Evidence baseline

Inspected orchestrator source: `2ecb8ceb32a4f169cba102dc205f261866e54792`. Inspected Runtime source: `1b0a9e32d010797711004ae612051a277b07912a`. These are source-review anchors, not new selected-release pins.

| Source | Observation | Proposed response |
| --- | --- | --- |
| [Runtime closeout store](https://github.com/cogno-us/cognous-execution-runtime/blob/1b0a9e32d010797711004ae612051a277b07912a/engine/revocation_closeout.py) | One closeout row per attempt; `applied` and `partial` both set `closed=true` | Retain v1; introduce explicit outcome, finality and resolution states in a separately versioned profile |
| [Q6 coordinator](https://github.com/cogno-us/cognous-stack-orchestrator/blob/2ecb8ceb32a4f169cba102dc205f261866e54792/development/recovery/o6_q6/reconciliation.py) | Later differing observations HOLD; several intake provenance fields are not persisted by the closeout | Append evidence rather than overwrite; retain a commitment to admission inputs |
| [Q6 tests](https://github.com/cogno-us/cognous-stack-orchestrator/blob/2ecb8ceb32a4f169cba102dc205f261866e54792/tests/integration/o6_q6/test_reconciliation.py) | Conflict protection and no-retry behavior are intentional | Preserve v1 regression behavior; qualify the successor separately |
| [Q6 limitations](https://github.com/cogno-us/cognous-stack-orchestrator/blob/2ecb8ceb32a4f169cba102dc205f261866e54792/development/acceptance/o6-q6/README.md) | Overdue counts are historical; live observation truth is unauthenticated | Separate current work from history and declared capability from measured conformance |

Static source review additionally shows that `original_attempts_unresolved` counts only existing closeouts with `closed=0`; an in-doubt attempt awaiting its first observation is outside that count. No new Runtime or integration tests were executed to prepare this proposal.

## 3 Scope and invariants

1. Resolve an existing, unambiguous original effect/attempt binding. Carry tenant or namespace identity only from a trusted retained source. Missing required scope or ambiguous attempt identity yields HOLD; never invent lineage.
2. Preserve all accepted historical observations. A later event cannot erase an earlier applied fact or rewrite its source evidence.
3. Separate structural validity, source authentication, scope binding, freshness, observation coverage, finality and independent verification. Presence of a URL, digest or signature is not sufficient for all of them.
4. Keep `retry_eligible=false`, `execution_authority=none`, and `settlement_verified=false` throughout this bounded profile. A provider-specific settlement profile would require separate review.
5. `absent` and `unknown` do not establish non-execution or permission to retry. A terminal no-effect outcome is outside this proposal.
6. Retain partial effects as partial. Full completion requires evidence covering the complete original effect and a reviewed finality rule; record closure alone is insufficient.
7. Support one cooperating local durable store. C0 check-to-commit limitations remain; optional C1 remains same-host only. No C2/C3, remote transaction, production exactly-once or real settlement claim.

## 4 Proposed event and admission records

The fields below are a semantic review inventory, not a machine-consumable schema. Freeze the exact serialization and API through the owning Runtime review before implementation.

| Group | Required retained information |
| --- | --- |
| Version and identity | Profile version, stable event ID, retained namespace where required, original effect ID, original attempt ID, adapter ID and bound client reference |
| Content and lineage | Canonical event digest, expected prior stream revision, predecessor event digest, and separate local recorded sequence/time |
| Observation | Observed state, observed time with timezone, source ordering domain/value, observation reference and content commitment, coverage and finality status |
| Provenance | Observer identity/reference, watermark reference/commitment, provider-acceptance reference/commitment for applied or partial, and protected evidence-location reference |
| Admission | Admission-policy version/digest, configured trust-snapshot reference/digest, verifier identity/version, evaluation time, per-check disposition and reason code |
| Follow-up | Accountable recovery owner, deadline, unresolved-remainder or disagreement reference when applicable; no raw refused payload |

Reference, digest, source authentication and independent verification remain distinct fields. Values unavailable in historical records stay explicitly unavailable. Ordinary logs retain minimal identifiers, commitments and reason codes; sensitive evidence stays in a separately access-controlled location under its own retention rules. Dereferencing an evidence reference is not an automatic network action.

The content commitment must cover normalized submitted semantic fields, including identity, state, provenance, observed time, ordering and predecessor. Exclude only the digest itself and explicitly server-assigned receipt fields. Canonicalization must be deterministic, versioned and tested; choose its exact encoding before schema acceptance. One event ID with a different committed body is a conflict, not an idempotent duplicate.

Synthetic fixtures may use an explicit test-only trust profile. Their dispositions must remain `synthetic_admission`, never production-authenticated or independently verified merely because structural checks pass.

## 5 Admission and durable ordering

Intake resolves original identity through a supported Runtime API. It checks adapter binding, source eligibility, content commitments, configured freshness and clock uncertainty, ordering-domain comparability, observation coverage and any required provider acceptance. A caller-supplied larger counter or later timestamp is not by itself a superior observation.

Unavailable or failed prerequisite checks produce HOLD. Retain a minimized refusal/review record when the supported writer is available; failed persistence cannot produce a successful admission. Invalid or untrusted inputs never enter the accepted observation stream as if authenticated. Bounded disagreement records may reference rejected inputs without retaining raw payloads or promoting their truth.

Append the admitted event and update the derived projection in one local transaction with an expected-revision check. Never update the current projection without its durable supporting event. Concurrent contenders must not create two competing current revisions. A stale expected revision requires re-reading and re-evaluating evidence; this is ledger reconciliation, not effect retry.

An exact previously admitted event returns the same admission result without adding a duplicate event. It must also return the current projection separately: a historical success must not conceal a subsequently recorded disagreement or superseding resolution. Database integrity errors and unavailable storage stay explicit failures/HOLD.

## 6 Outcome and resolution projection

Keep three dimensions: latest admissible observation (`none`, `unknown`, `absent`, `partial`, `applied`); finality (`unestablished` or `established_for_named_profile`); and recovery work state (`awaiting_observation`, `awaiting_finality`, `partial_followup`, `conflict_review`, `resolved`). Preserve historical observations separately from this projection.

| Retained situation | New evidence | Proposed disposition |
| --- | --- | --- |
| No observation, unknown or absent | Admissible partial | Append; `partial_followup`; preserve remainder/finality uncertainty |
| No observation, unknown or absent | Admissible applied without sufficient finality/coverage | Append; `awaiting_finality`; no retry |
| No observation, unknown or absent | Admissible applied with complete coverage and profile-specific finality | Append; `resolved` for this evidence profile only |
| Partial | Admissible complete applied evidence covering the original effect and its remainder | Resolve only if ordering, coverage and finality checks pass |
| Any state | Exact admitted duplicate | Return prior admission and current projection separately; no additional event |
| Any state | Incomparable or credible contradictory evidence | Retain disagreement and enter `conflict_review`; do not erase historical applied facts |
| Any state | Missing, stale, untrusted or malformed evidence | HOLD; no favorable outcome promotion |

Conflict is not settled by last-write-wins. A resolution of disagreement requires an explicit policy-permitted adjudication event naming the disputed evidence, governing rule, competent evidence-review identity and justification. It supplies no execution authority. Until that procedure is reviewed and implemented, conflict remains HOLD. A later source correction or loss of an observation's assurance must be appended as a new review event, not delete history or silently preserve an obsolete current assurance.

## 7 Accounting and migration

The eligible current-work population is all retained in-doubt original attempts, including those with no closeout. Report missing/ambiguous attempt bindings separately as unattributable work; do not fabricate attempt IDs to make counts reconcile.

For attributable attempts, use exclusive work-state buckets from section 6. `current_unresolved` is all eligible attributable attempts except `resolved`; `current_overdue` is the unresolved subset whose valid deadline has passed. Report missing deadlines and unattributable work separately. `historical_in_doubt` remains a separate lifetime count. Capture one consistent read snapshot and disclose its evaluation time. Avoid mixing effect, attempt and observation-event denominators.

Preserve v1 tables, interfaces and interpretation. An optional migration can append a legacy-baseline event with only retained v1 facts. It cannot reconstruct missing provenance or infer full completion from v1 `closed=true`. Legacy-only resolved rows remain labeled legacy and cannot satisfy the successor's stronger resolution claims without admissible supporting evidence. Migration is repeatable/idempotent and must leave v1 bytes and historical exports unchanged.

Consumers must carry initial uncertainty, admitted events, disagreement and current projection with the profile/version and loss report. Unsupported successor records must be rejected or marked unsupported explicitly, never silently decoded as v1 completion.

## 8 Proposed acceptance matrix

All cases below are **PLANNED / NOT RUN**. These are future implementation obligations, not results of validating this document.

| ID | Case | Required observation |
| --- | --- | --- |
| RR-01 | Unknown then admissible complete applied | Both events retained; same effect/attempt; resolved only with coverage/finality; retry false |
| RR-02 | In-doubt with no first observation | Present in awaiting-observation and current unresolved population |
| RR-03 | Partial then incomplete or complete evidence | Incomplete remains follow-up; complete resolves only under the named rules |
| RR-04 | Stale/future/incomparable or unauthenticated evidence | HOLD with explicit reason; no favorable projection promotion |
| RR-05 | Exact duplicate and reused ID with changed content | Idempotent identical body; changed body conflicts |
| RR-06 | Concurrent competing and contradictory evidence | Serialized durable revisions; disagreement visible; no silent last-write-wins |
| RR-07 | Crash before and after ledger transaction | No projection without event; committed history/projection stable after restart |
| RR-08 | Missing evidence writer or projection write failure | No successful admission; atomic rollback or unchanged prior state |
| RR-09 | Previously resolved attempt reaches deadline | Excluded from current overdue; retained in historical in-doubt |
| RR-10 | Missing identity/deadline and multiple attempts | Explicit separate populations; no fabricated mapping or mixed denominator |
| RR-11 | Legacy migration and replay | Idempotent import, v1 unchanged, missing provenance visible, no assurance upgrade |
| RR-12 | Producer to Replay to Evidence Pack | Actual pinned implementations preserve lineage, counts and unsupported/loss states |
| RR-13 | Disabled guard/writer/provenance retention controls | Negative controls detect the removed protection; no effect-dispatch capability added |
| RR-14 | Duplicate after later disagreement or source correction | Historical admission remains readable; current HOLD/review state is not hidden |

Retain exact source/PR SHAs, commands, environment, case results and exclusions for actual qualification. Schema-only or document checks cannot establish durable behavior, source authentication or deployment trust.

## 9 Review decisions and implementation boundaries

Acceptance requires Runtime and orchestrator contract review of identity scope, canonicalization, API/versioning, admission policy, ordering/finality semantics, conflict adjudication, migration and metrics. Review C4/C5/C8 compatibility and any C1–C8 amendment through the existing hub governance process; no amendment is adopted here.

Recommended dependent work: (1) Runtime ledger and supported query API; (2) orchestrator intake, projection and metrics against accepted Runtime source; (3) necessary consumer mapping and integrated qualification. Each is a separately scoped owning-repository issue/PR after contract acceptance. No worker launch, component-lock change or production activation follows automatically from this proposal.

The proposal deliberately leaves deployment-specific trust roots, provider finality, retention policy and competent adjudicator configuration to explicit reviewed profiles. Those missing choices block corresponding assurance claims. Preserve operational #30 HOLD, C0 race disclosure, optional same-host C1, no C2/C3 and no real settlement throughout.
