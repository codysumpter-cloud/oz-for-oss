---
name: review-pr
description: Review a pull request diff and write structured feedback to review.json for the workflow to publish. Use when reviewing a checked-out PR from local artifacts like pr_diff.txt and pr_description.txt and producing machine-readable review output instead of posting directly to GitHub.
---

# Review PR Skill

Review the current pull request and write the output to `review.json`.

## Context

- The working directory is the PR branch checkout.
- The workflow usually provides an annotated diff in `pr_diff.txt`.
- The workflow usually provides the PR description in `pr_description.txt`.
- If `spec_context.md` exists, it contains spec context for implementation-vs-spec validation.
- Focus on files and lines changed by this PR.
- Default behavior: do not post comments or reviews to GitHub directly.

## Review Scope

- Prioritize correctness, security, error handling, and meaningful performance issues.
- When `spec_context.md` exists, use the repository's local `check-impl-against-spec` skill and treat material spec drift as a review concern.
- Include style or nit comments only when you can provide a concrete suggestion block.
- If a concern involves untouched code, mention it in the summary instead of an inline comment.

### User-facing strings

- Flag interpolated text that would read unnaturally at runtime (e.g. wrong casing after a sentence fragment like "The triage concluded that {summary}").
- Link text should be descriptive (e.g. "triage session on Warp"), not bare URLs or generic "click here" labels.
- Verify that terminology is consistent across related messages in the same PR.

### Graceful degradation

- When code renders optional dynamic data (URLs, session links, metadata), flag cases where a missing value would produce empty or broken output. The fix is usually to omit the element entirely and show a short fallback message.
- Prefer starting with generic, user-safe error messages over exposing internal details.

### Debugging and observability

- Do not suggest removing session links, workflow URLs, or other debugging context from error paths. These are valuable for post-incident investigation even when the operation failed.

## Diff Line Annotations

The diff file uses these prefixes:

- `[OLD:n]` for deleted lines on the old side. Use `"LEFT"`.
- `[NEW:n]` for added lines on the new side. Use `"RIGHT"`.
- `[OLD:n,NEW:m]` for unchanged context. Use `"RIGHT"` with line `m`.

## Comment Requirements

Every comment body must start with one of these labels:

- `🚨 [CRITICAL]` for bugs, security issues, crashes, or data loss.
- `⚠️ [IMPORTANT]` for logic problems, edge cases, or missing error handling.
- `💡 [SUGGESTION]` for worthwhile improvements or better patterns.
- `🧹 [NIT]` for cleanup only when the comment includes a suggestion block.

Write comments with these constraints:

- Be concise, direct, and actionable.
- Do not add compliments or hedging.
- Prefer single-line comments.
- Keep ranges to at most 10 lines.
- Restrict inline comments to valid changed lines in this PR.
- Only create file-level or inline comments for files that exist in this PR's diff.
- If the relevant file or line is not part of the diff, put the feedback in `summary` instead of `comments`.

## Suggestion Blocks

When proposing a code change, use:

```suggestion
<replacement code here>
```

Rules:

- Match the exact indentation of the original file.
- Include only replacement code.
- For multi-line suggestions, set `start_line` to the first line and `line` to the last line.

## Output Format

Create `review.json` with this shape:

```json
{
  "summary": "## Overview\n...\n\n## Concerns\n- ...\n\n## Verdict\nFound: 1 critical, 2 important, 3 suggestions\n\n**Request changes**",
  "comments": [
    {
      "path": "path/to/file",
      "line": 42,
      "side": "RIGHT",
      "start_line": 40,
      "body": "⚠️ [IMPORTANT] Short explanation\n\n```suggestion\nreplacement\n```"
    }
  ]
}
```

Field rules:

- `path` must be relative to the repository root.
- `line` is required and must target the correct side.
- `start_line` is optional and only for multi-line ranges.
- `side` must be `"LEFT"` or `"RIGHT"`.

## Summary Requirements

The `summary` must include:

- A high-level overview of the PR.
- Important concerns and any untouched-code concerns that could not be commented inline.
- Issue counts in the format `Found: X critical, Y important, Z suggestions`.
- A final recommendation of `Approve`, `Approve with nits`, or `Request changes`.

## Final Checks

Before finishing:

- Validate `review.json` with `jq`.
- Fix invalid JSON if validation fails.
- Confirm line numbers match the annotated diff.
- Do not run `gh pr review`, `gh pr comment`, `gh api`, or any other command that posts to GitHub.

Your only output is the final `review.json`.

## Cloud workflow mode

If the prompt says you are in a cloud-environment workflow and the expected local context files are missing:

- Create `pr_description.txt` yourself from the PR body or GitHub metadata provided in the prompt.
- Fetch and check out the exact PR head branch by name before generating the diff. Run:
    ```
    git fetch origin <head_branch>
    git checkout <head_branch>
    ```
  Do NOT use `FETCH_HEAD` — always reference the named branch.
- Generate the diff against the base branch using a three-dot merge-base diff:
    ```
    git diff origin/<base_branch>...HEAD
    ```
  This isolates only the changes introduced by the PR, not accumulated state from other branches.
- Convert the raw diff into `pr_diff.txt` using the annotated format above before reviewing.
- If the prompt includes spec context to materialize, write it to `spec_context.md` before running the review.
- Still produce `review.json` and validate it with `jq`.
- After validation, upload the result via `oz-dev artifact upload review.json`.
- IMPORTANT: the upload command is `oz-dev artifact upload` (singular `artifact`). Do not use `artifacts` (plural) — that is not a valid subcommand and will fail.
