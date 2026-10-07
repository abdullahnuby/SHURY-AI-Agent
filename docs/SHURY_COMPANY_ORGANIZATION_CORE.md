# SHURY Company — Organization Core v1

## Purpose

Transform SHURY from a single generalized agent with workflow-specific department labels into an organization-aware runtime where ownership, specialist selection, dependencies, handoffs, and review are structured and inspectable.

## Current organization

- Executive / CEO orchestrator
- Operations
- Data
- Research
- Development
- Memory
- Security Reviewer
- Quality Reviewer

More departments can be added without changing the routing algorithm when their ownership is declared in the registry.

## Ownership model

`app/organization/registry.py` is the organization routing source. `app/organization/company.py` declares the roster and its ownership data.

The planner does not need to know department names. A tool may declare its organizational owner through runtime metadata, while atomic capabilities and skills remain reusable organizational facts.

## Assignment model

A plan step becomes a `CompanyAssignment` containing:

- CEO
- department
- department head
- specialist
- skill
- capability
- tool
- dependencies
- expected effects
- authority
- reviewers

## Coordination model

A sequence of assignments becomes `CompanyCoordination`:

`CompanyTask -> CompanyHandoff -> CompanyTask`

A handoff exists only when a dependency crosses departments. It requires completion of the producer task and availability of its observed result.

## Security and QA

Risk-sensitive builder tasks receive the Security Reviewer. Builder outputs are independently checked by the Quality Reviewer. Reviewers hold no execution write surface.

## Failure behavior

Ownership is fail-closed. If the company cannot prove a department owns the requested skill, capability, expected effect, or explicit tool declaration, routing raises `OrganizationRoutingError` instead of silently assigning Operations.

## Compatibility

The Company layer does not introduce an LLM fallback and does not replace `Arabic-Retrieval-v1.0`. The canonical Brain remains responsible for semantic understanding, planning, deterministic tool execution, verification, learning, and final response composition.
