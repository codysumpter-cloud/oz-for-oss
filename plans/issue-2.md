# Issue #2 — "delete" command removes more todos than expected

## Problem
Running `node dist/index.js delete 2` on a three-item list deletes the targeted todo **and every todo after it** instead of only the single targeted item.

## Root cause
In `src/app.ts` line 62, `deleteTodo` calls:

```ts
const removed = todos.splice(index);
```

`Array.prototype.splice(start)` with no second argument removes **all** elements from `start` to the end of the array. The delete-count argument (`1`) is missing.

## Current-state observations
- `deleteTodo` (src/app.ts:54-65) converts the 1-based `position` to a 0-based `index` correctly (`position - 1`), but the `splice` call is wrong.
- The function only logs `removed[0].text`, so from the user's perspective it looks like one item was deleted, even though every subsequent item was also removed.
- No tests exist for any of the app functions.

## Proposed changes

### 1. Fix the splice call (src/app.ts:62)
Change:
```ts
const removed = todos.splice(index);
```
to:
```ts
const removed = todos.splice(index, 1);
```

This limits removal to exactly one element.

### 2. Add a unit test for `deleteTodo`
Create a test file (e.g. `src/__tests__/app.test.ts` or `tests/app.test.ts`) covering at least:
- Deleting a middle item leaves the items before and after it intact.
- Deleting the first item.
- Deleting the last item.
- Attempting to delete an out-of-range position prints an error and does not modify the list.

A lightweight test runner such as `vitest` or Node's built-in `node --test` would suffice; choose whichever aligns with the project's preferences.

## Risks and open questions
- **Other splice-like patterns**: No other function in the codebase uses a single-argument `splice`, so this is an isolated fix.
- **Test infrastructure**: The project has no existing test setup. The implementer should decide on a test runner and add the necessary dev-dependency and npm script. This is a minor scope addition but valuable for preventing regressions.
- **Related bugs**: The codebase contains several other commented bugs (off-by-one in `completeTodo` and `editTodo`, inverted filter in `listByPriority`, reversed comparison in `listOverdue`, `clearCompleted` wiping all todos, and `saveTodos` stripping the `completed` field). These are out of scope for this issue but should be tracked separately.
