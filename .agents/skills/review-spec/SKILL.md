---
name: review-spec
description: Review a spec/plan pull request diff and write structured feedback to review.json for the workflow to publish. Use when reviewing a PR that only modifies files under specs/ and producing machine-readable review output instead of posting directly to GitHub.
---

# Review Spec Skill

Review a spec or plan pull request and write the output to `review.json`.

## Context

- The working directory is the PR branch checkout.
- The workflow usually provides an annotated diff in `pr_diff.txt`.
- The workflow usually provides the PR description in `pr_description.txt`.
- Focus on the spec files changed by this PR.
- Default behavior: do not post comments or reviews to GitHub directly. If the prompt explicitly says you are running in a cloud-environment workflow and asks you to return `review.json` through a temporary machine-readable transport comment, you may create that temporary transport comment only.

## Review Scope

- Evaluate specs for **completeness**: does the spec cover the full scope of the linked issue?
- Evaluate specs for **clarity**: are requirements, acceptance criteria, and constraints clearly stated and unambiguous?
- Evaluate specs for **feasibility**: are the proposed changes technically realistic given the repository's architecture?
- Evaluate specs for **issue alignment**: does the spec faithfully address the issue it is linked to, without significant scope creep or omissions?
- Evaluate specs for **internal consistency**: do different sections of the spec contradict each other?
- Flag missing sections that a spec should typically include (e.g. problem statement, proposed changes, open questions, follow-up items).
- Do not apply code-level review criteria such as security, error handling, or performance to spec prose.
- Include style or formatting comments only when they materially impair readability.

## Diff Line Annotations

The diff file uses these prefixes:

- `[OLD:n]` for deleted lines on the old side. Use `"LEFT"`.
- `[NEW:n]` for added lines on the new side. Use `"RIGHT"`.
- `[OLD:n,NEW:m]` for unchanged context. Use `"RIGHT"` with line `m`.

## Comment Requirements

Every comment body must start with one of these labels:

- `🚨 [CRITICAL]` for spec content that is contradictory, fundamentally incomplete, or would lead to a broken implementation.
- `⚠️ [IMPORTANT]` for missing details, ambiguous requirements, feasibility concerns, or significant scope gaps.
- `💡 [SUGGESTION]` for improvements to clarity, structure, or coverage that would strengthen the spec.
- `🧹 [NIT]` for minor wording or formatting issues only when the comment includes a concrete rewrite.

Write comments with these constraints:

- Be concise, direct, and actionable.
- Do not add compliments or hedging.
- Prefer single-line comments.
- Keep ranges to at most 10 lines.
- Restrict inline comments to valid changed lines in this PR.
- Only create file-level or inline comments for files that exist in this PR's diff.
- If the relevant file or line is not part of the diff, put the feedback in `summary` instead of `comments`.

## Suggestion Blocks

When proposing a rewrite of spec text, use:

```suggestion
<replacement text here>
```

Rules:

- Match the exact indentation of the original file.
- Include only replacement text.
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

- A high-level overview of the spec PR.
- Concerns about completeness, clarity, feasibility, or issue alignment.
- Issue counts in the format `Found: X critical, Y important, Z suggestions`.
- A final recommendation of `Approve`, `Approve with nits`, or `Request changes`.

## Final Checks

Before finishing:

- Validate `review.json` with `jq`.
- Fix invalid JSON if validation fails.
- Confirm line numbers match the annotated diff.
- Do not run `gh pr review`, `gh pr comment`, `gh api`, or any other command that posts to GitHub, unless the prompt explicitly instructs you to create a temporary machine-readable transport comment in cloud mode.

Your only output is the final `review.json`.

## Cloud workflow mode

If the prompt says you are in a cloud-environment workflow and the expected local context files are missing:

- Create `pr_description.txt` yourself from the PR body or GitHub metadata provided in the prompt.
- Fetch the PR branch and base branch, then generate `pr_diff.txt` yourself in the annotated format above before reviewing.
- Still produce `review.json`, validate it, and then return it exactly as the prompt requests.
