# Company 14 — C12 Governance

- Added deterministic `CompanyGovernance` runtime authorization.
- Added action classes: read-only, state-producing, controlled-side-effect, destructive, external-publication, privileged, financial.
- High/critical actions require explicit human approval and an independent security reviewer.
- Department authority `proposes` / `escalates` requires human approval.
- Reviewer roles cannot execute producer actions.
- Approval requests carry a SHA-256 action fingerprint.
- Governance denials are fail-closed and do not become generic replan requests.
- Added current OWASP and Microsoft runtime-governance references to the existing source catalog.
- Added `/company-governance <goal>` inspection command.

Gate: high-impact actions cannot bypass the governance contract.
