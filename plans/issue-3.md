# Issue #3 — Search is case-sensitive and misses valid matches

## Problem
The `search` command in the CLI todo app performs a case-sensitive match, so
`search "buy"` does not find a todo with the text `"Buy groceries"`.

## Current state
In `src/app.ts` (line 68), `searchTodos` filters with:

```ts
const results = todos.filter((todo) => todo.text.includes(query));
```

`String.prototype.includes` is case-sensitive, causing the mismatch.

## Proposed changes
In `src/app.ts`, update the `searchTodos` function to normalize both the todo
text and the query to lowercase before comparing:

```ts
const results = todos.filter((todo) =>
  todo.text.toLowerCase().includes(query.toLowerCase())
);
```

No changes are needed in `index.ts`, `storage.ts`, or `types.ts`.

## Risks / open questions
- None identified — the change is a single-line fix with no impact on other
  commands or data formats.
- If future requirements call for regex or fuzzy search, a more general
  matching utility could be introduced, but that is out of scope for this issue.
