# Issue #333: Support agent statements in triage response alongside follow-up questions

## Tech Spec

### Problem

The triage workflow in `.github/scripts/triage_new_issues.py` renders a consolidated triage comment with an "above the fold" visible section and a collapsed maintainer `<details>` block. Today, only follow-up questions (`follow_up_questions`) or duplicate detection (`duplicate_of`) can populate the visible section. The agent's findings — placed into `issue_body` — are always hidden inside the maintainer block.

Per the product spec, the triage agent needs a new `statements` output channel whose contents render above the fold, ahead of follow-up questions when both are present. The implementation must:

- extend `triage_result.json` with an optional `statements: list[str]` field,
- add helpers analogous to the existing follow-up helpers (`extract_statements`, `build_statements_section`),
- wire the new section into `process_issue()`'s comment layout,
- update the prompt in `build_triage_prompt()` so the agent knows when to use `statements`,
- preserve behavior when `statements` is absent or empty.

### Relevant code

All paths below are under the repository root.

- `.github/scripts/triage_new_issues.py (181-338)` — `process_issue()` orchestrates triage and assembles the consolidated comment body.
- `.github/scripts/triage_new_issues.py (271-303)` — visible-section assembly logic: preamble, follow-up vs duplicate branch.
- `.github/scripts/triage_new_issues.py (304-334)` — maintainer `<details>` assembly and disclaimer.
- `.github/scripts/triage_new_issues.py (359-497)` — `build_triage_prompt()` and the JSON schema literal the agent must produce.
- `.github/scripts/triage_new_issues.py (586-609)` — `extract_follow_up_questions()` — the pattern the new extractor should mirror.
- `.github/scripts/triage_new_issues.py (683-704)` — `build_follow_up_section()` — the pattern the new renderer should mirror for above-the-fold content with an `@reporter` mention.
- `.github/scripts/triage_new_issues.py (707-729)` — `build_duplicate_section()` — additional reference for reporter-facing section styling.
- `.github/scripts/tests/test_triage.py (358-397)` — `ExtractFollowUpQuestionsTest` — structural template for `ExtractStatementsTest`.
- `.github/scripts/tests/test_triage.py (644-665)` — `BuildFollowUpSectionTest` — template for `BuildStatementsSectionTest`.
- `.github/scripts/tests/test_triage.py (853-975)` — `MutualExclusivityTest._build_comment_parts` — the simulation of `process_issue()`'s comment assembly that must be updated to mirror the new layout.

### Current state

`process_issue()` builds the comment in this order:

1. Session link preamble (one of two variants depending on whether follow-up questions or duplicates exist).
2. Above-the-fold content: `build_duplicate_section` when duplicates are present, else `build_follow_up_section` when follow-up questions are present, else neither.
3. Maintainer `<details>` block containing `I concluded that {summary}.`, `issue_body` (when no duplicates), duplicate reasoning (when duplicates), and question reasoning (when follow-up questions have reasoning).
4. `TRIAGE_DISCLAIMER`.

`build_triage_prompt()` embeds an explicit JSON schema literal for `triage_result.json` in the agent prompt. The schema currently lists `summary`, `labels`, `reproducibility`, `root_cause`, `sme_candidates`, `selected_template_path`, `issue_body`, `follow_up_questions`, and `duplicate_of`. Output-requirements bullets explain when to populate `follow_up_questions` and `duplicate_of`.

`extract_follow_up_questions()` and `build_follow_up_section()` provide a stable pattern for normalizing and rendering an above-the-fold section with an `@reporter` mention.

### Proposed changes

#### 1. Add `extract_statements()` in `triage_new_issues.py`

Add a helper adjacent to `extract_follow_up_questions()`:

```python path=null start=null
def extract_statements(result: dict[str, Any]) -> list[str]:
    """Normalize reporter-facing statements from a triage result payload.

    Returns a list of trimmed, non-empty markdown strings in the order the
    agent provided them. Duplicate entries are removed, preserving the
    first occurrence. Returns an empty list when the field is missing,
    null, or not a list of strings.
    """
    raw = result.get("statements")
    if not isinstance(raw, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            continue
        trimmed = entry.strip()
        if not trimmed or trimmed in seen:
            continue
        seen.add(trimmed)
        normalized.append(trimmed)
    return normalized
```

Design notes:

- Input is tolerated as plain strings only, matching the product spec's "plain-markdown strings" description. Non-string entries are silently skipped to avoid crashing the workflow on a malformed agent response.
- Deduplication on the trimmed value mirrors how `extract_follow_up_questions()` handles repeated entries.
- No HTML stripping or markdown parsing is performed. Statements are rendered as-is, consistent with how `issue_body` markdown is embedded today.

#### 2. Add `build_statements_section()` in `triage_new_issues.py`

