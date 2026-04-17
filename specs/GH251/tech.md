# Issue #251: Pull repo-tunable state out of core agents into repo-specific skills for self-improvement loops

## Tech Spec

### Problem

The reusable agent skills and the `update-pr-review` self-improvement loop in this repo conflate a stable cross-repo contract with repo-specific preferences. We need a concrete implementation plan that:

- moves repo-specific guidance out of the core skill bodies and out of `.github/scripts/*` conditionals into a repo-local skill layer
- extends the prompt-construction layer to include that repo-local layer as additional context at runtime
- narrows the write surface of `update-pr-review` to only the repo-local layer
- introduces an analogous `update-triage` self-improvement loop
- documents the pattern in `docs/platform.md` so other repos can adopt it

This spec translates the product spec at `specs/GH251/product.md` into file-level changes against the current codebase.

### Relevant code

Core skill files that currently mix contract and repo-specific guidance:

- `.agents/skills/review-pr/SKILL.md` — contains user-facing-string norms, graceful-degradation rules, debugging/observability rules that are Warp/Oz-specific rather than universal.
- `.agents/skills/review-spec/SKILL.md` — contains spec-section expectations that reflect this repo's `specs/GH<n>/` convention.
- `.agents/skills/triage-issue/SKILL.md` — contains the issue-shape taxonomy and follow-up patterns that are Warp-specific (for example the `area:keyboard-layout` guidance and the list of "environment-sensitive bugs" patterns).
- `.agents/skills/dedupe-issue/SKILL.md` — the core dedupe algorithm is generic, but repeated known-duplicate clusters are inherently repo-specific.
- `.agents/skills/update-pr-review/SKILL.md` and `.agents/skills/update-pr-review/scripts/aggregate_review_feedback.py` — today assume they can rewrite the core review skill bodies.

Prompt-construction entrypoints that currently assemble agent prompts:

- `.github/scripts/review_pr.py (285-389)` — assembles the review prompt and currently adds no repo-local skill context.
- `.github/scripts/triage_new_issues.py (55-79)` — `triage_heuristics_prompt(owner, repo)` hardcodes `warpdotdev/Warp` guidance in Python; this is the most explicit existing example of repo-tunable state living in the wrong layer.
- `.github/scripts/triage_new_issues.py (82-91)` — `fetch_command_signatures_context()` similarly hardcodes `warpdotdev/Warp`.
- `.github/scripts/triage_new_issues.py (229-340)` — the `process_issue()` prompt body, where a new repo-local section would be added.
- `.github/scripts/create_spec_from_issue.py`, `.github/scripts/create_implementation_from_issue.py`, `.github/scripts/respond_to_pr_comment.py`, `.github/scripts/respond_to_triaged_issue_comment.py` — will later benefit from the same pattern but are out of scope for the first migration except where trivially touched.
- `.github/scripts/update_pr_review.py` — currently tells the self-improvement loop to write to `.agents/skills/review-pr/SKILL.md` and `.agents/skills/review-spec/SKILL.md`; that prompt text needs to change.

Repo-specific state already separated from core skills (stays as-is):

- `.github/issue-triage/config.json`
- `.github/STAKEHOLDERS`
- `specs/GH*/`

Workflow wrappers that remain unchanged at the integration boundary:

- `.github/workflows/review-pull-request.yml`
- `.github/workflows/triage-new-issues.yml`
- `.github/workflows/update-pr-review.yml`
- `.github/workflows/update-pr-review-local.yml`

### Current state

Core skills hold a mix of universal contract and Warp/Oz-specific preferences. For example `triage-issue/SKILL.md (34-48)` enumerates issue-shape follow-up patterns that assume Warp's product surface area, and `review-pr/SKILL.md (27-41)` encodes Oz-specific user-facing-string norms (for example the phrasing rules around "The triage concluded that {summary}").

`triage_heuristics_prompt(owner, repo)` in `.github/scripts/triage_new_issues.py (55-79)` branches explicitly on `owner == "warpdotdev" and repo == "Warp"` and returns different prompt text. That is the single clearest signal that a repo-local layer is already needed; it just lives in Python today.

`update_pr_review.py` calls the agent with a prompt that names the core skill files directly as write targets, and `aggregate_review_feedback.py` lives inside `.agents/skills/update-pr-review/scripts/` and has no notion of a "repo-local" write surface.

Triage has no self-improvement loop; maintainer re-labels and overrides are not captured as learning signal.

