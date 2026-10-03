# Phase 20 Security Baseline

Date: 2026-10-03

## Recorded security violations before fixes

1. Approval bypass: CognitiveKernel._execute_result used `approve or lambda: True`, allowing a requires_approval tool to execute when no approval callback was supplied.
2. Workspace escape: app/integrations/devops.py `_resolve_project_path()` accepted absolute paths outside AGENT_WORKSPACE; project inspection/checks could therefore operate on arbitrary local directories.
3. Cross-principal task/session access: authenticated Web API lookups accepted arbitrary session IDs with the single bearer token and had no task/session owner binding. This exposes another principal's session if distinct principals share the deployment API surface.
4. High-risk external skill admission: governance admitted high-risk external packages as `restricted` candidates. This was not an executable bypass in the baseline because activation is gated, but it remains under security review.
5. Task error exposure: persisted task errors were serialized to the Web API without the same redaction used for logs, creating a secret/error-channel exposure risk.

## Security controls observed as passing in baseline probes

- SSRF: loopback, localhost, IPv6 loopback and link-local metadata address rejected by validate_public_url().
- Calculator: Python import/system-call and lambda execution rejected; simple arithmetic succeeded.
- RAG/web evidence: external content is handled as evidence/data; no direct execution path found.
- Skill workflows: only registered tools are accepted and activation requires approved/trusted lifecycle state.
