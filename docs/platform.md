# Platform workflows in `oz-for-oss`

The main thing this repository provides is a reusable GitHub Actions workflow layer for OSS management. The center of gravity is [`../.github/workflows/`](../.github/workflows/): issue triage, spec creation, implementation, review, and review-skill improvement all live there as `workflow_call` entrypoints that another repository or orchestration system can invoke.

That is the important boundary to keep in mind while reading this doc. The local adapters in this repository, such as [`triage-new-issues-local.yml`](../.github/workflows/triage-new-issues-local.yml) or [`pr-hooks.yml`](../.github/workflows/pr-hooks.yml), are examples of how one repository chooses to wire these reusable workflows into GitHub events. They are not the product surface. The product surface is the reusable workflow layer.

## How to think about the platform

This platform is opinionated about where state lives and how work advances.

GitHub is the control plane. Issues, labels, assignees, comments, pull requests, and branches are the state that the workflows read and write. Oz is the reasoning engine inside some of those workflows, but it is not the source of truth. The workflows use Oz to classify, explain, plan, implement, and review. They use GitHub state to decide what happens next.

Most of the reusable workflows share the same shape:

1. a reusable workflow file in [`../.github/workflows/`](../.github/workflows/)
2. a Python entrypoint in [`../.github/scripts/`](../.github/scripts/)
3. shared helpers in [`../.github/scripts/oz_workflows/`](../.github/scripts/oz_workflows/)
4. repository-specific skills in [`../.agents/skills/`](../.agents/skills/) when Oz is involved

From the outside, integrating with this platform usually means four things:

- call the right reusable workflow with the documented `workflow_call` inputs
- provide the required secrets and permissions
- decide which source-system event should trigger that call
- decide whether your consuming repository also needs a thin local adapter workflow

## The workflow arc

The platform is easiest to understand as a single narrative rather than as an inventory of files.

It starts when an issue enters the system. The first job is to turn that issue from raw discussion into structured repository state. Sometimes that only means applying labels and rewriting the issue body. Sometimes it also means asking clarifying questions because the report is not actionable yet.

Once the issue is clear enough, the next job is to turn intent into artifacts. For larger work, that means a product spec and a tech spec. For smaller work, the issue may already be in good enough shape to proceed directly to implementation.

After that, the platform moves into PR governance. It checks that the work actually corresponds to an issue in the right state, runs validation, produces an automated review, and leaves room for maintainers to continue steering the branch.

Finally, the system improves itself. Review feedback does not only affect the current PR. It can also be fed back into the review skills so future review runs get better.

That flow maps to a small number of reusable workflows.

## Intake and clarification

The intake point is [`triage-new-issues.yml`](../.github/workflows/triage-new-issues.yml), implemented by [`triage_new_issues.py`](../.github/scripts/triage_new_issues.py) and grounded in [`triage-issue`](../.agents/skills/triage-issue/SKILL.md) plus [`dedupe-issue`](../.agents/skills/dedupe-issue/SKILL.md).

This workflow is doing more than simple labeling. It is responsible for turning an issue into something the rest of the system can trust. That includes:

- classifying the issue
- normalizing the visible issue body
- reconciling managed labels from [`config.json`](../.github/issue-triage/config.json)
- using ownership hints from [`STAKEHOLDERS`](../.github/STAKEHOLDERS)
- detecting likely duplicates
- asking clarifying questions when the report is underspecified
- re-triaging after the reporter replies to those questions

That last point matters. In this platform, the issue triage agent is also the first clarification loop. If an issue is missing key information, triage is expected to ask for it rather than merely mark the issue as incomplete and stop there.

For consumers, this workflow is the right integration point when another system wants to say, “make this issue actionable.” The key inputs are an explicit `issue_number` for one-off triage and `lookback_minutes` for batch processing.