`docs/platform.md (99-106)` documents the self-improvement agent but in terms of rewriting the core skills; the document needs to be updated once the pattern changes.

### Proposed changes

#### 1. Introduce a repo-local skill layer

Create new companion skills, each with YAML frontmatter and Markdown body:

- `.agents/skills/review-pr-local/SKILL.md`
- `.agents/skills/review-spec-local/SKILL.md`
- `.agents/skills/triage-issue-local/SKILL.md`
- `.agents/skills/dedupe-issue-local/SKILL.md`

Each companion file's frontmatter declares the core skill it specializes, for example:

```yaml
---
name: review-pr-local
specializes: review-pr
description: Repo-specific review guidance for oz-for-oss. Only the categories declared overridable by the core review-pr skill may be specialized here.
---
```

Move only the repo-specific rules out of the core skills and out of `triage_heuristics_prompt()` into the corresponding companion files. Specifically:

- `review-pr-local`: user-facing-string norms (section "User-facing strings"), graceful-degradation rules, debugging/observability rules currently in `review-pr/SKILL.md`.
- `review-spec-local`: repo-specific spec-section expectations and links to `specs/GH*/` conventions currently in `review-spec/SKILL.md`.
- `triage-issue-local`: the Warp-specific block from `triage_heuristics_prompt(owner, repo)` plus the `area:keyboard-layout` guidance and the issue-shape patterns from `triage-issue/SKILL.md`.
- `dedupe-issue-local`: seeded empty with a "no rules yet" body; gets populated over time by a future `update-dedupe` loop or by a reviewer.

Each core skill gets a short "Repository-specific overrides" section that explicitly enumerates the override categories the companion may specialize (for example "label taxonomy", "recurring follow-up patterns", "user-facing-string norms"). Categories not listed there are non-overridable.

#### 2. Shared helper for loading the repo-local layer

Add a new helper in `.github/scripts/oz_workflows/helpers.py` (or a new `repo_local.py` module next to it) with this shape:

```python
def load_repo_local_skill(workspace: Path, core_skill_name: str) -> str | None:
    """Load the repo-local companion skill body for a core skill.

    Returns the full Markdown body (including frontmatter) when the file
    exists and contains non-frontmatter content; otherwise returns None.
    """
```

- The helper resolves `.agents/skills/<core_skill_name>-local/SKILL.md` relative to `workspace`.
- Missing file → returns `None`.
- File exists but has only YAML frontmatter or is otherwise empty → returns `None` so the prompt section is silently omitted.
- File exists with content → returns the full body. The prompt builder is responsible for fencing it with a clearly labeled section header.

Expose a second helper that wraps the text in the canonical fenced section:

```python
def format_repo_local_prompt_section(core_skill_name: str, body: str) -> str:
    return (
        f"## Repository-specific guidance for `{core_skill_name}`\n"
        "The following repository-specific guidance may override only the "
        "categories your core skill marks as overridable. It must not change "
        "the core skill's output schema, severity labels, or safety rules.\n\n"
        f"{body}"
    )
```

Add unit tests under `.github/scripts/tests/test_repo_local.py` covering:

- missing file returns `None`
- empty file returns `None`
- frontmatter-only file returns `None`
- file with body returns the full body
- `format_repo_local_prompt_section` produces the fenced section with the expected header

#### 3. Wire the prompt-construction layer

Update `.github/scripts/review_pr.py`:

- Call `load_repo_local_skill(workspace(), skill_name)` where `skill_name` is already computed at `.github/scripts/review_pr.py:335`.
- If non-None, append `format_repo_local_prompt_section(skill_name, body)` to the `prompt` string built at `.github/scripts/review_pr.py (351-389)`, placed after the existing "Spec Context" block but before the "Cloud Workflow Requirements" block.
- Keep the rest of the prompt byte-for-byte identical when the companion file is absent.

Update `.github/scripts/triage_new_issues.py`:

- Remove the Warp-specific branch from `triage_heuristics_prompt(owner, repo)` at `.github/scripts/triage_new_issues.py (55-79)`; keep the function returning only the generic rules as the default base.
- In `process_issue()` at `.github/scripts/triage_new_issues.py (229-340)`, read `load_repo_local_skill(workspace(), "triage-issue")` and `load_repo_local_skill(workspace(), "dedupe-issue")` once per run and pass them in as prompt context.
- Add the fenced section(s) to the prompt using `format_repo_local_prompt_section("triage-issue", triage_local)` and `format_repo_local_prompt_section("dedupe-issue", dedupe_local)` when present.
- Leave `fetch_command_signatures_context()` untouched in this change; it is a separate repo-specific concern that is already structured as external repo data rather than skill prose, and re-shaping it would expand scope.

