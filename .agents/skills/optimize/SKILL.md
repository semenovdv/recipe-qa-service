---
name: optimize
description: Walk through a file and rewrite its implementation to be as simple and efficient as possible while keeping the core logic unchanged; the goal is readability and comprehension, not new features.
---

# Optimize

Simplify the implementation of a target file without changing what it does.

## What to do

1. **Read the whole file first.** Understand what the code does, its public
   surface (functions/classes others import) and its tests before changing
   anything.
2. **Walk through the file top to bottom** and look for:
   - dead code, unused imports, unused variables, unreachable branches;
   - duplicated logic that can collapse into one helper;
   - overly clever constructs (nested comprehensions, one-letter names,
     chained conditions) that can be plain, boring code;
   - long functions doing several things — split by intent;
   - needless data shuffling (extra copies, repeated lookups, re-parsing).
3. **Rewrite for a first-time reader**: descriptive names, small focused
   functions, early returns instead of deep nesting, docstrings on
   non-obvious pieces.
4. **Keep efficiency where it matters**, but prefer clarity over micro-
   optimizations unless a real hot path is documented.

## Hard rules

- **Core logic must not change**: same inputs → same outputs, same public
  API, same error types and side effects.
- **No new features, no behavior additions**, no renames of public symbols
  used elsewhere.
- **Tests must stay green**: run the relevant test suite (e.g.
  `.venv/bin/python -m pytest -p no:cacheprovider`) before and after; if
  tests break, fix the implementation, never the test.
- Prefer deleting code over adding code. If a rewrite grows the file
  meaningfully, reconsider.
- Type hints and style stay consistent with the project (Python: PEP 8,
  type hints, `from __future__ import annotations`).

## Output

Summarize what was simplified (deleted duplication, renamed, flattened)
in one short list; note anything deliberately left alone and why.
