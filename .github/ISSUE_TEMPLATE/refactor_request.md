---
name: Refactor Request
about: Propose a refactoring or architecture improvement
title: "[Refactor] "
labels: refactor
assignees: ''
---

**Which component or layer?**
`[e.g., src/auditors/ / src/engines/pipeline.py / scripts/ / rules parsing]`

**What is the current problem?**
A clear description of the pain point: duplication, unclear responsibility, layering violation, maintainability issue.

**Proposed approach**
What refactoring do you suggest? Keep it scoped:
- Files/modules involved
- Target structure or design pattern
- What behavior must stay identical (golden test must still pass)

**Validation plan**
How will we verify no regression? (e.g., `pytest tests/ -v`, golden test, specific test files)

**Alternative approaches considered**
Briefly note alternatives and why they were rejected.

**Additional context**
Any related history, ADR, or prior attempts.