There is a second, narrower clarification workflow: [`respond-to-triaged-issue-comment.yml`](../.github/workflows/respond-to-triaged-issue-comment.yml), implemented by [`respond_to_triaged_issue_comment.py`](../.github/scripts/respond_to_triaged_issue_comment.py). It uses the same analytical skill family, but it does not retriage the whole issue. It is for the phase where an issue is already triaged and someone wants Oz to answer or interpret a follow-up comment without rewriting the issue body or mutating labels.

## From issue to spec

When the next step is design rather than code, the platform moves to [`create-spec-from-issue.yml`](../.github/workflows/create-spec-from-issue.yml), implemented by [`create_spec_from_issue.py`](../.github/scripts/create_spec_from_issue.py).

This workflow exists to make planning concrete. It uses [`spec-driven-implementation`](../.agents/skills/spec-driven-implementation/SKILL.md), [`create-product-spec`](../.agents/skills/create-product-spec/SKILL.md), [`create-tech-spec`](../.agents/skills/create-tech-spec/SKILL.md), and the shared writing skills [`write-product-spec`](../.agents/skills/write-product-spec/SKILL.md) and [`write-tech-spec`](../.agents/skills/write-tech-spec/SKILL.md).

The output is not ephemeral agent text. The output is committed repository state under [`../specs/`](../specs/), typically a `product.md` and `tech.md` for the issue, pushed on a branch and surfaced in a PR. That is an important design choice in this repo: plans are expected to become durable artifacts that code review can reason about.

For an external integrator, this is the workflow to call when an issue has crossed the line from “we understand the problem” to “we want the system to produce a design artifact.”

## From spec to implementation

When the issue is ready to build, the platform moves to [`create-implementation-from-issue.yml`](../.github/workflows/create-implementation-from-issue.yml), implemented by [`create_implementation_from_issue.py`](../.github/scripts/create_implementation_from_issue.py).

This workflow uses [`implement-issue`](../.agents/skills/implement-issue/SKILL.md), [`implement-specs`](../.agents/skills/implement-specs/SKILL.md), and [`spec-driven-implementation`](../.agents/skills/spec-driven-implementation/SKILL.md). Its job is to connect approved intent to actual code.

The workflow is opinionated about spec context. If there is approved spec material, it uses that. If there are spec PRs but none are approved, it refuses to proceed. That keeps the implementation path aligned with the repository’s planning model rather than treating specs as optional commentary.

The result is a branch update and usually a PR update. In other words, the integration contract is not “return a patch.” The integration contract is “produce repository changes in the right place, with the right issue and spec linkage.”

## Guardrails before review

Before review, the platform enforces repository policy with [`enforce-pr-issue-state.yml`](../.github/workflows/enforce-pr-issue-state.yml), implemented by [`enforce_pr_issue_state.py`](../.github/scripts/enforce_pr_issue_state.py).

This workflow sits in an important middle ground. It is not purely scripted, but it is not always agent-driven either. It has fast paths that do not use Oz at all, such as cases where the PR already has a clearly valid issue association. It only invokes Oz when the workflow needs fuzzy matching between a PR and the set of open ready issues.

That is why it is best understood as a conditional agent workflow rather than a pure agent workflow. Its purpose is not to create content. Its purpose is to keep review from starting on PRs that are not actually connected to issues in the correct state. The output `allow_review` is the control bit that downstream automation uses to continue or stop.

## Review, iteration, and branch follow-up

Once a PR is eligible for review, the main reusable review surface is [`review-pull-request.yml`](../.github/workflows/review-pull-request.yml), implemented by [`review_pr.py`](../.github/scripts/review_pr.py).

This workflow chooses between [`review-pr`](../.agents/skills/review-pr/SKILL.md) and [`review-spec`](../.agents/skills/review-spec/SKILL.md) based on the changed files, and it can use [`check-impl-against-spec`](../.agents/skills/check-impl-against-spec/SKILL.md) when spec context exists. The important point is that the workflow is already shaped to be a reusable review engine, not just a local bot hook. Callers supply a PR number, trigger source, requester, and optional review focus, and the workflow produces GitHub review output.