Add/extend tests under `.github/scripts/tests/`:

- A new test for `review_pr.py` that patches `load_repo_local_skill` to confirm the prompt includes the fenced section when the helper returns content, and omits it when the helper returns `None`.
- A new test for `triage_new_issues.py` `process_issue()` prompt assembly asserting the same behavior for both the triage and dedupe companions.
- A regression test that loading the `triage-issue-local/SKILL.md` checked in for `oz-for-oss` produces the Warp-specific rules (byte-equivalent up to whitespace) that used to live in `triage_heuristics_prompt()`.

#### 4. Narrow the self-improvement write surface

Update `.agents/skills/update-pr-review/SKILL.md`:

- Replace references to `.agents/skills/review-pr/SKILL.md` / `review-spec/SKILL.md` with `.agents/skills/review-pr-local/SKILL.md` / `review-spec-local/SKILL.md`.
- Add an explicit "write surface" section that lists the only files the loop may write to and forbids touching core skill files or `.github/scripts/*`.

Update `.github/scripts/update_pr_review.py`:

- Update the dedented prompt to name the `-local` skill files as the write targets.
- Add a post-run guard (executed in this script, not in the agent) that validates the diff produced on `oz-agent/update-pr-review` before pushing. Reuse `subprocess.run(["git", "diff", "--name-only", ...])` and fail if any path is outside `.agents/skills/review-pr-local/`, `.agents/skills/review-spec-local/`, or `.github/issue-triage/`.

Add a new script `.github/scripts/update_triage.py` modeled on `update_pr_review.py`:

- Aggregation: add `.agents/skills/update-triage/scripts/aggregate_triage_feedback.py` that queries the GitHub API for signals relevant to triage (issues triaged in the last N days, subsequent label changes by maintainers, closes-as-duplicate, re-opens, follow-up comments). Output a temp JSON payload analogous to `aggregate_review_feedback.py`.
- Prompt: instruct the `update-triage` skill to propose minimum-viable edits to `.agents/skills/triage-issue-local/SKILL.md` and/or `.agents/skills/dedupe-issue-local/SKILL.md`, and to update `.github/issue-triage/config.json` only when a label taxonomy change is warranted.
- Branch/PR: branch `oz-agent/update-triage`, tag `@captainsafia` for review, reuse the same app-token and Oz-agent plumbing as `update_pr_review.py`.
- Write-surface guard: same diff-based check as `update_pr_review.py`.

Add new skill `.agents/skills/update-triage/SKILL.md` and bundled aggregation script, following the shape of `.agents/skills/update-pr-review/`.

Add new workflow wrappers:

- `.github/workflows/update-triage.yml`: reusable wrapper modeled on `update-pr-review.yml`.
- `.github/workflows/update-triage-local.yml`: weekly schedule + workflow_dispatch, modeled on `update-pr-review-local.yml`.

#### 5. Bootstrap behavior

Extend `.agents/skills/bootstrap-issue-config/SKILL.md`:

- When bootstrapping a new consumer repository, scaffold empty `<agent>-local/SKILL.md` files for `review-pr`, `review-spec`, `triage-issue`, and `dedupe-issue` with only the frontmatter block and a short "no rules yet" body. This is the minimum that lets the prompt-construction layer and self-improvement loops treat the files as absent until a real rule lands.
- The exact content of the scaffold should mirror the companion files checked into this repo.

#### 6. Documentation

Update `docs/platform.md`:

- Add a new section "Core skills and repo-local companions" that explains the split, lists the four initial companion skills, and describes the fenced prompt section convention.
- Update the "Self-improvement agent" section so it describes `update-pr-review` as writing only to `review-pr-local` / `review-spec-local`, and introduce the new `update-triage` role.
- Update the final summary sentence to mention the self-improvement roles in the plural.

### End-to-end flow

For a PR review run with repo-local guidance present:

1. `review-pull-request.yml` fires on PR event.
2. `review_pr.py` resolves `skill_name` (`review-pr` or `review-spec`) at `.github/scripts/review_pr.py:335`.
3. `review_pr.py` calls `load_repo_local_skill(workspace(), skill_name)`; returns body or `None`.
4. `review_pr.py` appends a fenced "Repository-specific guidance" section to the prompt if non-None.
5. Oz runs the core `review-pr` (or `review-spec`) skill, treats the fenced section as additional allowed-override context, and produces `review.json`.
6. `review_pr.py` posts the review to GitHub as before.

