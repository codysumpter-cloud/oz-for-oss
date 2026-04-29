# oz-for-oss

Oz for OSS is a reusable open-source automation platform that lets a Warp-hosted Oz agent triage issues, draft product and tech specs, open implementation PRs, review pull requests, respond to PR comments, and verify changes via slash commands. The intelligence lives in the agent skills under [`.agents/skills/`](.agents/skills/) and the prompt-construction layer that feeds them concrete repository context — everything else is delivery wiring around those skills.

PR-triggered work and issue triage run through a Vercel-hosted webhook control plane (`api/`, `lib/`, `tests/`, `vercel.json`); the remaining issue-triggered, plan-approval, and weekly self-improvement flows run as GitHub Actions workflows under [`.github/workflows/`](.github/workflows/).

## Documentation

- [Platform overview](docs/platform.md) — agent roles, prompt construction, and how skills back each workflow.
- [Architecture](docs/architecture.md) — repository layout and the end-to-end flow for both delivery surfaces.
- [Onboarding](docs/onboarding.md) — install the GitHub App, deploy the Vercel control plane, and wire up GitHub Actions in your own repo.
- [Contributing](CONTRIBUTING.md) — issue/PR workflow, label conventions, and local development.
