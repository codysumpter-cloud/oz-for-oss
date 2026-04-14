# Issue #193: Add setup instructions to README

## Tech Spec

### Problem

The README documents what the repository does but not how to adopt it. A new section needs to be added that covers GitHub App creation, secrets/variables configuration, and reusable workflow incorporation. The product spec defines the content structure and audience; this tech spec specifies exactly where the content goes, what it contains, and how it is validated.

### Relevant code

- `README.md (1-72)` — The entire current README. The new section is inserted between "Workflow surface" (line 24) and "Local development" (line 26).
- `.github/workflows/create-spec-from-issue.yml (4-10)` — Representative `workflow_call` trigger with the three required secrets.
- `.github/workflows/triage-new-issues-local.yml` — Representative local trigger file that calls a reusable workflow.
- `.github/workflows/create-spec-from-issue-local.yml` — Another local trigger showing the `secrets: inherit` pattern.

### Current state

The README has these top-level sections in order:

1. `# oz-for-oss` (heading + description)
2. `## Primary artifacts`
3. `## Workflow surface`
4. `## Local development`
5. `## Bootstrapping triage configuration`
6. `## Repository conventions`

There is no setup or onboarding section. The "Local development" section covers Python virtualenv setup and running tests, but does not address adopting the workflows in a different repository.

All reusable workflows declare the same three secrets via `workflow_call`:

- `OZ_MGMT_GHA_APP_ID` (required)
- `OZ_MGMT_GHA_PRIVATE_KEY` (required)
- `WARP_API_KEY` (required)

Exception: `comment-on-unready-assigned-issue.yml` only requires the two App secrets (no `WARP_API_KEY`), and `run-tests.yml` requires no secrets.

All reusable workflows except `comment-on-unready-assigned-issue.yml` and `run-tests.yml` reference these optional variables via `${{ vars.* }}`:

- `WARP_AGENT_MODEL`
- `WARP_AGENT_MCP`
- `WARP_ENVIRONMENT_ID`

The Google Cloud / Workload Identity Federation steps for resolving the staging origin token are Warp-internal infrastructure and should be excluded from the public setup instructions per the product spec.

### Proposed changes

#### 1. Insert a new `## Setting up Oz workflows in a new repository` section in `README.md`

Insert the new section after line 24 (end of "Workflow surface") and before line 26 (start of "Local development"). No existing content is modified.

The section has three subsections:

**### 1. Create and install a GitHub App**

Content:

- Explain that the workflows authenticate via a GitHub App to manage issues, PRs, and repository contents with elevated permissions.
- Link to GitHub's official documentation for creating a GitHub App: `https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app`.
- List the minimum required repository permissions for the app:
  - Contents: Read & write
  - Issues: Read & write
  - Pull requests: Read & write
- Instruct the user to install the app on the target repository or organization.
- Instruct the user to note the App ID (shown on the app settings page) and generate a private key (PEM file).

**### 2. Configure secrets and variables**

Content:

- Instruct the user to navigate to the target repository's Settings → Secrets and variables → Actions.
- List the three required repository secrets:
  - `OZ_MGMT_GHA_APP_ID` — The numeric App ID from the GitHub App settings page.
  - `OZ_MGMT_GHA_PRIVATE_KEY` — The full PEM-encoded private key generated in step 1.
  - `WARP_API_KEY` — A Warp API key for invoking Oz agents (obtained from the Warp dashboard).
- List the optional repository variables (set under the "Variables" tab, not "Secrets"):
  - `WARP_AGENT_MODEL` — Overrides the default Oz agent model.
  - `WARP_AGENT_MCP` — MCP server configuration passed to the agent.
  - `WARP_ENVIRONMENT_ID` — Cloud environment ID for the agent runtime.

**### 3. Add local trigger workflows**

Content:

