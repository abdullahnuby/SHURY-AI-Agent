# Personal Agent V21 Architecture

```text
User Goal
   |
   v
Research / Discovery Router
   |
   +--> Web / arXiv / GitHub evidence
   |
   +--> GitHub Skill Discovery
   |        |
   |        +--> repository metadata
   |        +--> recursive tree scan
   |        +--> SKILL.md metadata preview
   |        v
   |     Candidate Catalog
   |        |
   |        v
   |     Bounded Materializer
   |        |
   |        v
   |     Schema + Security Audit
   |        |
   |        v
   |     Quarantine Registry
   |        |
   |        +--> Refresh / provenance
   |        +--> Route: area -> family -> skill root
   |        +--> Human approval -> trusted
   |
   +--> Runtime Failure
   |        |
   |        v
   |     Failure Skill Candidate
   |        |
   |        v
   |     Evaluation / Refinement
   |
   v
Governed SkillBank
   |
   v
Planner / Executor / Verification
```

Remote Markdown is evidence/instructions for review, never authority. Only validated machine-readable workflows referencing registered tools can enter the execution model, and remote trust is quarantined until approval.
