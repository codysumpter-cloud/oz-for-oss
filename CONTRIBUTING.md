# Contributing

## How this repo decides when changes are accepted

The issue is where product alignment happens. Anyone can file one, and anyone can join the discussion. Once the problem is clear enough, the Warp team decides whether the next step is planning or implementation.

That decision is expressed with issue labels:

- `ready-to-plan` means we agree on the problem but still want technical due diligence before code starts.
- `ready-to-implement` means the product shape and technical approach are already in good enough shape that someone can start writing code.

Those labels are the repo's way of saying when a change is open for contribution. They are not Oz-specific, and they do not mean only one person can work on something. They just tell contributors whether we are accepting a plan first or whether we are ready for code.

Other labels, such as automated triage labels for area or reproducibility, are informational only. They do not change whether an issue is ready for planning or implementation.

## When to open a plan PR

Plan-only changes are accepted when they are tied to an issue that is marked `ready-to-plan`.

In practice, that means:

- use the issue for product discussion first
- wait until the Warp team marks the issue `ready-to-plan`
- open a PR with the plan once the issue is in that state
- use the PR as the place for technical discussion and iteration

For larger changes, the plan lives in the PR and becomes the home for the technical back-and-forth. Once it is in good shape, the Warp team can approve it and the work can move into implementation.

## When to open a code PR

Code changes are accepted when they are tied to an issue that is marked `ready-to-implement`.

In practice, that means:

- use the issue to get the product discussion into a stable place
- wait until the Warp team marks the issue `ready-to-implement`
- open a PR with the implementation once the issue is in that state

For smaller changes, we can go straight from issue to code. For larger changes, we usually expect the plan step first and then implementation on that same PR or a linked follow-up PR.

## Who decides readiness

Contributors can file issues, comment on issues and PRs, and open PRs directly. The Warp team is still the group that decides whether an issue is ready for planning or ready for implementation. Contributors should not treat discussion alone as approval to start a plan or code change if the readiness label is missing.

## A note on parallel work

Marking an issue as ready is not meant to lock it. It just means the repo is open for that next chunk of work. Someone can take a swing at it with Oz, another coding agent, or by hand. If multiple people explore the same issue, that is still normal open source behavior and we will select the best implementation through normal review.
