# SHURY Company C10 Release

## Scope

Company Memory adds a durable organizational memory namespace on top of the existing canonical `Memory` authority.

## Stored knowledge

- CEO/team decisions
- ownership facts
- verified reusable procedures
- verified failure lessons
- independent review findings
- structured execution outcomes

## Boundary

Company memory is stored with `scope=company` and an explicit organization owner id. User/session/run memory remains separate. Company retrieval is explicit through `CompanyMemory`; the normal user-memory controller does not merge these records. Raw user text is not written by the company facade.

## Verification

- C10 and Company regression: 88/88 PASS
- `python -m compileall -q app`: PASS
- Canonical structured Brain can retrieve previously stored verified company records: PASS
- Company-memory writes using user provenance: BLOCKED
- Company memory does not inherit unrelated user memory or task context: PASS

## Known unrelated full-suite status

The full repository suite still contains legacy failures in the old `/agent` path (e.g. historical save-note intent/planner cases). Those are outside the C10 change surface and are not claimed as fixed by this release.
