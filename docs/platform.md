# Platform workflows in `oz-for-oss`

`oz-for-oss` exposes its main automation surface through reusable GitHub Actions workflows in [`../.github/workflows/`](../.github/workflows/). Those reusable workflows are the platform boundary that other repositories, orchestration repos, or higher-level event routers can call with `workflow_call`.

This document focuses on that reusable surface first. The repository also contains local adapters such as [`triage-new-issues-local.yml`](../.github/workflows/triage-new-issues-local.yml) and [`pr-hooks.yml`](../.github/workflows/pr-hooks.yml), but those are examples of how this repo wires the reusable workflows into GitHub events, not the main integration contract.

## Integration model

Each reusable workflow typically has four layers:

1. A reusable workflow file in [`../.github/workflows/`](../.github/workflows/).
2. A Python entrypoint in [`../.github/scripts/`](../.github/scripts/).
3. Shared GitHub and Oz helpers in [`../.github/scripts/oz_workflows/`](../.github/scripts/oz_workflows/).
4. Repository-specific skills in [`../.agents/skills/`](../.agents/skills/) when the workflow actually invokes Oz.

From another system's point of view, the reusable workflows are the stable interface:

- call the workflow with the documented `workflow_call` inputs
- provide the required secrets and permissions
- map your source-system event into the right workflow invocation
- decide whether you want this repo to supply only the reusable workflow logic, or also a local adapter in the consuming repository

In practice, these workflows are best suited for:

- GitHub event adapters in another repository
- scheduled repository maintenance
- issue and PR governance bots
- external orchestration that wants GitHub to remain the source of truth for labels, assignees, comments, and pull requests

## Workflow categories

The reusable workflows in this repo fall into three buckets:

- **Agent-backed workflows**: always invoke Oz.
- **Conditionally agent-backed workflows**: may use Oz as part of policy enforcement, but not in every fast path.
- **Non-agent workflows**: pure scripted automation with no Oz invocation.

## Agent-backed reusable workflows

### Issue triage: [`triage-new-issues.yml`](../.github/workflows/triage-new-issues.yml)

**Implementation**

- Workflow: [`triage-new-issues.yml`](../.github/workflows/triage-new-issues.yml)
- Script: [`triage_new_issues.py`](../.github/scripts/triage_new_issues.py)
- Skills:
  - [`triage-issue`](../.agents/skills/triage-issue/SKILL.md)
  - [`dedupe-issue`](../.agents/skills/dedupe-issue/SKILL.md)
- Repository context:
  - [`config.json`](../.github/issue-triage/config.json)
  - [`STAKEHOLDERS`](../.github/STAKEHOLDERS)

**Inputs**

- `issue_number` for immediate single-issue triage
- `lookback_minutes` for batch scanning recent issues

**What it does**

- finds untriaged issues or triages one explicitly requested issue
- inspects issue comments, issue-template context, label taxonomy, and likely owners
- rewrites the visible issue body into a normalized structure
- sets and reconciles managed labels
- detects likely duplicates
- asks clarifying questions on the issue when the report is underspecified, usually through a managed follow-up comment
- re-triages after reporter follow-up when the issue is in a `needs-info` state

**Role in the OSS workflow**

This is the intake workflow. It does both the initial classification work and the first round of clarification work when more reporter input is required. In other words, the triage agent is responsible not just for labeling the issue, but also for asking the clarifying questions that unblock later spec or implementation work.

**How to integrate it elsewhere**

Use this workflow when another system wants GitHub issue state to become structured and actionable. A consuming repository can call it from:

- issue-opened events
- scheduled backfills
- explicit maintainer reruns
- reporter replies to prior clarification requests

### Triaged issue follow-up: [`respond-to-triaged-issue-comment.yml`](../.github/workflows/respond-to-triaged-issue-comment.yml)

**Implementation**

- Workflow: [`respond-to-triaged-issue-comment.yml`](../.github/workflows/respond-to-triaged-issue-comment.yml)
- Script: [`respond_to_triaged_issue_comment.py`](../.github/scripts/respond_to_triaged_issue_comment.py)
- Skill: [`triage-issue`](../.agents/skills/triage-issue/SKILL.md)

**What it does**

- reads the current issue body and visible discussion
- interprets an explicit `@oz-agent` mention on an already triaged issue
- posts a concise inline response without rewriting the issue body or changing labels

**Role in the OSS workflow**

This workflow handles narrow, targeted follow-up after triage but before the issue is ready for design or implementation. It is a lightweight analysis loop, not a full retriage pass.

**How to integrate it elsewhere**

Call this workflow when your system wants a “question-answering” path on issues that are already triaged but still under discussion.

### Spec creation: [`create-spec-from-issue.yml`](../.github/workflows/create-spec-from-issue.yml)

**Implementation**

