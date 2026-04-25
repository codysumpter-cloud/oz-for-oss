# Issue #333: Support agent statements in triage response alongside follow-up questions
## Tech Spec
### Problem
The triage workflow in `.github/scripts/triage_new_issues.py` currently renders only follow-up questions or duplicate information above the fold. Reporter-facing findings from the agent remain trapped in `issue_body`, which is shown only inside the maintainer `<details>` block.
The workflow needs a new reporter-facing `statements` channel that:
- is represented as an optional markdown string in `triage_result.json`,
- renders above follow-up questions when both are present,
- is suppressed when duplicate matches are present,
- leaves maintainer-only sections unchanged.
### Relevant code
- `.github/scripts/triage_new_issues.py` — triage prompt assembly, result normalization, and comment rendering.
- `.github/scripts/tests/test_triage.py` — unit coverage for normalization helpers and visible comment layout.
### Proposed changes
#### 1. Add `extract_statements()`
Add a helper near `extract_follow_up_questions()`:
```python path=null start=null
def extract_statements(result: dict[str, Any]) -> str:
    raw = result.get("statements")
    if not isinstance(raw, str):
        return ""
    return raw.strip()
```
This keeps the host workflow simple and avoids concatenating a list of strings. Non-string inputs are treated as absent.
#### 2. Add `build_statements_section()`
Add a renderer near `build_follow_up_section()`:
```python path=null start=null
def build_statements_section(issue: Any, statements: str) -> str:
    reporter_login = get_login(get_field(issue, "user")).strip()
    lines: list[str] = []
    if reporter_login:
        lines.append(f"@{reporter_login} — here's what I found while triaging this issue:")
    else:
        lines.append("Here's what I found while triaging this issue:")
    lines.append("")
    lines.append(statements)
    return "
".join(lines)
```
The agent-provided markdown block is rendered directly so the agent can choose short prose or a compact list.
#### 3. Update `process_issue()` comment assembly
Normalize `statements` alongside follow-up questions and duplicates, then compute `show_statements = bool(statements and not duplicates)`. The visible comment body becomes:
1. session-link preamble,
2. statements when `show_statements` is true,
3. duplicate section when duplicates are present,
4. otherwise follow-up questions when present.
The fallback preamble is shown only when there is no visible content at all.
#### 4. Update `build_triage_prompt()`
Extend the JSON schema example with:
```text
"statements": "markdown string for reporter-facing findings, or empty string",
```
Add prompt guidance that:
- gives at least three examples of reporter-facing findings,
- distinguishes `statements` from `follow_up_questions`,
- instructs the agent to leave `statements` empty when `duplicate_of` is populated,
- keeps `issue_body` as the maintainer-facing summary.
#### 5. Update tests
Extend `.github/scripts/tests/test_triage.py` with:
- `ExtractStatementsTest` for trimming and invalid-input handling,
- `BuildStatementsSectionTest` for rendering and reporter mentions,
- `MutualExclusivityTest` coverage showing statements render before follow-up questions, duplicates suppress statements, and maintainer details remain unchanged.
### End-to-end flow
1. The triage agent emits `triage_result.json` with an optional `statements` string.
2. `process_issue()` normalizes `statements`, `follow_up_questions`, and `duplicate_of`.
3. The workflow renders statements above the fold only when there are no duplicates.
4. Maintainer details continue to come from `issue_body`, duplicate reasoning, and question reasoning.
### Risks and mitigations
- Over-sharing noisy findings: mitigated with prompt guidance that prefers an empty `statements` string over speculative content.
- Duplicate content between `statements` and `issue_body`: mitigated by explicitly framing `statements` as a short reporter-facing subset of the full summary.
- Backward compatibility: mitigated because missing or invalid `statements` values normalize to an empty string.
### Testing and validation
- Run the `test_triage.py` suite.
- Verify layout-specific tests for statements-only, statements-plus-follow-up, and duplicate suppression cases.
### Follow-ups
- Consider reusing the same reporter-facing statements surface in re-triage comment flows if that becomes valuable later.
