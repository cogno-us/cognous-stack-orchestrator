# Engineering agent operating instructions

Scope: all paths in this repository. Read [development/README.md](development/README.md), the active GitHub issue, and [CONTRACTS.md](CONTRACTS.md) before work.

Role separation: governor assigns/reviews/integrates; worker implements only the issue-scoped files in the owning repo. No implicit authority to merge, activate releases, change source contract C1-C8, or access/export private ISS internals.

Per-task procedure:
1. Check issue stage/owner and exact source head; identify accepted dependency revisions.
2. Write a short plan and list target files, affected trust boundaries, expected positive/negative tests.
3. Work on one isolated branch. No unrelated refactors and no duplicate workers on the same files.
4. Run affected validations once per final head; record exact commands, exit status and SHA.
5. Open a PR with the template, linking issue and evidence. Do not claim the PR is accepted until reviewed/merged.
6. Return: STATUS; ISSUE; REPO/HEAD; BRANCH/PR; DIFF SUMMARY; TESTS; CONTRACT IMPACT; RISKS; NEXT GATE.

Never invent CI, independent evidence, authenticated identity, effect verification or publication approval. Preserve ISS as an unimplemented external interface.
