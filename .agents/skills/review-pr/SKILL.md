---
name: review-pr
description: Review a pull request and publish feedback directly on GitHub. Use when the prompt provides the repository and pull request context and the agent should inspect the PR using GitHub-aware tools, then post the review itself.
---

# Review PR Skill

Review the target pull request and publish the review directly on GitHub.

## Context

- The prompt provides the repository, pull request number, and any extra focus guidance.
- Use GitHub-aware tools available in the environment to inspect the pull request metadata, changed files, and diff.
- Focus on files and lines changed by this PR.
- Publish the review directly on GitHub instead of writing local output files.

## Review Scope

- Prioritize correctness, security, error handling, and meaningful performance issues.
- Include style or nit comments only when you can provide a concrete suggestion block.
- If a concern involves untouched code, mention it in the summary instead of an inline comment.

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

## Suggestion Blocks

When proposing a code change, use:

```suggestion
<replacement code here>
```

Rules:

- Match the exact indentation of the original file.
- Include only replacement code.
- For multi-line suggestions, ensure the suggestion matches the exact range you are replacing.

## Summary Requirements

The final review you publish must include:

- A high-level overview of the PR.
- Important concerns and any untouched-code concerns that could not be commented inline.
- Issue counts in the format `Found: X critical, Y important, Z suggestions`.
- A final recommendation of `Approve`, `Approve with nits`, or `Request changes`.

## Final Checks

Before finishing:

- Confirm any inline comment line numbers match the actual pull request diff.
- Publish exactly one coherent pull request review, with inline comments when warranted.
- Do not modify repository code, create branches, or open pull requests as part of the review.
