# SHURY Company-2 Completion Report

## Gate
The Company QA reviewer is a mandatory post-execution gate. A run cannot remain `completed` after the reviewer returns `ok=false`.

## Runtime path

```text
Goal
 -> CEO
 -> Department
 -> Specialist
 -> Tool execution
 -> Tool verification
 -> Independent QA Reviewer
 -> Final verified response
```

## Cross-department contract

```text
Operations: recursive snapshot
Data: analyze CSV collection and select candidate
Operations: move selected file safely
Operations: create report
Operations: reread report
QA: verify objective, handoffs, integrity, and unchanged files
Security: review the high-risk move
```

## Evidence checks
- Assignment count equals plan step count.
- Every delegated step includes `qa:reviewer`.
- High-risk move includes `security:reviewer`.
- All execution steps are complete.
- CSV analysis is verified and selection matches recomputed maximum.
- Move destination exists and selected SHA-256 is unchanged.
- All other files from the source snapshot retain their original SHA-256 values.
- Report contains the selected source, destination and fingerprints.
- Report is reread before QA completion.
- Final response is derived from the QA-approved result.

## Test results

```text
20/20 PASS
compileall PASS
```
