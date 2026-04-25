# Issue #333: Support agent statements in triage response alongside follow-up questions

## Product Spec

### Summary

The triage response comment should be able to render concise, reporter-facing informational statements (root-cause findings, repro confirmation, relevant file pointers) directly in the visible section of the comment, alongside or before follow-up questions. Today, those observations are only visible to maintainers because they are collapsed behind the `<details>` block.

### Problem

When the triage agent produces useful, reporter-relevant findings — for example "I reproduced this locally against commit abc123" or "The failing path is in `src/auth/middleware.py:42`" — those observations are placed inside the maintainer-only `<details>` section via the agent's `issue_body` markdown field. The visible section above the fold can currently only show one of:

- follow-up questions (`follow_up_questions`), or
- duplicate detection (`duplicate_of`).

Reporters therefore never see the agent's diagnostic conclusions unless a maintainer manually surfaces them. This hurts transparency and keeps reporters in the dark about the agent's actual findings, even when those findings are relevant enough to share immediately.

### Goals

- Allow the triage agent to share short, informational statements with the issue reporter in the visible part of the triage comment.
- Render statements alongside follow-up questions when both are present, with statements rendered first so the agent's conclusions precede its questions.
- Keep maintainer-only content (full `issue_body` triage summary, question reasoning, duplicate reasoning) unchanged in the `<details>` block.
- Preserve existing behavior when the agent does not produce statements (backward compatibility).

### Non-goals

- Removing or restructuring the existing `issue_body` maintainer summary. Statements are a new, focused surface, not a replacement for the full maintainer analysis.
- Changing duplicate-detection rendering. When duplicates are present, statements are not rendered above the fold (see "User experience" below).
- Changing how labels, reproducibility, or SME candidates are applied or rendered.
- Adding rich formatting primitives (tables, images, collapsible regions) inside statements.
- Changing the `triage_result.json` schema beyond adding the new optional `statements` field.

### Figma / design references

Figma: none provided. This is a workflow-level change that only affects the markdown content of an existing GitHub issue comment.

### User experience

#### Comment layout

The visible ("above the fold") portion of the triage comment is rendered in this order when statements and/or follow-up questions are present:

1. Session link preamble line (existing behavior).
2. Statements section (new), if `statements` is non-empty.
3. Follow-up questions section (existing), if `follow_up_questions` is non-empty and no duplicates were found.

The maintainer `<details>` block and trailing disclaimer remain at the bottom, unchanged.

When only statements are present (no follow-up questions, no duplicates), the visible section shows statements as the primary user-facing content.

When both statements and follow-up questions are present, statements render first, then the follow-up questions section.

When duplicates are present, duplicate detection continues to take precedence over follow-up questions. Statements are still rendered above the duplicate section when both are present, so the reporter sees the agent's findings before the overlap call-out. This preserves the existing duplicate-vs-follow-up mutual exclusivity while letting statements coexist with either.

#### Statements section content

The statements section is addressed to the reporter and contains a short paragraph introduction followed by a bulleted list of the agent's statements, in the order provided by the agent. Each statement is a single markdown string — it may include inline code, links, and file references (e.g. `` `src/auth/middleware.py:42` ``) but should remain concise (roughly one to two sentences each).

Example rendered output when the reporter login is `alice`:

```
@alice — here's what I found while triaging this issue:

- I was able to reproduce this locally against commit abc123.
- The failing path is in `src/auth/middleware.py:42`.
```

When the reporter login is unavailable, the intro line omits the mention but keeps the same structure.

If statements are present alongside follow-up questions, the combined visible section reads:

```
@alice — here's what I found while triaging this issue:

- I was able to reproduce this locally against commit abc123.
- The failing path is in `src/auth/middleware.py:42`.

@alice — I have a few follow-up questions before I can narrow this down:

1. …
2. …

Reply in-thread with those details and the triage workflow will automatically re-evaluate the issue and update the diagnosis, labels, and next steps.
```

#### Behavior rules and invariants

