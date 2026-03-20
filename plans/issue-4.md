# Issue #4 — Listing todos reverses their order each time

## Problem
Each call to `list` (or `ls`) reverses the order of todos. Calling it twice in a row shows items in opposite order each time.

## Root cause
In `src/app.ts` line 28, the `listTodos` function uses:

```ts
const displayTodos = todos.reverse();
```

`Array.prototype.reverse()` mutates the array **in place** and returns a reference to the same array. Because `todos` is a module-level variable that persists for the lifetime of the process, and because the reversed array is also written back implicitly through the shared reference, every invocation of `listTodos` reverses the authoritative list. In the current CLI (one command per process), the mutation is also persisted to disk indirectly: other commands that run after `listTodos` in the same import (none today, but a risk) would operate on the reversed array. More critically, the JSON file written by any subsequent `saveTodos` call would store the reversed order, making the flip-flop visible across separate process invocations.

## Current-state observations
- `todos` is declared as a module-level `let` in `app.ts` (line 4) and loaded once from `todos.json` via `loadTodos()`.
- `listTodos` is the only function that calls `.reverse()` on the array.
- No other function copies or re-sorts `todos` before operating on it, so the mutation propagates everywhere.

## Proposed changes

### 1. Use a non-mutating copy in `listTodos` (`src/app.ts`)
Replace:
```ts
const displayTodos = todos.reverse();
```
with a shallow copy before reversing:
```ts
const displayTodos = [...todos].reverse();
```
This leaves the original `todos` array untouched while still displaying items in reverse (newest-first) order.

### 2. Add a simple automated test (optional, recommended)
Add a small test (e.g. in a new `src/__tests__/app.test.ts` or similar) that:
1. Adds three todos.
2. Captures the output of two consecutive `listTodos` calls.
3. Asserts the order is identical in both calls.

This prevents regressions. The project currently has no test framework configured, so a lightweight choice like `vitest` or `jest` would need to be added as a dev dependency if this step is pursued.

## Risks and open questions
- **Intentionality of reverse display order:** The current code appears to intend showing newest todos first. The fix preserves that intent. If chronological (oldest-first) order is preferred instead, the `.reverse()` call should simply be removed rather than copied.
- **No existing test suite:** There are no automated tests in the project today, so verifying the fix relies on manual reproduction unless a test framework is introduced.
