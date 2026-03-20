# Issue #23 — Bug: `clear` command deletes ALL todos instead of only completed ones

## Problem
The `clearCompleted()` function in `src/app.ts` wipes the entire todo list (`todos = []`) instead of removing only the completed items. Running `todo clear` after completing a subset of todos leaves the list empty rather than preserving pending items.

## Current State
- **`src/app.ts:173-184`** — `clearCompleted()` correctly counts completed todos and early-returns when there are none, but on line 181 it replaces `todos` with an empty array instead of filtering.
- **`src/index.ts:107-109`** — The `clear` command invokes `clearCompleted()` with no additional logic.
- **No test suite exists** in the repository, so the bug is not caught by automated tests.

## Proposed Changes

### 1. Fix the filter in `clearCompleted()` (`src/app.ts`)
Replace:
```ts
todos = [];
```
with:
```ts
todos = todos.filter((t) => !t.completed);
```
This retains all pending (non-completed) todos and removes only the completed ones.

### 2. Add tests for `clearCompleted()`
Because no test infrastructure exists yet, set up a minimal test harness (e.g. a lightweight framework such as `vitest` or Node's built-in `node:test`) and add at least the following cases:
- Clearing when some todos are completed leaves pending todos intact.
- Clearing when no todos are completed produces a no-op with an informational message.
- Clearing when all todos are completed results in an empty list.

## Risks & Notes
- The fix is a single-line change with a small blast radius.
- `saveTodos()` in `src/storage.ts` has a separate bug: its custom JSON replacer strips the `completed` field during serialization, which means completion state is lost on reload. This is out of scope for this issue but worth noting as it would affect any test that round-trips through the storage layer.
- There is no existing test framework configured in `package.json`. Adding one is recommended but optional for this bug fix.

## Open Questions
- None — the issue description pinpoints the exact bug and the fix is straightforward.
