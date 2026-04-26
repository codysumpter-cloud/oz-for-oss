# Issue #333: Support agent statements in triage response alongside follow-up questions
## Product Spec
### Summary
The triage response comment should be able to render concise, reporter-facing informational statements directly in the visible section of the comment, ahead of follow-up questions when both are present. These statements should focus on findings the reporter can act on immediately, such as version guidance, settings/workaround hints, or environment-specific explanations.
### Problem
Today, reporter-relevant conclusions from triage live inside the maintainer-only `<details>` block via `issue_body`. Reporters therefore do not see useful findings unless a maintainer manually surfaces them, even when those findings are safe and helpful to share immediately.
### Goals
- Allow the triage agent to share short, reporter-facing findings above the fold.
- Render those findings before follow-up questions when both are present.
- Keep maintainer-only content (`issue_body`, duplicate reasoning, question reasoning) unchanged inside `<details>`.
- Preserve existing behavior when no statements are provided.
### Non-goals
- Replacing `issue_body` as the maintainer-facing summary.
- Changing duplicate-detection rendering beyond keeping duplicates mutually exclusive with statements and follow-up questions.
- Changing label application, SME selection, or reproducibility handling.
- Adding richer formatting primitives beyond markdown already supported in issue comments.
### User experience
#### Comment layout
The visible portion of the triage comment is rendered in this order:
1. Session-link preamble line.
2. Statements section, when `statements` is non-empty and no duplicates were found.
3. Follow-up questions section, when `follow_up_questions` is non-empty and no duplicates were found.
4. Duplicate section, when `duplicate_of` is non-empty.
When duplicates are present, the duplicate section is the only visible reporter-facing guidance. Statements and follow-up questions are both omitted above the fold in that case.
#### Statements section content
The statements section contains a short intro line addressed to the reporter followed by a single markdown string provided by the agent. That markdown string may be a short paragraph or a compact bulleted list, but it should stay concise and reporter-facing.
Example when the reporter login is `alice`:
```
@alice — here's what I found while triaging this issue:

This behavior appears to already be fixed in newer Warp releases, and the current code suggests it is limited to SSH-backed sessions. If you need a workaround in the meantime, check whether the relevant session setting is enabled.
```
If follow-up questions are also present, the statements section appears first and the existing follow-up block appears underneath it.
#### Behavior rules and invariants
- `statements` is an optional markdown string in `triage_result.json`.
- Missing, null, non-string, empty, or whitespace-only `statements` values are treated as absent.
- Surrounding whitespace is trimmed before rendering. Internal markdown content is preserved exactly.
- Statements never appear inside the maintainer `<details>` block.
- When duplicates are present, statements are suppressed from the visible section.
- The triage disclaimer still appears exactly once at the bottom of the comment.
### Prompt guidance
The triage prompt should instruct the agent to use `statements` for concise reporter-facing findings that are worth sharing immediately, such as:
- the behavior likely being fixed in a newer version,
- a relevant setting or workaround the reporter can try,
- the issue appearing limited to a particular environment based on the current code.
The prompt should also make clear that:
- `follow_up_questions` are only for information the reporter alone can provide,
- `statements` should stay empty when `duplicate_of` is populated,
- `statements` do not replace `issue_body`.
### Backward compatibility
- Payloads without `statements` continue to render exactly as they do today.
- Existing `triage_result.json` producers remain valid if they omit the new field.
### Success criteria
1. `triage_result.json` accepts an optional `statements: string` field.
2. Statements render above follow-up questions when both are present.
3. When only `statements` is populated, the visible section shows the statements block and omits follow-up questions.
4. When duplicates are present, both statements and follow-up questions are suppressed above the fold.
5. Statements render as a markdown block addressed to the reporter, with an `@reporter` mention when available.
6. Empty or whitespace-only statements are omitted after trimming.
7. Maintainer content in the `<details>` block remains unchanged.
8. The triage disclaimer appears exactly once at the bottom of the comment.
9. The prompt distinguishes `statements` from `follow_up_questions` and instructs the agent not to emit `statements` for duplicate cases.
10. Existing tests pass, and new unit tests cover `extract_statements`, `build_statements_section`, and visible comment layout behavior.
### Validation
- Unit tests for `extract_statements` normalization.
- Unit tests for `build_statements_section` rendering with and without a reporter login.
- Layout tests proving statements render before follow-up questions, duplicates suppress statements, and maintainer details remain unchanged.
- Regression coverage showing payloads without `statements` still render the old layout.
### Open questions
- None.
