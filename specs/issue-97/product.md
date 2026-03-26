# Issue #97: Add onboarding script for Oz management layer

## Product Spec

### Goal
Provide a single entry point that walks an open-source project through the complete setup required to adopt the Oz management layer workflows from this repository. Today, adopting these workflows requires manually configuring several disparate pieces — skills, secrets, GitHub App credentials, and environment IDs — across a target repository with no guided path. The onboarding script removes that friction by automating as much of the setup as possible and interactively prompting for the pieces that require human input.

### Intended behavior

#### Single bootstrap command
A user with a Warp team account runs a single shell command from the root of their target repository. The script is hosted in the `oz-for-oss` repository and can be acquired and executed without cloning `oz-for-oss` first. The recommended approach is to download and inspect the script before running it. A `curl | bash` shorthand is available for convenience.

#### Step 1 — Prerequisites check
The script verifies that required tools are available:
- `git` (authenticated and inside a git repository)
- `gh` (GitHub CLI, authenticated with sufficient permissions)
- A Warp team with a team-scoped API key (see [Warp team setup](https://docs.warp.dev/features/teams))
- A GitHub App installed on the target repository for workflow authentication (see [GitHub App documentation](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps))
- Network connectivity to GitHub and the Warp API

If any prerequisite is missing, the script prints a clear error message explaining what is needed and exits.

#### Step 2 — Warp API key configuration
- The script prompts the user for their Warp team-scoped API key (or reads it from a `WARP_API_KEY` environment variable if already set). Team API keys can be generated from the Warp team settings page at [app.warp.dev/settings/team/api-keys](https://app.warp.dev/settings/team/api-keys).
- It stores the key as a GitHub Actions repository secret named `WARP_API_KEY` via the `gh` CLI.

#### Step 3 — GitHub App credentials
- The script prompts the user for their GitHub App ID (`GHA_APP_ID`) and the path to the private key file (`GHA_PRIVATE_KEY`).
- These values come from a GitHub App the user has already created and installed on their repository. The script prints a link to GitHub's documentation on creating a GitHub App and explains the required permissions (contents: write, issues: write, pull-requests: write, id-token: write). The App ID is visible on the GitHub App's settings page, and the private key can be generated and downloaded from the same page.
- Both values are stored as GitHub Actions repository secrets via the `gh` CLI.

#### Step 4 — Oz environment configuration
- The script prompts for the base Oz agent environment ID (`WARP_AGENT_ENVIRONMENT_ID`).
- It optionally prompts for workflow-specific environment IDs (`WARP_AGENT_TRIAGE_ENVIRONMENT_ID`, `WARP_AGENT_SPEC_ENVIRONMENT_ID`, `WARP_AGENT_IMPLEMENTATION_ENVIRONMENT_ID`, `WARP_AGENT_REVIEW_ENVIRONMENT_ID`, `WARP_AGENT_ENFORCEMENT_ENVIRONMENT_ID`). If not provided, these fall back to the base environment ID at workflow runtime.
- Optional agent configuration variables (`WARP_AGENT_MODEL`, `WARP_AGENT_MCP`, `WARP_AGENT_PROFILE`) are prompted if the user wants to customize them.
- Environment IDs and optional variables are stored as GitHub Actions repository variables via `gh variable set`.

#### Step 5 — Install workflow files
- The script installs GitHub Actions workflow files into the target repository's `.github/workflows/` directory.
- Rather than copying the full workflow definitions that embed Python source from `oz-for-oss`, the installed workflows reference the `oz-for-oss` repository's reusable workflows directly (e.g. `uses: warpdotdev/oz-for-oss/.github/workflows/<name>.yml@main`). This keeps the Python source and workflow logic in `oz-for-oss` as the single source of truth and avoids requiring the target repository to maintain its own copies of the Python code.
- If workflow files already exist in the target repository, the script warns the user and asks for confirmation before overwriting.

#### Step 6 — Copy skill files
- The script copies the `.agents/skills/` directory from `oz-for-oss` into the target repository.
- If skill files already exist, the script warns and asks for confirmation before overwriting.

#### Step 7 — Bootstrap triage configuration
- The script prints documentation and instructions for the user to bootstrap triage configuration (`.github/issue-triage/config.json` and `.github/STAKEHOLDERS`) via Oz or manually.
- This step is optional — the user can skip it if they want to configure triage later.

#### Step 8 — Summary and next steps
- The script prints a summary of everything it configured: secrets set, variables set, and files installed.
- It lists any manual steps the user still needs to complete (e.g. creating a GitHub App if they haven't already, enabling GitHub Actions on the repo, bootstrapping triage configuration).
- It suggests opening a test issue to trigger triage and verify the setup works.

### Acceptance criteria

1. A user can run a single command from a target repository to set up the full Oz management layer.
2. After running the script, the target repository has workflow files that reference `oz-for-oss` reusable workflows and skill files in the correct locations.
3. All required GitHub Actions secrets (`WARP_API_KEY`, `GHA_APP_ID`, `GHA_PRIVATE_KEY`) are set on the target repository.
4. All required GitHub Actions variables (at minimum `WARP_AGENT_ENVIRONMENT_ID`) are set on the target repository.
5. The script is hosted in `oz-for-oss` and acquirable without first cloning the full repository.
6. The script provides clear error messages when prerequisites are missing.
7. The script does not silently overwrite existing configuration in the target repository without user confirmation.
8. The script is idempotent — re-running it is safe and does not break an existing working setup.

### Scope

#### In scope
- Interactive shell script for end-to-end repository onboarding
- Prerequisite checks (git, gh, Warp team, GitHub App)
- Prompting for and storing Warp API key, GitHub App credentials, and Oz environment configuration
- Installing workflow files that reference `oz-for-oss` reusable workflows into the target repository
- Copying skill files into the target repository
- Documentation-based triage configuration guidance
- Summary output with next steps

#### Out of scope
- Creating the GitHub App itself (the user must do this manually; the script provides documentation links)
- Creating a Warp team or account (the script assumes these exist)
- Copying Python source files or dependencies into the target repository (workflows reference `oz-for-oss` directly)
- CI/CD pipeline setup beyond installing the workflow files
- Automated end-to-end validation that triggers a real Oz agent run (suggested as a manual next step)
- Windows support (the script targets Unix-like environments consistent with the existing workflows)
- Supporting non-GitHub hosting platforms

### Open product questions

1. **Acquisition mechanism**: The script should be acquirable via a download-and-run approach from the `oz-for-oss` repository. A `curl | bash` shorthand is provided for convenience. A `gh` extension or dedicated CLI may be considered in the future but is not needed for the initial version.
2. **GitHub App creation guidance**: The script will include links to documentation for creating the required GitHub App. Automating GitHub App creation is not planned.
3. **Versioning**: When referencing reusable workflows from `oz-for-oss`, should the workflow files pin to a specific release tag or always use `@main`? Using `@main` is simpler for the initial version, but a versioned release strategy may be needed as the project matures.
