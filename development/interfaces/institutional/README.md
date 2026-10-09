# O4c-C institutional identity and Authority Context mapping

Status: candidate requirements mapping only; pending Governor/source-owner review.

This directory implements issue #12's narrow mapping against the exact Cognous Institutional Governance source revision 1386fd236f13896029e5ab47ba5b9c3127509c3d. It does not issue, authenticate, activate, suspend, revoke or authorize a grant.

## Exact source evidence

Repository: cogno-us/cognous-institutional-governance@1386fd236f13896029e5ab47ba5b9c3127509c3d.

- process/implementation/public-stack-v0.1/authority-context.schema.json: Authority Context schema_version=0.1.0 and interface_status=proposed_pending_governor_review; institution, principal, acting identity, requirement and optional grant fields are source-owned.
- process/implementation/public-stack-v0.1/AUTHORITY_CONTEXT.md: requirements, claimed grants and downstream runtime decisions are distinct; authority mode does not prove adoption; caller-supplied context/snapshots are not trusted; unknown authoritative status and required authorization evidence hold affected consequential effects.
- testing/harness/authority_context.py: the source reference checker explicitly assumes synthetic snapshot premises, requires issuer/domain and identity bindings, returns no_issued_grant without a grant, and treats required authorization evidence as hold_effect when unknown.
- testing/fixtures/authority-context/bases.json: source fixtures bind action institution/domain/acting identity to the context and represent issuer mandate/status as separate snapshot inputs.

These source artifacts themselves state that they do not authenticate institutions, establish adoption or make a runtime authorization decision.

## Candidate mapping

authority_context_mapping.py performs only local consistency checks:

1. Pin the exact source revision, schema version and review-pending interface status.
2. Bind request tenant/actor to an explicit supplied identity-binding record, then require that record to match source institution, principal and acting identity.
3. If a source grant claim is present, require the claimed issuer, requirement, grantee and acting identity to match the supplied mapping. This is claim consistency, not issuer authentication.
4. Require source-declared required authorization evidence to retain unknown_behavior=hold_effect.
5. Return authority=not_established and effect_disposition=hold_effect even when every mapping check passes.

An institutional_adoption_ref is deliberately only a reference. Missing adoption evidence yields adoption_state=missing; a supplied reference yields reference_present_unverified. Neither state is an adopted grant or permission.

## Trust boundary and non-goals

The authenticated institutional grant issuer/resolver is external and remains an O1 issue #2 acceptance dependency. This candidate neither verifies source authenticity nor decides that a supplied issuer, mandate, adoption record, tenant, actor or grant is genuine. It never calls the Control Plane and has no allowed/runtime-decision output.

No C1-C8 contract is changed. No ISS interface is activated. No source component repository is modified.

## Tests

Run:

python -m unittest discover -s tests/contracts/institutional -p 'test_*.py' -v

Negative vectors cover source/status drift, tenant mismatch, actor mismatch, institution/principal/acting-identity mismatch, issuer mismatch, grant identity mismatch, prohibited authorization fields, malformed required-evidence semantics and adoption-reference hold behavior.
