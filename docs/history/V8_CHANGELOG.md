# V8 Changelog

## 8.0.0

### Planning
- replaced clause-only selection with bounded state-space best-first search
- separated path cost from heuristic score so budget constraints use real cost
- added precondition-producer insertion with bounded support search
- added duration/resource metadata and explicit constraint parsing
- emitted dependency edges for sequential and piped steps

### Execution
- dependency-aware ready queue replaces index-only execution semantics
- independent `parallel_safe` work can execute concurrently
- parallel effects commit in deterministic plan order
- wall-clock duration for a parallel batch is tracked by its maximum member duration

### Durability
- SQLite WAL, synchronous=NORMAL and busy timeout
- checkpoint revision + SHA-256 integrity verification
- append-only effect state fingerprints
- verified-effect recovery on resume to avoid duplicate side effects after crashes

### Memory
- BM25-like local ranked retrieval
- importance/freshness/access signals
- fact lifecycle history for overwrite/delete
- semantic / episodic / procedural recall facade
- verified plan experience cache

### Reliability / evaluation
- per-tool reliability snapshot
- horizon-survival report
- expanded V8 benchmark cases

### Compatibility
- V7 APIs remain available
- custom planners with the old `plan(goal, memory)` signature still work
- no non-standard Python dependency was introduced