For a self-improvement run after the migration:

1. `update-triage-local.yml` fires weekly.
2. `update_triage.py` runs `aggregate_triage_feedback.py`, gets a JSON payload in `/tmp`.
3. `update_triage.py` invokes Oz with the `update-triage` skill, pointing it at `.agents/skills/triage-issue-local/SKILL.md` and `.agents/skills/dedupe-issue-local/SKILL.md` as its only write targets.
4. Oz proposes minimal evidence-backed edits to those companion files (and optionally `.github/issue-triage/config.json`).
5. `update_triage.py` enforces the write-surface guard before pushing; a diff outside the allowed prefix aborts the run.
6. Branch `oz-agent/update-triage` is pushed and a PR is opened tagging `@captainsafia`.

For a repo with no companion files yet:

1. The helper returns `None` for every companion.
2. No fenced section is added to the prompt.
3. Oz behaves exactly as if the split had not happened — core skill only.

### Risks and mitigations

- Regressing behavior because Warp-specific triage rules are no longer hardcoded in Python. Mitigation: seed `triage-issue-local/SKILL.md` in `oz-for-oss` with the exact text currently returned by `triage_heuristics_prompt()`, and add a regression test that compares the two on the `warpdotdev/oz-for-oss` workspace.
- Self-improvement loops silently expanding their write surface. Mitigation: a post-run diff guard in the Python entrypoint (not in the agent prompt). The guard fails the job if any path outside the allowed prefixes changes.
- Companion files drifting out of sync with what the core skill marks overridable. Mitigation: the core skill explicitly lists override categories, and the companion template includes section headers matching those categories. Reviewers can catch non-conforming companions during PR review.
- Prompt bloat if every companion file is large. Mitigation: the fenced section is always short because the self-improvement loop only adds evidence-backed minimal edits; the write-surface guard keeps growth linear with signal volume.
- Ambiguity about whether a companion file exists but is "effectively empty." Mitigation: the helper uses a strict check (non-frontmatter body length > 0 after trimming) and tests cover empty / frontmatter-only cases explicitly.
- The self-improvement loop running before the migration completes could regress because it still targets the old paths. Mitigation: land the migration and the `update_pr_review.py` prompt change in the same PR; disable the weekly schedule temporarily via `workflow_dispatch`-only until the PR is merged.

### Testing and validation

- New unit tests for the `load_repo_local_skill` and `format_repo_local_prompt_section` helpers, covering missing / empty / frontmatter-only / populated cases.
- Extended tests for `review_pr.py` prompt assembly and `triage_new_issues.py` `process_issue()` prompt assembly that patch the helper and assert the prompt includes/excludes the fenced section as expected.
- Regression test that loads `.agents/skills/triage-issue-local/SKILL.md` from the `oz-for-oss` workspace fixture and asserts the body matches the Warp-specific prose previously returned by `triage_heuristics_prompt()` (up to whitespace and ordering).
- Diff-guard test for `update_pr_review.py` and `update_triage.py` that simulates a proposed diff touching a core skill file and asserts the job fails.
- Manual validation via `workflow_dispatch`:
  - run `update-pr-review-local.yml` on a recent week's feedback and confirm the resulting PR diff is restricted to the repo-local skills
  - run `update-triage-local.yml` on a recent week and confirm the produced PR cites concrete issue/comment URLs
  - run `review-pull-request.yml` against a PR both with and without `review-pr-local/SKILL.md` present and compare the prompts
- `docs/platform.md` is updated and builds (it is plain Markdown, so this is a read-review step).

### Follow-ups

- Evaluate whether `review-pr-local` and `review-spec-local` can be collapsed into a single `review-local` companion consumed by both core skills. Track as a follow-up spec once we have usage data.
- Decide whether a dedicated `update-dedupe` self-improvement loop is worthwhile, or whether dedupe signals should fold into `update-triage`.
- Extend the pattern to `create-spec-from-issue`, `create-implementation-from-issue`, and `respond-to-*` entrypoints as those accumulate repo-specific prompt guidance.
- Consider introducing `update-implementation` after the implementation agent has accumulated enough reviewer signal to justify the loop.
- Investigate factoring `fetch_command_signatures_context()` into a similar "repo-local data source" abstraction; out of scope for this change.