- Explain the two-layer pattern: `oz-for-oss` exposes reusable `workflow_call` workflows; the target repository creates thin local trigger files that listen for GitHub events and call the reusable workflow.
- Provide one complete example — a minimal local trigger file for issue triage. Use the existing `triage-new-issues-local.yml` as a template but replace `uses: ./.github/workflows/...` with `uses: warpdotdev/oz-for-oss/.github/workflows/triage-new-issues.yml@main` to show the cross-repository call pattern. Simplify the trigger conditions to the essentials.
- After the example, list all available reusable workflows with a one-line description:
  - `triage-new-issues.yml` — Triages newly opened issues using Oz.
  - `create-spec-from-issue.yml` — Generates product and tech specs for a labeled issue.
  - `create-implementation-from-issue.yml` — Creates an implementation diff for a labeled issue.
  - `review-pull-request.yml` — Reviews pull requests using Oz.
  - `enforce-pr-issue-state.yml` — Enforces that PRs are linked to issues in the correct state.
  - `comment-on-unready-assigned-issue.yml` — Posts guidance when Oz is assigned to an issue without a ready label.
  - `respond-to-pr-comment.yml` — Responds to `@oz-agent` mentions in PR comments.
  - `respond-to-triaged-issue-comment.yml` — Responds to `@oz-agent` mentions on triaged issues.
  - `update-pr-review.yml` — Periodically updates the PR review skill from human feedback.
  - `run-tests.yml` — Runs linting and unit tests on a pull request.
- Note that the `*-local.yml` files in this repository serve as reference implementations for the trigger conditions and can be copied and adapted.
- Note that `secrets: inherit` is the simplest way to pass secrets when using `uses` within the same organization, and that cross-organization calls require explicitly mapping each secret.

#### Example YAML for the trigger workflow

The example should look approximately like this (adapted from the existing `triage-new-issues-local.yml`):

```yaml
name: Triage New Issues
on:
  issues:
    types: [opened]
jobs:
  triage:
    if: "!contains(github.event.issue.labels.*.name, 'triaged')"
    permissions:
      contents: read
      id-token: write
      issues: write
    uses: warpdotdev/oz-for-oss/.github/workflows/triage-new-issues.yml@main
    secrets:
      OZ_MGMT_GHA_APP_ID: ${{ secrets.OZ_MGMT_GHA_APP_ID }}
      OZ_MGMT_GHA_PRIVATE_KEY: ${{ secrets.OZ_MGMT_GHA_PRIVATE_KEY }}
      WARP_API_KEY: ${{ secrets.WARP_API_KEY }}
```

This example explicitly maps secrets (rather than using `secrets: inherit`) because cross-repository callers cannot use `secrets: inherit`.

### Risks and mitigations

**Risk: The setup instructions become stale as workflows evolve.**
Mitigation: The instructions reference the workflow files by name and describe their purpose at a high level. They do not duplicate the full trigger conditions or step logic. The `*-local.yml` files are pointed to as the authoritative reference implementations.

**Risk: The GitHub App permissions listed become incomplete if new workflows require additional permissions.**
Mitigation: The listed permissions (`contents: write`, `issues: write`, `pull-requests: write`) cover the union of all current workflow requirements. New permissions can be added to the setup instructions when new workflows are introduced.

**Risk: External adopters are confused by the Google Cloud / staging origin token steps in the reusable workflows.**
Mitigation: The setup instructions explicitly exclude this as Warp-internal infrastructure. A note can be added that external adopters may need to remove or replace those steps if they fork the reusable workflows rather than calling them cross-repository.

### Testing and validation

- **actionlint**: Run `actionlint` on the example YAML snippet to confirm it is syntactically valid.
- **Cross-reference audit**: Verify that every `workflow_call` workflow in `.github/workflows/` is listed in the setup instructions. Compare the declared secrets against the documented secrets list.
- **Structural review**: Confirm the new section is inserted at the correct location in the README and that the existing sections are not modified.
- **Readability review**: Read the setup section from the perspective of a new maintainer and confirm each step is actionable.

### Follow-ups

- Consider adding a "Verification" subsection that tells the user how to trigger a test run (e.g. opening a test issue to confirm triage works) after the initial setup.
- If the Google Cloud authentication steps become relevant for external adopters, document them in a separate advanced setup guide rather than cluttering the main README.
- Consider adding a troubleshooting section for common setup issues (e.g. incorrect App permissions, missing secrets) once real adoption feedback is available.