Add a renderer adjacent to `build_follow_up_section()`:

```python path=null start=null
def build_statements_section(issue: Any, statements: list[str]) -> str:
    """Build the reporter-facing statements section for the consolidated
    triage comment. *statements* must already be normalized by
    ``extract_statements``.
    """
    reporter_login = get_login(get_field(issue, "user")).strip()
    lines: list[str] = []
    if reporter_login:
        lines.append(f"@{reporter_login} — here's what I found while triaging this issue:")
    else:
        lines.append("Here's what I found while triaging this issue:")
    lines.append("")
    lines.extend(f"- {statement}" for statement in statements)
    return "\n".join(lines)
```

Design notes:

- Uses the same `get_login`/`get_field` helpers as `build_follow_up_section()` so it behaves consistently on both real GitHub objects and the `FakeTriageGitHubClient` used in tests.
- Emits a bulleted markdown list. Statements retain their own inline markdown (code spans, links, file references).
- Does not emit a trailing blank line; block separation is handled at the `process_issue()` join step (same pattern as other section helpers).

#### 3. Update `process_issue()` comment assembly

Change the visible-section block in `process_issue()` to include statements. The rendering order inside the `parts` list becomes:

1. Session link preamble (unchanged logic, with one small update: `statements` should count as "has visible content" alongside follow-up questions and duplicates when deciding which preamble to emit — see below).
2. Statements section (new), when `statements` is non-empty.
3. Duplicate section (unchanged), when duplicates are present.
4. Follow-up section (unchanged), when follow-up questions are present and no duplicates.

Concretely, add an `extract_statements` call and update the preamble branch so the "I've finished triaging this issue." fallback is only used when **none** of `statements`, `follow_up_questions`, or `duplicates` are present:

```python path=null start=null
follow_up_questions = extract_follow_up_questions(result)
duplicates = extract_duplicate_of(result, current_issue_number=issue_number)
statements = extract_statements(result)

parts: list[str] = []
has_visible_content = bool(statements or follow_up_questions or duplicates)

if not has_visible_content:
    if session_link:
        link_text = _format_triage_session_link(session_link)
        parts.append(
            "I've finished triaging this issue. "
            "A maintainer will verify the details shortly. "
            f"You can view {link_text}."
        )
    else:
        parts.append("I've completed the triage of this issue.")
elif session_link:
    link_text = _format_triage_session_link(session_link)
    parts.append(f"You can view {link_text}.")

if statements:
    parts.append(build_statements_section(issue, statements))

if duplicates:
    parts.append(build_duplicate_section(issue, duplicates))
elif follow_up_questions:
    parts.append(build_follow_up_section(issue, follow_up_questions))
```

The maintainer `<details>` assembly is unchanged. The trailing disclaimer is unchanged.

This places statements above both the duplicate section and the follow-up questions section, matching the product spec's ordering rule.

Note: statements intentionally do not add a new entry to the maintainer section. They are reporter-facing only; the full maintainer summary continues to come from `issue_body`.

#### 4. Extend the triage prompt in `build_triage_prompt()`

Two changes to the prompt string:

- Add a `statements` field to the JSON schema literal:

```text
"statements": ["short markdown string", "another short markdown string"],
```

- Add output-requirements bullets that explain when to populate `statements`:

```text
- When the triage surfaces concise, reporter-facing findings that are worth sharing immediately (e.g., "I reproduced this against commit abc123", "The failing path is in `src/auth/middleware.py:42`"), include them in the `statements` array. Keep each statement to one or two sentences of plain markdown. Leave the array empty when there are no high-confidence findings worth surfacing above the fold.
- Use `statements` for agent conclusions that inform the reporter. Use `follow_up_questions` only for information the reporter alone can provide. Do not duplicate the same content across both.
- `statements` does not replace `issue_body`. Continue populating `issue_body` with the full maintainer-facing markdown summary; `statements` is a short, filtered view for the reporter.
```

Schema validation via `jq` continues to work because the new field is an array of strings and optional.

#### 5. Update `MutualExclusivityTest._build_comment_parts` to mirror the new layout

The simulation in the existing integration-style test must learn about `statements` so it continues to validate the full comment assembly. Add:

```python path=null start=null
statements = extract_statements(result)
...
if statements:
    parts.append(build_statements_section(issue, statements))
```

Adjust the fallback preamble condition to the new "none of statements/follow-ups/duplicates" rule. This is a purely additive change; pre-existing tests inside `MutualExclusivityTest` continue to pass because they construct `result` dicts without a `statements` key.

#### 6. Add unit tests

Add three new test classes in `.github/scripts/tests/test_triage.py`:

