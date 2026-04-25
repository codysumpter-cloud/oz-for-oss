# Issue #337: Fix PR-issue linking detection with a single canonical association standard

## Product Spec

### Summary

PR-to-issue association in this repo should follow one canonical standard everywhere. Today one path treats any `#123` mention as an associated issue, while another only recognizes a narrow set of verbs before `#123`. The result is the worst of both worlds: destructive workflows can mutate the wrong issue, and legitimate contributor PRs can be auto-closed as “unlinked.”

The new behavior should prefer authoritative GitHub-linked issue data when it is available, preserve Oz’s deterministic branch and spec-path conventions, and use a single shared fallback parser for a small, explicit set of softer contributor phrases such as `Addresses #123`.

### Problem

The repo currently has two opposite failure modes:

1. **Too broad for destructive workflows.** The `remove-stale-issue-labels-on-plan-approved.yml` workflow scans the PR body with `/#(\d+)/g`, so any incidental `#123` mention can be treated as the associated issue. If the wrong issue happens to exist, the workflow may remove `ready-to-spec` from that unrelated issue.
2. **Too narrow for contribution gating.** `ISSUE_PATTERN` in `.github/scripts/oz_workflows/helpers.py` only recognizes a small set of verbs such as `Closes` and `Fixes`. Common phrases like `Addresses #123`, `Related to #123`, `Part of #123`, and `Towards #123` are ignored, so legitimate contributor PRs can be treated as unlinked and auto-closed.

These failure modes are symptoms of the same product problem: the repo does not have a single, documented definition of what counts as an associated issue for a PR.

### Goals

- Define one canonical PR-to-issue association standard that all workflows use.
- Prefer authoritative, GitHub-native linked issue data when it is available instead of re-parsing freeform text in multiple places.
- Continue to recognize the repo’s deterministic Oz-managed conventions, such as `oz-agent/spec-issue-{N}` branches and `specs/GH{N}/...` paths.
- Preserve compatibility for common contributor phrases like `Addresses #123` through a single shared fallback parser so legitimate PRs are not auto-closed.
- Make ambiguity safe: workflows must not guess and must not mutate unrelated issues.

### Non-goals

- Redesigning the repo’s readiness policy (`ready-to-spec` and `ready-to-implement`).
- Treating any bare `#123` mention in prose, code snippets, or changelog text as a valid association.
- Supporting arbitrary freeform phrasing beyond the explicitly accepted fallback phrases.
- Using cross-repository linked issues to satisfy same-repository gating or label-removal workflows.
- Changing commit-message-based issue linking behavior. This work is scoped to PR association used by repo automation.

### Figma / design references

Figma: none provided. This is a workflow and automation change with no product UI beyond GitHub issue, PR, and label behavior.

### User experience

#### Scenario: spec PR mentions multiple issue numbers in its body

1. A spec PR is opened for issue `#337`.
2. The body includes the real association (`Closes #337`) but also mentions other issues such as `See #323` and `See #324`.
3. When `plan-approved` is added and the stale-label workflow runs, the system identifies the canonical associated issue rather than scanning every `#123` token.
4. `ready-to-spec` is removed only from `#337`.
5. No unrelated issue label is changed.

#### Scenario: contributor PR uses an official GitHub-linked issue

1. A contributor opens a PR and links issue `#123` using supported GitHub closing keywords or GitHub’s manual linked-issue UI.
2. The repo’s enforcement workflow reads the PR’s associated issue from GitHub-linked issue data.
3. If issue `#123` is marked `ready-to-implement`, the PR is treated as linked and is not auto-closed for missing issue association.

#### Scenario: contributor PR uses a soft phrase such as `Addresses #123`

1. A contributor opens a PR whose body says `Addresses #123`.
2. GitHub-linked issue data may not include that relationship.
3. The repo falls back to the shared parser and still recognizes `#123` as the associated issue because `Addresses` is part of the supported fallback phrase set.
4. If issue `#123` is marked `ready-to-implement`, the PR is treated as linked and is not auto-closed.

