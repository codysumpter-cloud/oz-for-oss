# Issue #97: Add onboarding script for Oz management layer

## Product Spec

### Goal
Provide a single entry point that walks an open-source project through the complete setup required to adopt the Oz management layer workflows from this repository. Today, adopting these workflows requires manually configuring several disparate pieces — skills, secrets, GitHub App credentials, environment IDs, and Python dependencies — across a target repository with no guided path. The onboarding script removes that friction by automating as much of the setup as possible and interactively prompting for the pieces that require human input.

### Intended behavior

#### Single bootstrap command
A user with a Warp account runs a single shell command from the root of their target repository. The script is hosted in the `oz-for-oss` repository and can be acquired and executed without cloning `oz-for-oss` first (e.g. via `curl | bash` or a similar lightweight acquisition mechanism).

#### Step 1 — Prerequisites check
The script verifies that required tools are available:
- `git` (authenticated and inside a git repository)
- `gh` (GitHub CLI, authenticated with sufficient permissions)
- `python3` (>= 3.11)
- Network connectivity to GitHub and the Warp API

If any prerequisite is missing, the script prints a clear error message explaining what is needed and exits.

#### Step 2 — Warp API key configuration
- The script prompts the user for their Warp team API key (or reads it from a `WARP_API_KEY` environment variable if already set).
- It stores the key as a GitHub Actions repository secret named `WARP_API_KEY` via the `gh` CLI.

#### Step 3 — GitHub App credentials
- The script prompts the user for their GitHub App ID (`GHA_APP_ID`) and the path to the private key file (`GHA_PRIVATE_KEY`).
- These are expected to come from a GitHub App the user has already created and installed on their repository (the script does not create the GitHub App itself).
- Both values are stored as GitHub Actions repository secrets via the `gh` CLI.

#### Step 4 — Oz environment configuration
- The script prompts for the base Oz agent environment ID (`WARP_AGENT_ENVIRONMENT_ID`).
- It optionally prompts for workflow-specific environment IDs (`WARP_AGENT_TRIAGE_ENVIRONMENT_ID`, `WARP_AGENT_SPEC_ENVIRONMENT_ID`, `WARP_AGENT_IMPLEMENTATION_ENVIRONMENT_ID`, `WARP_AGENT_REVIEW_ENVIRONMENT_ID`, `WARP_AGENT_ENFORCEMENT_ENVIRONMENT_ID`). If not provided, these fall back to the base environment ID at workflow runtime.
- Optional agent configuration variables (`WARP_AGENT_MODEL`, `WARP_AGENT_MCP`, `WARP_AGENT_PROFILE`) are prompted if the user wants to customize them.
- Environment IDs and optional variables are stored as GitHub Actions repository variables via `gh variable set`.

#### Step 5 — Copy workflow files
- The script copies the `.github/workflows/` directory from the `oz-for-oss` repository into the target repository.
- If workflow files already exist in the target repository, the script warns the user and asks for confirmation before overwriting.

#### Step 6 — Copy skill files
- The script copies the `.agents/skills/` directory from `oz-for-oss` into the target repository.
- If skill files already exist, the script warns and asks for confirmation before overwriting.

#### Step 7 — Install Python dependencies
- The script copies `src/requirements.txt` into the target repository at `src/requirements.txt` (or a configurable path).
- It copies the `src/oz_workflows/` package and the Python entrypoint scripts from `src/` into the target repository.
- If a virtual environment is detected, it installs dependencies into it. Otherwise, it advises the user to set one up.

#### Step 8 — Bootstrap triage configuration
- The script invokes the `bootstrap-issue-config` skill logic (or runs it as a subprocess) to generate `.github/issue-triage/config.json` and `.github/STAKEHOLDERS` in the target repository.
- This step is optional — the user can skip it if they want to configure triage manually.

#### Step 9 — Summary and next steps
- The script prints a summary of everything it configured: secrets set, variables set, files copied, and triage config generated.
- It lists any manual steps the user still needs to complete (e.g. creating a GitHub App if they haven't already, enabling GitHub Actions on the repo).
- It optionally suggests running a test triage on a recent open issue to verify the setup works.

### Acceptance criteria

1. A user can run a single command from a target repository to set up the full Oz management layer.
2. After running the script, the target repository has all workflow files, skill files, Python source files, and dependencies in the correct locations.
3. All required GitHub Actions secrets (`WARP_API_KEY`, `GHA_APP_ID`, `GHA_PRIVATE_KEY`) are set on the target repository.
4. All required GitHub Actions variables (at minimum `WARP_AGENT_ENVIRONMENT_ID`) are set on the target repository.
5. The script is hosted in `oz-for-oss` and acquirable without first cloning the full repository.
6. The script provides clear error messages when prerequisites are missing.
7. The script does not silently overwrite existing configuration in the target repository without user confirmation.

### Scope

#### In scope
- Interactive shell script for end-to-end repository onboarding
- Prerequisite checks (git, gh, python3)
- Prompting for and storing Warp API key, GitHub App credentials, and Oz environment configuration
- Copying workflow files, skill files, and Python source/dependencies into the target repository
- Optional triage configuration bootstrapping
- Summary output with next steps

#### Out of scope
- Creating the GitHub App itself (the user must do this manually or via a separate process)
- Creating a Warp account (the script assumes the user already has one)
- PyPI packaging of the Python workflows (this is flagged as an open question for future work)
- CI/CD pipeline setup beyond copying the workflow files
- Automated end-to-end validation that triggers a real Oz agent run (suggested as a manual next step)
- Windows support (the script targets Unix-like environments consistent with the existing workflows)
- Supporting non-GitHub hosting platforms

### Open product questions

1. **Acquisition mechanism**: The script should be runnable via `curl | bash` from the `oz-for-oss` repository. Should we also provide a `gh` extension or a dedicated CLI tool for a more polished acquisition story? For the initial version, a standalone shell script hosted at a stable URL is sufficient.
2. **GitHub App creation guidance**: Should the script include a link to documentation for creating the required GitHub App, or should we eventually automate GitHub App creation via the GitHub API? For now, documentation links are sufficient.
3. **Partial re-runs**: If the script is interrupted partway through, should re-running it detect what has already been configured and skip those steps? The initial version should be safe to re-run (idempotent where possible) but does not need to be fully resumable.
4. **Versioning**: When copying files from `oz-for-oss`, should the script pin to a specific release tag or always use the latest `main` branch? Using `main` is simpler for the initial version, but a versioned release strategy may be needed as the project matures.
5. **Staging vs production API**: The current `oz_client.py` is hardcoded to a staging base URL and requires a `STAGING_ORIGIN_TOKEN`. The onboarding script needs to handle this — either by also configuring the staging token, or by expecting a production API configuration. This needs resolution before implementation.
