# Lock-driven evidence handoff (step 3.1, producer side)

Candidate, non-authorizing, read-only. Authorized by the hub M0 decision record (cogno-us/cognous-open-control-stack, `docs/program-v0.2/m0-decision-record.md`) and specified by hub contract 1.4 (`docs/program-v0.2/s02/contracts/1.4-evidence-handoff.md`). Release and production remain on HOLD.

`handoff.py` builds and checks an immutable evidence envelope for exactly the component tuple in a hub `component-lock.json` supplied to the run, bound by the lock's byte digest. It replaces hardcoded pins with a lock-driven profile; the historical `../o6-q5/` constants and candidate stay as history and are unchanged.

What it does not do: select, advance or write a pin; edit the lock; carry a verdict, pass or expectation (an unknown member is refused); promote anything; or make a Qualification decision. Whether Qualification consumes an envelope is Qualification's own decision. Every successful check ends in `hold` / `not_authorized` / `effects: disabled`. An envelope for tuple T carries only evidence produced at T; a different lock is refused, so no historical pass transfers.

Lock key mapping (one documented mapping): the revision is `sha` or `accepted_sha`; both must be equal when both are present; `core_interop_sha` must equal it; anything else fails closed. Nested history members are ignored.

Not independently qualified. `tests/integration/lock_driven_handoff/` holds developer tests only; independent cases and expectations belong to Qualification. Operational trust cannot be asserted by the producer: the only accepted value is `not_established` with no operator evidence.