There is also an important repository-local follow-up path in [`respond-to-pr-comment.yml`](../.github/workflows/respond-to-pr-comment.yml), implemented by [`respond_to_pr_comment.py`](../.github/scripts/respond_to_pr_comment.py). That one is not part of the reusable `workflow_call` surface today. It exists in the local wiring layer because it is a concrete example of how a repository can let maintainers turn PR comments into branch updates with Oz. It is part of the platform story, but not yet part of the reusable integration boundary in the same way as the other workflows above.

Validation sits alongside review through [`run-tests.yml`](../.github/workflows/run-tests.yml). This is not an agent workflow. It is a conventional scripted test runner that checks whether a PR contains non-markdown changes, installs dependencies, and runs the repository test suite. It is part of the PR pipeline, but it does not invoke Oz.

## The self-improvement loop

The most distinctive workflow in the repo is [`update-pr-review.yml`](../.github/workflows/update-pr-review.yml), implemented by [`update_pr_review.py`](../.github/scripts/update_pr_review.py).

This workflow should be read as a self-improvement loop for the platform. It does not review product code directly. Instead, it looks at recent PR review discussions, separates evidence from code PRs and spec PRs, and updates [`review-pr`](../.agents/skills/review-pr/SKILL.md) and [`review-spec`](../.agents/skills/review-spec/SKILL.md) when the feedback suggests a durable rule change.

That design makes the review system iterative. The repository is not just using skills. It is also teaching those skills over time through observed reviewer feedback.

## Workflows that are not agents

Not every workflow in this repo should be described as an agent.

[`comment-on-unready-assigned-issue.yml`](../.github/workflows/comment-on-unready-assigned-issue.yml), implemented by [`comment_on_unready_assigned_issue.py`](../.github/scripts/comment_on_unready_assigned_issue.py), is a good example. It does not invoke Oz. It simply comments that an issue was assigned too early and removes the `oz-agent` assignee. That makes it a scripted guardrail, not a reasoning workflow.

[`run-tests.yml`](../.github/workflows/run-tests.yml) is the same way. It is pipeline support, not an agent.

That distinction is useful for integrators because it clarifies what kind of dependency they are taking on. Some workflows require agent credentials, prompt discipline, and review of generated output. Others are ordinary automation and can be treated that way.

## Local adapters in this repository

The local workflow files in [`../.github/workflows/`](../.github/workflows/) show one concrete wiring of the reusable layer:

- [`triage-new-issues-local.yml`](../.github/workflows/triage-new-issues-local.yml)
- [`respond-to-triaged-issue-comment-local.yml`](../.github/workflows/respond-to-triaged-issue-comment-local.yml)
- [`create-spec-from-issue-local.yml`](../.github/workflows/create-spec-from-issue-local.yml)
- [`create-implementation-from-issue-local.yml`](../.github/workflows/create-implementation-from-issue-local.yml)
- [`update-pr-review-local.yml`](../.github/workflows/update-pr-review-local.yml)
- [`comment-on-unready-assigned-issue-local.yml`](../.github/workflows/comment-on-unready-assigned-issue-local.yml)
- [`pr-hooks.yml`](../.github/workflows/pr-hooks.yml)
- [`respond-to-pr-comment.yml`](../.github/workflows/respond-to-pr-comment.yml)

They are useful reference material for consumers that want to see how these reusable workflows can be mapped onto issue events, comment events, PR events, and schedules. But they should be read as adapters and orchestrators, not as the primary abstraction.

## In one sentence

`oz-for-oss` is a reusable workflow platform for running an OSS contribution loop in GitHub: intake and clarification, spec creation, implementation, policy enforcement, review, and review self-improvement, with a clear distinction between agent-backed reasoning workflows and ordinary scripted guardrails.
