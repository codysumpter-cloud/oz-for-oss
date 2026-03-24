---
name: triage-issue
description: Triage a newly filed GitHub issue in this repository by analyzing the report, inspecting relevant code, estimating reproducibility, suggesting likely root cause and subject-matter experts, and returning structured triage output without mutating GitHub directly unless a cloud workflow explicitly requests a transport comment.
---

# Triage a GitHub issue

Analyze the assigned GitHub issue and produce a structured initial triage result for this repository.

## Inputs

Expect the prompt to include:

- issue number, title, description, labels, assignees, and creation time
- any issue comments gathered by the workflow
- the repository triage configuration JSON, including label taxonomy and stakeholder hints
- the repository issue template context, if any templates are present
- the original issue report extracted from the pre-triage body

## Workflow

1. Read the issue carefully and classify whether it is primarily a bug report, enhancement request, documentation issue, or needs more information.
2. Inspect only the most relevant code and docs needed to understand the report. Avoid broad, unfocused repository scans.
3. Infer the most likely related files and estimate reproducibility as `high`, `medium`, `low`, or `unknown`.
4. Look for a plausible root cause in the current codebase. If the evidence is weak, say so clearly and use low confidence.
5. Identify subject-matter experts by:
   - preferring explicit matches from the stakeholder config for the related files
   - falling back to recent contributors to the related files from git history when needed
   - using the configured default experts only when there is no stronger match
6. Choose a small, useful label set. Prefer labels from the provided config and avoid inventing new labels unless the prompt explicitly allows it.
7. If repository issue templates exist, pick the best matching template and rewrite the visible issue body to follow that structure as closely as the available information allows. When no template exists, produce a clean structured markdown issue body yourself.
8. Keep the visible issue body self-contained. Include triage findings directly in the body rather than relying on a separate comment.
9. Write `triage_result.json` with the exact structure required by the prompt. The `issue_body` value should be the full visible issue body only; do not include the preserved-original-report appendix because the workflow will add it automatically.
10. Validate `triage_result.json` with `jq` before finishing.

## Output expectations

- The result must be evidence-driven and conservative about uncertainty.
- When the issue is underspecified, prefer `needs-info` and `repro:unknown` over overconfident guesses.
- Preserve the user's original wording conceptually when rewriting the issue body, but improve the structure.
- Do not create commits, branches, pull requests, or durable GitHub comments by default.

## Cloud workflow mode

If the prompt says you are running in a cloud workflow:

- still perform the triage as above
- do not apply labels or edit the issue directly yourself
- after validating `triage_result.json`, return it exactly through the temporary transport comment format requested by the prompt