#### Scenario: PR body contains an incidental `#123` mention only

1. A PR body mentions `#123` inside prose, a code block, or a “see also” list without an accepted linking phrase and without a GitHub-native link.
2. The system does not treat that bare mention as an associated issue.
3. Destructive workflows make no issue mutation based on that mention.
4. Contribution gating continues to behave as if the PR is unlinked unless another supported association signal exists.

#### Scenario: multiple associated same-repository issues exist

1. A PR resolves to multiple same-repository associated issues via branch conventions, GitHub link data, or the fallback parser.
2. Workflows that require a single target issue to mutate state, such as stale-label removal, only proceed if one primary issue can be determined safely and deterministically.
3. If a single primary issue cannot be determined, the destructive workflow does nothing rather than guessing.
4. Contribution gating may still treat the PR as associated if at least one associated same-repository issue is marked `ready-to-implement`.

#### Behavior rules

1. **All PR association decisions use one shared standard.** The repo must not maintain separate “broad” and “narrow” linking rules in different workflows.
2. **Association prefers deterministic signals first.** For Oz-managed PRs, branch naming and changed spec paths remain valid high-confidence signals.
3. **GitHub-linked issue data is the primary PR-level source of truth.** When GitHub exposes linked issue data for the PR, repo automation should prefer that over ad hoc text parsing.
4. **Fallback text parsing is explicit and bounded.** If GitHub-linked issue data does not provide a usable association, the shared fallback parser may recognize a documented set of phrases such as `Closes`, `Fixes`, `Resolves`, `Implements`, `Addresses`, `Related to`, `Part of`, and `Towards`.
5. **Bare `#123` does not count.** A raw hash-number token without an accepted association signal is not treated as a linked issue.
6. **Cross-repository issues do not satisfy repo gating.** A PR linked to an issue in another repository may still be displayed as linked data, but oz-for-oss gating and label workflows only act on same-repository issues.
7. **Destructive workflows require a safe target.** Any workflow that removes or edits labels on an issue must act only when it can resolve a single safe target issue.
8. **Contribution gating optimizes for avoiding false auto-closures.** If at least one associated same-repository issue is `ready-to-implement`, the PR should not be auto-closed for missing issue association.

### Success criteria

1. The plan-approved stale-label workflow never removes `ready-to-spec` from an unrelated issue solely because that issue number appeared somewhere in the PR body.
2. The enforcement workflow recognizes PRs linked via GitHub-native linked issue data and does not auto-close them as “unlinked.”
3. The enforcement workflow recognizes the supported fallback phrases `Addresses #N`, `Related to #N`, `Part of #N`, and `Towards #N` when no authoritative GitHub link data is available.
4. A bare `#N` mention without a supported phrase or GitHub-native link is ignored consistently across workflows.
5. Two different code paths in the repo do not disagree about whether the same PR is associated with the same issue.
6. Destructive workflows no-op on ambiguous association rather than mutating the wrong issue.

### Validation

- Add unit tests for the canonical association resolver covering deterministic Oz signals, GitHub-linked issue data, fallback phrases, incidental bare `#N` mentions, and ambiguity handling.
- Add regression tests for the stale-label workflow path showing that unrelated issue references in a spec PR body do not cause the wrong issue label to be removed.
- Add regression tests for contributor PR enforcement showing that PRs using `Addresses #N`, `Related to #N`, `Part of #N`, and `Towards #N` are treated as linked when appropriate.
- Validate that cross-repository linked issues are ignored for oz-for-oss readiness gating and label mutation.
- Validate that existing branch-based and spec-path-based association for Oz-generated PRs continues to work unchanged.

### Open questions

1. Should the close comment for an unlinked contributor PR explicitly recommend GitHub’s manual linked-issue UI or official closing keywords as the preferred long-term syntax, even though the repo will continue to accept the fallback phrases for compatibility?
2. Should the repo surface when a PR was accepted through fallback parsing rather than authoritative GitHub-linked issue data, so maintainers can measure whether the fallback parser is still necessary over time?
