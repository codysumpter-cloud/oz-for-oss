# Issue #23 — Implementation Summary

## What changed

### Bug fix (`src/app.ts`)
Replaced `todos = []` with `todos = todos.filter((t) => !t.completed)` in `clearCompleted()` (line 181). The function now retains pending todos and removes only completed ones.

### Test infrastructure
- Added `vitest` as a dev dependency.
- Added `"test": "vitest run"` script to `package.json`.
- Created `src/app.test.ts` with three test cases for `clearCompleted()`:
  - Clearing with a mix of completed/pending todos preserves only the pending ones.
  - Clearing when no todos are completed is a no-op and prints an informational message.
  - Clearing when all todos are completed results in an empty list.

Tests mock the storage layer (`loadTodos`/`saveTodos`) to avoid filesystem side effects and to bypass the known `saveTodos` serialization bug (out of scope).

## Validation
All 3 tests pass via `npm test` (vitest run).

## Assumptions / Follow-ups
- The `saveTodos()` replacer in `src/storage.ts` strips the `completed` field during serialization. This is a separate bug (noted in the plan) and was not addressed here.
- Tests use `vi.doMock` with `vi.resetModules` to re-initialize the module-level `todos` array for each test case.