- `ExtractStatementsTest` — table-driven, mirrors `ExtractFollowUpQuestionsTest`. Cases:
  - returns normalized list for valid input,
  - strips whitespace,
  - deduplicates entries on trimmed value (order preserved by first occurrence),
  - ignores empty/whitespace-only entries,
  - ignores non-string entries,
  - returns `[]` for missing key, `None`, or non-list values.
- `BuildStatementsSectionTest` — mirrors `BuildFollowUpSectionTest`. Cases:
  - includes `@reporter` mention when reporter login is present,
  - omits `@` mention when reporter login is empty,
  - renders each statement as a bullet in order,
  - preserves inline markdown content (e.g. backticks in file references).
- Extension of `MutualExclusivityTest` (or a new `StatementsLayoutTest`): verifies, using `_build_comment_parts`,
  - statements render before follow-up questions when both are present,
  - statements render before the duplicate section when both are present,
  - the statements section is absent when `statements` is missing or empty,
  - the fallback "I've completed the triage of this issue." preamble only appears when `statements`, `follow_up_questions`, and `duplicate_of` are all empty,
  - the maintainer `<details>` block is unchanged by the presence or absence of `statements`.

All new tests use the existing `FakeTriageGitHubClient`/dict-based issue fixtures that the rest of the suite already relies on.

#### 7. Export new helpers from the module

The new helpers (`extract_statements`, `build_statements_section`) must be importable from `triage_new_issues` the same way `extract_follow_up_questions` and `build_follow_up_section` are, since the test module imports them directly from the script (`from triage_new_issues import ...`). No additional plumbing is needed beyond defining them at module scope.

### End-to-end flow

1. The triage agent reads the updated prompt and produces `triage_result.json` that may include a `statements` array.
2. The host workflow receives the JSON, calls `process_issue()`.
3. `process_issue()` calls `extract_statements`, `extract_follow_up_questions`, and `extract_duplicate_of` to normalize the result.
4. The visible comment body is assembled in order: session-link preamble → statements (if any) → duplicates or follow-ups (existing mutual exclusivity) → maintainer `<details>` → disclaimer.
5. `progress.replace_body(...)` publishes the consolidated comment. The reporter now sees the statements list directly, followed by any follow-up questions when present.
6. When `statements` is absent or empty, the comment body is identical to the pre-change output.

### Risks and mitigations

- **Agent over-sharing.** The agent might push speculative or noisy findings into `statements`, creating visual clutter for reporters. Mitigation: explicit prompt guidance instructing the agent to prefer an empty `statements` array over low-confidence findings; reviewers can tune prompt wording if early results are noisy.
- **Duplicate content between `statements` and `issue_body`.** The agent might repeat the same sentence in both. Mitigation: the prompt explicitly tells the agent that `statements` is a short, filtered view of `issue_body`, not a replacement. Dedup within statements handles at least the trivial case within the same array.
- **Markdown injection risk.** Statements render raw markdown. This is consistent with how `issue_body` already renders. GitHub renders comment markdown with the same safety characteristics regardless of source, so no additional sanitization is introduced (matching existing behavior).
- **Backward compatibility.** Old `triage_result.json` payloads without `statements` must continue to render identically. Mitigation: `extract_statements` returns `[]` for missing keys; the `parts` construction falls through to the original logic when `statements` is empty.
- **Schema drift.** The new optional field is additive and does not affect `jq` validation. Existing consumers of `triage_result.json` that ignore unknown fields remain unaffected.
- **Test simulation drift.** `MutualExclusivityTest._build_comment_parts` duplicates the real `process_issue()` assembly. If only the real code path is updated without updating the simulation, the existing tests will silently pass even if new regressions exist around `statements`. Mitigation: the simulation is updated in the same change as `process_issue()`, and new tests exercise the simulation's statements path directly.

### Testing and validation

- Unit tests described in "Proposed changes" §6 must pass locally via the existing `python -m unittest` flow that the `.github/scripts/tests/` suite uses.
- Regression: run the full `test_triage.py` suite with no `statements` present in any result fixture to confirm the default comment layout is byte-identical to the current output for those tests.
- Manual validation (optional, behind a test issue): run the triage workflow on a synthetic issue where the agent is coached to return both `statements` and `follow_up_questions`, and confirm the rendered comment matches the product spec's example layout.

### Follow-ups

- Consider surfacing `statements` in `respond_to_triaged_issue_comment` responses as well, so re-triage comments can update both the visible findings and follow-up questions consistently. This is out of scope for the initial change.
- Consider allowing the maintainer `<details>` block to optionally mirror the statements list when `issue_body` is empty, as a fallback for agents that populate only `statements`. Out of scope for the initial change; `issue_body` coverage is expected today.
- Evaluate whether statements should carry optional metadata (confidence, category) in a future schema version. This is deliberately excluded from this change to keep the surface area minimal and fully backward compatible.