- Workflow: [`create-spec-from-issue.yml`](../.github/workflows/create-spec-from-issue.yml)
- Script: [`create_spec_from_issue.py`](../.github/scripts/create_spec_from_issue.py)
- Skills:
  - [`spec-driven-implementation`](../.agents/skills/spec-driven-implementation/SKILL.md)
  - [`create-product-spec`](../.agents/skills/create-product-spec/SKILL.md)
  - [`create-tech-spec`](../.agents/skills/create-tech-spec/SKILL.md)
  - [`write-product-spec`](../.agents/skills/write-product-spec/SKILL.md)
  - [`write-tech-spec`](../.agents/skills/write-tech-spec/SKILL.md)
- Output area: [`../specs/`](../specs/)

**What it does**

- gathers issue details and relevant org-member discussion
- creates the product and technical spec artifacts for the issue
- commits the spec diff onto a dedicated branch
- creates or updates a PR containing the spec work

**Role in the OSS workflow**

This workflow turns an issue from “understood” into “designed.” It is the formal handoff between triage and implementation.

**How to integrate it elsewhere**

Use this workflow when another system decides an issue is ready for a design pass, for example after applying a “ready to spec” signal, a workflow state transition, or an assignment event.

### Implementation creation: [`create-implementation-from-issue.yml`](../.github/workflows/create-implementation-from-issue.yml)

**Implementation**

- Workflow: [`create-implementation-from-issue.yml`](../.github/workflows/create-implementation-from-issue.yml)
- Script: [`create_implementation_from_issue.py`](../.github/scripts/create_implementation_from_issue.py)
- Skills:
  - [`implement-issue`](../.agents/skills/implement-issue/SKILL.md)
  - [`implement-specs`](../.agents/skills/implement-specs/SKILL.md)
  - [`spec-driven-implementation`](../.agents/skills/spec-driven-implementation/SKILL.md)
- Spec context source: [`../specs/`](../specs/)

**What it does**

- resolves approved spec context when it exists
- refuses to proceed when spec PRs exist but are not yet approved
- creates implementation changes on either the approved spec branch or a dedicated implementation branch
- validates the resulting changes
- pushes the branch and creates or updates the implementation PR

**Role in the OSS workflow**

This is the build workflow. It translates approved intent into code while preserving the linkage back to the issue and, when present, the approved spec artifacts.

**How to integrate it elsewhere**

Use this workflow when an external system can confidently say the issue is ready to build. The cleanest integrations are workflow-state transitions, explicit “ready to implement” labels, or approval of a spec PR.

### Pull request review: [`review-pull-request.yml`](../.github/workflows/review-pull-request.yml)

**Implementation**

- Workflow: [`review-pull-request.yml`](../.github/workflows/review-pull-request.yml)
- Script: [`review_pr.py`](../.github/scripts/review_pr.py)
- Skills:
  - [`review-pr`](../.agents/skills/review-pr/SKILL.md)
  - [`review-spec`](../.agents/skills/review-spec/SKILL.md)
  - [`check-impl-against-spec`](../.agents/skills/check-impl-against-spec/SKILL.md)

**Inputs**

- `pr_number`
- `trigger_source`
- `requester`
- optional `focus`
- optional `comment_id`

**What it does**

- resolves any available spec context for the PR
- chooses a code-review skill or a spec-review skill depending on the changed files
- generates structured review output
- posts the resulting review back onto the pull request

**Role in the OSS workflow**

This is the reusable review engine for the platform. It performs first-pass automated review for implementation PRs and spec-only PRs.

**How to integrate it elsewhere**

This workflow fits well behind:

- automatic PR-opened or ready-for-review hooks
- manual slash-command review requests
- external “please review this PR now” orchestration

### Review-skill maintenance: [`update-pr-review.yml`](../.github/workflows/update-pr-review.yml)

**Implementation**

- Workflow: [`update-pr-review.yml`](../.github/workflows/update-pr-review.yml)
- Script: [`update_pr_review.py`](../.github/scripts/update_pr_review.py)
- Skill: [`update-pr-review`](../.agents/skills/update-pr-review/SKILL.md)
- Files updated by the loop:
  - [`review-pr`](../.agents/skills/review-pr/SKILL.md)
  - [`review-spec`](../.agents/skills/review-spec/SKILL.md)

**What it does**

- aggregates recent PR review discussions
- separates evidence from code PRs and spec PRs
- updates the review skills themselves when the feedback supports a durable change
- opens a follow-up PR with those skill adjustments

**Role in the OSS workflow**

This workflow is the platform’s explicit self-improvement loop. It does not review product code directly. Instead, it learns from human responses to prior reviews and updates the review instructions that future Oz review runs will use.

**How to integrate it elsewhere**

Use this as scheduled maintenance or as an operator-invoked calibration pass when review quality drifts or the repository’s expectations change.

## Conditionally agent-backed reusable workflows

### PR issue-state enforcement: [`enforce-pr-issue-state.yml`](../.github/workflows/enforce-pr-issue-state.yml)

**Implementation**

