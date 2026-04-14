# Issue #193: Add setup instructions to README

## Product Spec

### Summary

The oz-for-oss README describes the repository's purpose and its primary artifacts but does not explain how an external repository can adopt the Oz-backed workflows. This change adds a "Setup" section to the README that walks a repository maintainer through creating a GitHub App installation, configuring the required secrets and variables in GitHub Actions, and incorporating the reusable workflows into a target repository.

### Problem

A maintainer who wants to use the Oz automation in their own repository currently has no documented path. They must reverse-engineer the workflow YAML files to discover which secrets (`OZ_MGMT_GHA_APP_ID`, `OZ_MGMT_GHA_PRIVATE_KEY`, `WARP_API_KEY`) and optional variables (`WARP_AGENT_MODEL`, `WARP_AGENT_MCP`, `WARP_ENVIRONMENT_ID`) are needed, understand the GitHub App permission model, and figure out the correct `workflow_call` invocation pattern by reading the local trigger files. This is a significant onboarding barrier.

### Goals

- Provide clear, step-by-step instructions for setting up the GitHub App installation that the management agent uses to authenticate.
- Document every required secret and optional variable, including what each one controls.
- Show how to incorporate the reusable workflows into a target repository by creating local trigger workflow files.
- Make the instructions self-contained enough that a maintainer can follow them without reading the workflow YAML source.

### Non-goals

- Automating the setup process (e.g. a CLI tool or setup script).
- Documenting the internal implementation of the Python entrypoints or helper modules.
- Covering local development or debugging of the workflows (already partially covered in the existing README).
- Documenting every workflow trigger condition in exhaustive detail — the setup section should focus on getting started, not replacing the workflow YAML as the source of truth.
- Documenting the Google Cloud authentication steps. These are specific to Warp's infrastructure and not required by external adopters (the staging origin token resolution is an internal Warp detail).

### Figma / design references

Figma: none provided. This is a documentation change with no UI component.

### User experience

#### Audience

The primary reader is a repository maintainer who wants to adopt the Oz-backed workflows in a new or existing GitHub repository. They are assumed to have basic familiarity with GitHub Actions, repository secrets, and GitHub Apps.

#### Location in the README

The setup instructions are added as a new top-level section in the README, placed after the existing "Workflow surface" section and before "Local development". The section heading is "## Setting up Oz workflows in a new repository" (or similar).

#### Content structure

The setup section has three subsections:

1. **GitHub App installation** — Explains what the GitHub App is for (authenticating as a bot to manage issues, PRs, and repository contents), what permissions it needs, and how to install it on the target organization or repository. Covers:
   - Creating a new GitHub App (or reusing an existing one) with the required permissions: `contents: write`, `issues: write`, `pull-requests: write`, `id-token: write` at minimum.
   - Installing the app on the target repository or organization.
   - Noting the App ID and generating a private key, which become the `OZ_MGMT_GHA_APP_ID` and `OZ_MGMT_GHA_PRIVATE_KEY` secrets.

2. **Environment variables and secrets** — A reference table or list of all secrets and variables, organized by whether they are required or optional:
   - **Required secrets:**
     - `OZ_MGMT_GHA_APP_ID` — The numeric App ID of the GitHub App installation.
     - `OZ_MGMT_GHA_PRIVATE_KEY` — The PEM-encoded private key for the GitHub App.
     - `WARP_API_KEY` — The Warp API key used to invoke Oz agents.
   - **Optional variables (repository-level `vars`):**
     - `WARP_AGENT_MODEL` — Override the default agent model.
     - `WARP_AGENT_MCP` — MCP configuration for the agent.
     - `WARP_ENVIRONMENT_ID` — Cloud environment ID for the agent.
   - Instructions for where to configure these (repository settings → Secrets and variables → Actions).

