# Rename plan Q5: producer-observation `disposition` to `execution_standing`

**PROPOSAL. Non-authorizing. NOT IMPLEMENTED, awaiting operator authorization.** Release and production remain on HOLD. This document changes no `.py` file, no test, no workflow and no existing README; [observations.py](observations.py) and [README.md](README.md) are as merged. Implementation of Q5 is not authorized in this round. Nothing here claims clearance, certification, qualification or production readiness, and no independent review has taken place.

Origin: architect decision Q5 (approve rename). Use `execution_standing`, not `standing`, to distinguish execution or coordination status from an authorization decision or a human-review disposition. Preserve separate names for authority outcome, effect observation and review decision. Make the correction before the profile's first frozen version.

Verified against Orchestrator `72fb6ed`. Baseline: `tests/integration/producer_observations` (part of 438 tests with the workflow machine and store) passes on Python 3.11.17 and 3.13.16.

## 1. Current state

The member `disposition` is part of the exact member set (`FIELDS`) of profile `cognous-producer-observation/0`. It carries one fixed value, `"hold"` (`FIXED_DISPOSITION`); any other value is refused as `fixed_field_changed`. The README already records that this `disposition` is not the human-review `disposition` of the hub AOI-C01 envelope and calls renaming "an operator-visible naming candidate to decide before the profile is frozen". The profile is a candidate wire name (provisional `/0`, Q4) and has not been frozen.

Note for the architect: the decision text calls the producer-observation wire unmerged. In the Orchestrator it is merged on `main` as a candidate (module, README, tests and the `producer-observations.yml` developer-test workflow all exist at `72fb6ed`). It is unfrozen and unqualified, which is what matters for the rename, but the word "unmerged" does not match the repository.

## 2. Names that must stay separate

| Concept | Name used today in the program | Owner | Meaning |
|---|---|---|---|
| Authority outcome | Control Plane decision result (`authorized`, `hold`, `deny`) | Control Plane | A decision about whether an effect may proceed |
| Effect observation | `observation.*` states (`applied`, `partial`, `absent`, `unknown`) | observation records (not the Orchestrator) | Independent evidence about what happened |
| Review decision | AOI-C01 `disposition` (human review) | hub AOI-C01 envelope | A reviewer's decision about a submitted item |
| Execution standing (new name) | `execution_standing` | this profile (producer observation) | The Orchestrator's own standing for the record: fixed `hold`, meaning the record carries no execution, authorization or release effect |

Proposed rule for the README and module docstring: `execution_standing` is neither an authority outcome, an effect observation nor a review decision, must not be read as, mapped to or compared with any of them, and its single permitted value `hold` is a statement about the record (nothing is executed, authorized or released on its strength), never about the world. The unrelated `effect_disposition` member of the institutional Authority Context mapping (`development/interfaces/institutional/authority_context_mapping.py`) is a different profile and name and is not touched. Likewise not touched: `development/scenarios/customer_refunds/compose.py:34` and `development/scenarios/customer_refunds/evaluate.py:23`, which belong to a different profile and also emit `"disposition": "hold"`; the rename in this plan does not apply to them and they need their own decision if renamed.

The value stays `hold`: it matches the program's HOLD wording and is the existing fixed value; changing both the name and the value would make a larger wire change than the architect approved. A value change is open question 2.

## 3. Exact changes (for the implementation round; none made here)

Line numbers are for Orchestrator `72fb6ed`.

`development/acceptance/producer-observations/observations.py`

| Line | Today | Change |
|---|---|---|
| 5-6 (module docstring) | "every record carries the fixed disposition "hold"" | "the fixed execution standing "hold"" |
| 40 (`FIELDS`) | `"disposition"` | `"execution_standing"` |
| 47 | `FIXED_DISPOSITION = "hold"` | `FIXED_EXECUTION_STANDING = "hold"` |
| 165-166 (`validate`) | reads `observation["disposition"]`, compares to `FIXED_DISPOSITION`, `_refuse("fixed_field_changed", "disposition")` | read `observation["execution_standing"]`, compare to `FIXED_EXECUTION_STANDING`, detail `"execution_standing"` |
| 231 (`build`) | `"disposition": FIXED_DISPOSITION` | `"execution_standing": FIXED_EXECUTION_STANDING` |

The refusal code `fixed_field_changed` and the closed `CODES` set are unchanged (the static test that compares `CODES` with the `_refuse` literals keeps passing). `execution_standing` contains no `FORBIDDEN_MARKERS` substring (checked: none of `verdict`, `pin`, `expect`, `grant`, `authori`, `approv`, `accept`, `pass`, `fail`, `decision`, `certif`, `qualif`, `release`, `promot`, `select`, `allow`, `permission`, `result`, `clear` occurs in it), so it cannot be refused as `forbidden_member` by accident; a test should pin that. The constant name `FIXED_DISPOSITION` is not imported elsewhere in the repository (only this module and the tests reference the member; grep over `*.py`).