- Workflow: [`enforce-pr-issue-state.yml`](../.github/workflows/enforce-pr-issue-state.yml)
- Script: [`enforce_pr_issue_state.py`](../.github/scripts/enforce_pr_issue_state.py)

**Inputs and outputs**

- input: `pr_number`
- optional input: `requester`
- output: `allow_review`

**What it does**

- checks whether a PR clearly maps to an issue in the correct ready state
- fast-paths some cases without using Oz, such as PRs authored by org members or PRs with an explicit valid issue link
- uses Oz only when the PR needs fuzzy association against open ready issues
- closes PRs that do not satisfy the policy
- emits `allow_review` so downstream workflows can stop or continue

**Role in the OSS workflow**

This is the policy gate in front of automated review. It keeps design and implementation work tied to issues that have reached the correct repository state.

**How to integrate it elsewhere**

Place this workflow before expensive review or test automation when you want issue readiness to be a hard requirement for PR processing.

## Non-agent reusable workflows

### Unready assignment guardrail: [`comment-on-unready-assigned-issue.yml`](../.github/workflows/comment-on-unready-assigned-issue.yml)

**Implementation**

- Workflow: [`comment-on-unready-assigned-issue.yml`](../.github/workflows/comment-on-unready-assigned-issue.yml)
- Script: [`comment_on_unready_assigned_issue.py`](../.github/scripts/comment_on_unready_assigned_issue.py)

**Uses Oz?**

No. This workflow does not invoke an agent.

**What it does**

- posts a comment explaining that the issue is assigned prematurely
- removes the `oz-agent` assignee

**Role in the OSS workflow**

This is a scripted guardrail, not a generative workflow. Its job is to keep assignment state aligned with readiness state.

**How to integrate it elsewhere**

Use this when another system may assign Oz optimistically and you want a cheap corrective path before any agent work starts.

### Test runner: [`run-tests.yml`](../.github/workflows/run-tests.yml)

**Implementation**

- Workflow: [`run-tests.yml`](../.github/workflows/run-tests.yml)

**Uses Oz?**

No. This workflow does not invoke an agent.

**What it does**

- detects whether the PR has non-markdown changes
- checks out the PR merge ref when code changed
- installs Python dependencies
- runs the repository test suite

**Role in the OSS workflow**

This is supporting validation around the agent workflows rather than an agent workflow itself.

## Repository-local adapters and orchestrators

The workflows above are the reusable platform surface. This repository also contains local wiring that shows how to connect that surface to concrete GitHub events:

- [`triage-new-issues-local.yml`](../.github/workflows/triage-new-issues-local.yml)
- [`respond-to-triaged-issue-comment-local.yml`](../.github/workflows/respond-to-triaged-issue-comment-local.yml)
- [`create-spec-from-issue-local.yml`](../.github/workflows/create-spec-from-issue-local.yml)
- [`create-implementation-from-issue-local.yml`](../.github/workflows/create-implementation-from-issue-local.yml)
- [`update-pr-review-local.yml`](../.github/workflows/update-pr-review-local.yml)
- [`comment-on-unready-assigned-issue-local.yml`](../.github/workflows/comment-on-unready-assigned-issue-local.yml)
- [`pr-hooks.yml`](../.github/workflows/pr-hooks.yml)
- [`respond-to-pr-comment.yml`](../.github/workflows/respond-to-pr-comment.yml)

Two important points about that local layer:

- it is intentionally thinner than the reusable workflows
- some important repository behaviors, especially [`respond-to-pr-comment.yml`](../.github/workflows/respond-to-pr-comment.yml), are currently repository-local rather than part of the reusable `workflow_call` surface

## End-to-end platform flow

The reusable workflows form a staged OSS automation pipeline:

1. **Triage and clarification** via [`triage-new-issues.yml`](../.github/workflows/triage-new-issues.yml)
2. **Targeted follow-up on triaged issues** via [`respond-to-triaged-issue-comment.yml`](../.github/workflows/respond-to-triaged-issue-comment.yml)
3. **Design artifact generation** via [`create-spec-from-issue.yml`](../.github/workflows/create-spec-from-issue.yml)
4. **Implementation generation** via [`create-implementation-from-issue.yml`](../.github/workflows/create-implementation-from-issue.yml)
5. **PR policy enforcement** via [`enforce-pr-issue-state.yml`](../.github/workflows/enforce-pr-issue-state.yml)
6. **Review and validation** via [`review-pull-request.yml`](../.github/workflows/review-pull-request.yml) and [`run-tests.yml`](../.github/workflows/run-tests.yml)
7. **Self-improvement of review behavior** via [`update-pr-review.yml`](../.github/workflows/update-pr-review.yml)

## Design principles

The platform currently follows a few consistent rules:

- **Reusable workflows are the main integration boundary.**
- **GitHub state is the control plane.**
- **Specs are first-class artifacts under [`../specs/`](../specs/).**
- **Not every workflow is an agent workflow.** Some workflows are policy or validation guardrails only.
- **The review system has a built-in self-improvement loop.**