3. **Incorporating reusable workflows** — Explains how the target repository calls the oz-for-oss reusable workflows. Covers:
   - The pattern: create a local trigger workflow (e.g. `triage-new-issues-local.yml`) that listens for the relevant GitHub events and calls the reusable workflow in `warpdotdev/oz-for-oss` via `uses: warpdotdev/oz-for-oss/.github/workflows/<workflow>.yml@main`.
   - A concrete example showing a minimal local trigger file for one workflow (e.g. triage).
   - A list of the available reusable workflows and a one-line description of what each does:
     - `triage-new-issues.yml` — Triages newly opened issues.
     - `create-spec-from-issue.yml` — Generates product and tech specs from a labeled issue.
     - `create-implementation-from-issue.yml` — Creates an implementation diff from a labeled issue.
     - `review-pull-request.yml` — Reviews pull requests.
     - `enforce-pr-issue-state.yml` — Enforces issue-state requirements on PRs.
     - `comment-on-unready-assigned-issue.yml` — Posts guidance when Oz is assigned to an issue that is not yet ready.
     - `respond-to-pr-comment.yml` — Responds to `@oz-agent` mentions in PR comments.
     - `respond-to-triaged-issue-comment.yml` — Responds to `@oz-agent` mentions on triaged issues.
     - `update-pr-review.yml` — Periodically updates the PR review skill from human feedback.
   - A note that the local trigger files in `oz-for-oss` itself (the `*-local.yml` files) serve as reference implementations and can be copied and adapted.
   - A note that `secrets: inherit` is the simplest way to pass the required secrets when using `uses` within the same organization.

#### Behavior rules

1. **No new files beyond the README.** The setup instructions live entirely in the README. No separate setup guide, wiki page, or additional markdown file is created.
2. **Existing README sections are unchanged.** The new section is inserted between existing sections without modifying their content. The "Primary artifacts", "Workflow surface", "Local development", "Bootstrapping triage configuration", and "Repository conventions" sections remain as they are.
3. **Code examples use fenced code blocks.** Any YAML or shell snippets use fenced code blocks with the appropriate language identifier.
4. **Instructions are prescriptive, not exploratory.** Each step tells the reader what to do, not what they might consider doing.
5. **Secrets are never shown in plain text.** Example YAML uses `${{ secrets.SECRET_NAME }}` syntax. No dummy values that could be confused with real credentials.

### Success criteria

1. A maintainer who has never seen the repository can read the setup section and, starting from an empty GitHub repository, configure the GitHub App, set the required secrets, and create at least one local trigger workflow that successfully calls a reusable workflow.
2. The list of required secrets and optional variables in the README matches what the reusable workflows actually declare.
3. Every reusable `workflow_call` workflow in `.github/workflows/` is mentioned in the setup instructions with a brief description.
4. The example local trigger workflow YAML is syntactically valid and follows the same patterns as the existing `*-local.yml` files.
5. The README remains a single file with a clear, scannable structure. The setup section does not exceed roughly 150 lines of markdown.
6. Existing README content is preserved without modification.

### Validation

- **Manual review**: Read the setup section end-to-end and confirm each step is actionable and complete.
- **Cross-reference**: Compare the list of secrets and variables in the setup section against every `workflow_call` workflow's `secrets:` and the `env:` / `vars` references in the YAML files. Confirm nothing is missing or extraneous.
- **Example validation**: Confirm the example local trigger YAML is syntactically valid by running it through `actionlint` or equivalent.
- **Structural review**: Confirm the new section fits naturally in the README's existing table of contents and does not disrupt the flow.

### Open questions

1. **Should the instructions cover the Google Cloud / Workload Identity Federation setup for the staging origin token?** This appears to be Warp-internal infrastructure. The current recommendation is to exclude it from the public setup instructions and note that external adopters do not need it unless they are integrating with Warp's staging environment. If external adopters need an equivalent, it should be documented separately.
2. **Should the setup section link to GitHub's official documentation for creating a GitHub App?** Linking to the official docs avoids duplicating content that may change, but adds an external dependency. A brief inline summary with a link to the official docs for full details is likely the best balance.
3. **Should there be a "quick start" vs. "full reference" split?** For the initial version, a single linear walkthrough is simpler. A quick-start summary can be added later if the section grows.
