# SHURY Company 5 — Capability Synthesis

Version: `24.2.0-alpha1-company5`

## Goal

Finish the bounded remainder of Company Phase 2: let the CEO derive **required capabilities** from structured semantic/task state and resolve those requirements through organizational contracts, without adding workflow-name routing or an LLM.

## Implemented

- `ExecutiveCapabilitySynthesizer` turns TaskIR/planned actions/semantic operation into typed `CapabilityRequirement` records.
- Candidate tools are matched by exact declared capability, then resolved through the organization registry.
- A future tool can join a department by declaring organization metadata; no tool-name routing table is required.
- Department/specialist selection remains registry-driven.
- Unowned capabilities fail closed and are reported as unresolved.
- When the normal planner returns no plan, a **bounded novelty bridge** can build an executable plan only when TaskIR is executable and every capability has an exact declared tool owner.
- TaskIR dependency IDs are translated to runtime step IDs (`t1 -> s1`) before execution.
- Company coordination exposes required capabilities, selected capability candidates, and unresolved capabilities.
- `/company-capabilities <goal>` provides a non-executing inspection surface.

## Design boundary

The synthesizer never classifies a user sentence directly. It consumes structured fields produced by the semantic layer or TaskIR. The organization layer therefore stays language-independent after semantic parsing.

No fuzzy text-to-tool execution is introduced. No LLM fallback is introduced. `Arabic-Retrieval-v1.0` remains the canonical semantic model.

## Verification

- Company + Organization regression: 54 passing tests in the release gate.
- Capability synthesis regression: included in the 54 passing tests.
- `python -m compileall -q app`: PASS before release packaging.