- `statements` is an optional array of plain markdown strings in `triage_result.json`. When it is missing, null, or empty, the visible comment is identical to today's behavior.
- Empty, whitespace-only, or duplicate statement strings are filtered out before rendering. If every statement is invalid, the statements section is omitted.
- Statements are rendered literally as markdown. They must not be mutated or reformatted beyond trimming surrounding whitespace.
- Statements never appear inside the maintainer `<details>` block. They are strictly above the fold.
- The full `issue_body` triage summary and the existing maintainer-only reasoning sections continue to live in the `<details>` block. Statements are additive, not a replacement for `issue_body`.
- The existing triage disclaimer continues to appear exactly once, at the bottom of the comment.
- When duplicates are present, statements still render above the duplicates section if the agent provides any. Follow-up questions remain suppressed in the duplicate case (existing behavior).

#### Prompt guidance

The triage prompt in `build_triage_prompt` instructs the agent when to populate `statements` versus `follow_up_questions`:

- `statements` are concise, reporter-facing findings worth sharing immediately: root-cause conclusions, repro confirmation, relevant file or line pointers, or environment-specific explanations.
- `follow_up_questions` remain focused on information only the reporter can provide.
- `statements` are not a substitute for `issue_body`; they are a short, filtered view of what is most useful for the reporter to see up front.
- The agent should prefer empty `statements` over speculative or low-confidence findings.

#### Backward compatibility

- When `statements` is absent, null, or empty, the rendered comment is byte-identical to the pre-change output.
- Existing `triage_result.json` payloads without a `statements` key remain valid.
- Existing unit and integration tests continue to pass without modification to assertions that are unrelated to the new section.

### Success criteria

1. `triage_result.json` accepts an optional `statements: list[str]` field. Results without `statements` still validate and render as today.
2. The triage comment's visible section renders statements above follow-up questions when both are present.
3. When only `statements` is populated, the visible section shows the statements block and omits the follow-up questions block.
4. When neither `statements` nor `follow_up_questions` is populated (and no duplicates are detected), the visible section falls back to the existing "finished triaging" preamble.
5. Statements render as a bulleted markdown list addressed to the reporter, with an `@reporter` mention when the reporter login is known.
6. Empty, whitespace-only, and duplicate statement strings are filtered out. If all statements are invalid, the section is omitted entirely.
7. Maintainer content in the `<details>` block is unchanged by this feature: `issue_body`, duplicate reasoning, and question reasoning continue to render exactly as before.
8. The triage disclaimer appears exactly once, at the bottom of the comment.
9. Duplicate detection continues to suppress follow-up questions. When duplicates are present, statements may still render above the duplicate section.
10. The prompt in `build_triage_prompt` instructs the agent on when to use `statements` vs. `follow_up_questions`, and the agent's output guide includes a `statements` field in the JSON schema.
11. Existing tests pass; new unit tests cover `extract_statements` and `build_statements_section`.

### Validation

- **Unit tests** covering:
  - `extract_statements` normalization: strips whitespace, filters empty/duplicate entries, returns `[]` for missing or non-list inputs.
  - `build_statements_section` rendering: includes reporter mention when present, omits it cleanly when absent, emits bulleted markdown, and preserves markdown content in each entry.
  - Comment layout integration (analogous to the existing `MutualExclusivityTest`): verifies that statements render before follow-up questions, that duplicates still suppress follow-up questions, and that the maintainer `<details>` block is unchanged.
- **Backward compatibility regression**: a `triage_result.json` payload without a `statements` field produces the same rendered comment as before.
- **Manual validation**: trigger a triage run on a test issue where the agent produces both statements and follow-up questions; confirm the reporter-facing section shows statements first, followed by the follow-up questions and existing reply-in-thread guidance.

### Open questions

- None. Behavior, ordering, and backward compatibility are defined above. Any future changes (e.g. allowing statements alongside duplicate detection in a different visual treatment, or formatting statements as prose rather than bullets) are out of scope for this spec.
