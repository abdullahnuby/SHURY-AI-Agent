# SHURY Company-2 — V27 Release

## Purpose

Company-2 extends the canonical deterministic Brain with explicit organizational ownership,
independent QA review, and the V27 sales-analysis workflow.

## V27 workflow

```text
list_files_recursive
  -> analyze_csv_by_average
  -> create_sales_analysis_report
  -> move_workspace_report
  -> read_file
  -> independent QA review
```

The workflow is language-independent. The planner derives report and destination paths from the
structured goal and uses execution references to carry the actual destination from the move step
to the reread step.

## Ownership

- Operations: recursive workspace snapshot, report movement, report reread
- Data: CSV ranking and analytical report generation
- Security reviewer: filesystem move
- Quality reviewer: independent final verification

## Regression coverage

The V27 regression suite covers:

- collision-safe destination naming
- execution reference resolution (`{{s4.destination}}`)
- Windows/POSIX workspace path normalization
- report/source fingerprint preservation
- unchanged original-file verification
- required tool ordering and department assignments
- mandatory security and QA review

## Verification

```text
Company-focused regression: PASS
Company test count: 24/24
compileall: PASS
Canonical Brain structured execution: PASS
Independent QA: PASS
```

## NLP environment boundary

Production natural-language routing uses `omarelshehy/Arabic-Retrieval-v1.0` through Sentence
Transformers. The clean build does not bundle Python environments or model weights. A local run
must install `requirements.txt` and can use the configured Hugging Face model cache.

## Clean-release policy

Generated SQLite runtime state, logs, pytest caches, benchmark output folders, phase result dumps,
legacy generative runtime files, and the old release-history artifacts are intentionally excluded.
The application recreates runtime state under its configured data locations.