`development/acceptance/producer-observations/README.md`

| Line | Change |
|---|---|
| 7 (member list) | replace the last member `` `disposition` = `hold` `` with `` `execution_standing` = `hold` `` |
| 18 (reading the records) | rewrite the bullet: `execution_standing` is the fixed value `hold` of this profile; it is not an authority outcome, an effect observation, or the human-review `disposition` of AOI-C01 and must not be read as, mapped to or compared with them. Delete the sentence saying renaming would change the profile and the name is kept |
| (new) | a short note stating that the member was renamed from `disposition` before the first frozen version, that records with the old member are refused (section 4), and the pointer to this plan |

`tests/integration/producer_observations/test_observations.py`

| Line | Today | Change |
|---|---|---|
| 63 | `assert obs["disposition"] == "hold"` | `assert obs["execution_standing"] == "hold"` |
| 169-171 | `test_fixed_disposition_cannot_change` sets `obs["disposition"] = "release"` | rename to `test_fixed_execution_standing_cannot_change`; set `obs["execution_standing"]` |
| 621 | `_t_fixed_field_changed` sets `d["disposition"] = "x"` | set `d["execution_standing"]` |

New tests (required with the change, per the repository rule that every behavior change has a test):

1. A record carrying the old member `disposition` and no `execution_standing` is refused (the code is `unknown_member`: `disposition` matches no forbidden marker, and the exact-member check refuses extras first); a record carrying both is refused.
2. A record without `execution_standing` is `schema_invalid` ("exact members required").
3. `execution_standing` with a value other than `hold` (including empty, non-text, `Hold`) is `fixed_field_changed`.
4. Digest and id differ from a pre-rename record with otherwise identical content (the member is inside the digest), pinning that the rename is a wire change.
5. `execution_standing` is not matched by `FORBIDDEN_MARKERS` (so it is not accidentally refused), and a hypothetical member named for an authority outcome or review decision (`decision_result`, `review_disposition`) stays refused or unknown.
6. A store test: a store directory containing a record written with `disposition` fails `verify_chain` with a typed code, and the whole store must be recreated (section 4), proving no silent acceptance of the old shape.

`.github/workflows/producer-observations.yml` runs the same test directory and needs no change (its path filters already include `development/acceptance/producer-observations/**` and `tests/integration/producer_observations/**`). The workflow file is not changed by this proposal.

## 4. Wire consequences and migration

- The member is inside the digest, so every digest, `observation_id` and chain value changes for every record. The rename is a wire change. It is acceptable because `cognous-producer-observation/0` is provisional and unfrozen (Q4: freeze each schema at its own qualification boundary), and the architect asks for the correction before the first frozen version. If the identity is later frozen and then changed, a new identity (`/1`) is required.
- Proposal: keep the profile string `cognous-producer-observation/0` for the corrected shape and state in the README that the `disposition` shape was never frozen. The alternative, `/1` now, is safer against confusing old and new records but contradicts "provisional `/0`"; this is open question 1.
- Existing stored records: none are known to exist outside tests (the module has no production caller; the producer is not wired to a running orchestrator). Before the change, the implementer must confirm that on the actual hosts (search for `*.json` stores named by `ObservationStore` callers); if none exist, no migration is needed and old-shaped records are simply refused. If any exist, they cannot be rewritten in place (chain digests would change and the originals are custody): keep the old store read-only as a historical record, create a new store under the new shape, and record the mapping out of band. No in-place migration tool is proposed.
- Consumers: Qualification ingestion is Qualification-owned and does not exist in this repository; a search of hub `c6ef531` for the profile string `cognous-producer-observation` and for `execution_standing` found no reference, so no cross-repository text depends on the old name. The implementer must still notify the Qualification owner of the wire change before the freeze.

## 5. Not done and not claimed

Not implemented; no code, test, README or workflow edited. No independent review. The rename does not make the observation an authority record, does not change what the module refuses, and does not relax any forbidden-member behavior.

## 6. Open questions for the architect or operator

1. Keep the string `cognous-producer-observation/0` for the corrected shape (recommended while unfrozen) or move to `/1` now?
2. Keep the fixed value `hold` (recommended) or also rename the value?
3. Operator authorization of the exact implementation package (files and lines in section 3, with the new tests of the same section).
4. Confirmation that no real stores in the old shape exist outside tests.
5. Correct the "unmerged" wording in the decision record, or confirm the intent was "not frozen".


## Successor note (step 3.4-A)

Implemented in step 3.4-A (branch `s34-a-execution-standing`): see [README.md](README.md), [observations.py](observations.py) and the tests. The text above is the historical proposal and is not rewritten; it still describes the pre-rename state. Non-authorizing; release and production remain on HOLD.
