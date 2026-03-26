# Issue #97: Add onboarding script for Oz management layer

## Tech Spec

### Problem
There is no single entry point for adopting the Oz management layer in a new repository. A user must manually copy workflow files, skill files, and Python source code; create multiple GitHub Actions secrets and variables; install Python dependencies; and bootstrap triage configuration. This spec describes the implementation of an interactive onboarding shell script that automates this process end-to-end.

### Current state
- All GitHub Actions workflows live in `.github/workflows/` (8 workflow files). Each workflow expects specific secrets and variables to be configured on the target repository.
- Required secrets (from workflow files): `WARP_API_KEY`, `GHA_APP_ID`, `GHA_PRIVATE_KEY`.
- Required variables (from workflow files): `WARP_AGENT_ENVIRONMENT_ID`. Optional per-workflow overrides: `WARP_AGENT_TRIAGE_ENVIRONMENT_ID`, `WARP_AGENT_SPEC_ENVIRONMENT_ID`, `WARP_AGENT_IMPLEMENTATION_ENVIRONMENT_ID`, `WARP_AGENT_REVIEW_ENVIRONMENT_ID`, `WARP_AGENT_ENFORCEMENT_ENVIRONMENT_ID`. Optional agent tuning: `WARP_AGENT_MODEL`, `WARP_AGENT_MCP`, `WARP_AGENT_PROFILE`.
- Workflows also use Google Cloud Workload Identity Federation to resolve a `STAGING_ORIGIN_TOKEN` at runtime. This is specific to the staging environment and will need to be addressed for external adopters.
- `src/oz_workflows/oz_client.py` hardcodes `base_url="https://staging.warp.dev/api/v1"` and requires a `STAGING_ORIGIN_TOKEN` header. External adopters will need a production API endpoint or their own staging credentials.
- Skill files live in `.agents/skills/` (7 skills). These are referenced by workflows via the `skill_spec()` helper which constructs `{repo_slug}:.agents/skills/{name}/SKILL.md` paths.
- Python entrypoints are in `src/` (7 scripts). Shared library code is in `src/oz_workflows/` (7 modules). Dependencies are in `src/requirements.txt` (currently just `oz-sdk-python` from GitHub).
- Triage configuration lives in `.github/issue-triage/config.json` and `.github/STAKEHOLDERS`. The `bootstrap-issue-config` skill already automates generating these files.
- `README.md` documents local development setup but contains no onboarding instructions for external repositories.
- No existing onboarding tooling or bootstrap script exists in the repository.

### Proposed changes

#### 1. New file: `scripts/onboard.sh`

A standalone Bash script that drives the entire onboarding flow. Located at `scripts/onboard.sh` in the `oz-for-oss` repository. Designed to be acquired and executed remotely:

```
curl -fsSL https://raw.githubusercontent.com/warpdotdev/oz-for-oss/main/scripts/onboard.sh | bash
```

Or downloaded and run locally:

```
gh repo clone warpdotdev/oz-for-oss /tmp/oz-for-oss
bash /tmp/oz-for-oss/scripts/onboard.sh
```

The script assumes it is run from the root of the target repository.

**Internal structure:**

```
#!/usr/bin/env bash
set -euo pipefail

OZ_REPO="warpdotdev/oz-for-oss"
OZ_BRANCH="main"

# --- Utility functions ---
info()    { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()    { printf '\033[1;33mWARN:\033[0m %s\n' "$*"; }
err()     { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }
confirm() { read -rp "$1 [y/N] " ans; [[ "$ans" =~ ^[Yy] ]]; }

# --- Step functions (see below) ---
check_prerequisites()
configure_secrets()
configure_variables()
copy_workflows()
copy_skills()
copy_python_source()
bootstrap_triage()
print_summary()

main() {
    info "Oz management layer onboarding"
    check_prerequisites
    configure_secrets
    configure_variables
    copy_workflows
    copy_skills
    copy_python_source
    bootstrap_triage
    print_summary
}

main "$@"
```

**Step implementations:**

**`check_prerequisites()`**
- Verify `git` is installed and CWD is a git repository (`git rev-parse --is-inside-work-tree`).
- Verify `gh` is installed and authenticated (`gh auth status`).
- Verify `python3` is installed and >= 3.11 (`python3 --version`, parse output).
- Derive `REPO_SLUG` from `gh repo view --json nameWithOwner -q .nameWithOwner` for use in subsequent `gh secret set` / `gh variable set` commands.
- Exit with a clear message if any check fails.

**`configure_secrets()`**
- For each of `WARP_API_KEY`, `GHA_APP_ID`, `GHA_PRIVATE_KEY`:
  - Check if the secret already exists via `gh secret list` (parse output for the secret name).
  - If it exists, ask the user if they want to update it.
  - If not, prompt the user for the value.
  - For `GHA_PRIVATE_KEY`, accept a file path and read the file content.
  - Store via `gh secret set <NAME> --body <VALUE>` (or `--body-file` for the private key).

**`configure_variables()`**
- Prompt for `WARP_AGENT_ENVIRONMENT_ID` (required).
- Prompt for optional per-workflow environment IDs. Skip if the user presses Enter.
- Prompt for optional `WARP_AGENT_MODEL`, `WARP_AGENT_MCP`, `WARP_AGENT_PROFILE`.
- Store each non-empty value via `gh variable set <NAME> --body <VALUE>`.

**`copy_workflows()`**
- Create a temporary directory for the `oz-for-oss` clone (or use a sparse checkout).
- Use `gh api` or `git archive` to fetch `.github/workflows/` from `OZ_REPO` at `OZ_BRANCH`.
- Fallback: clone the repo into a temporary directory and copy from there.
- Create `.github/workflows/` in the target repo if it doesn't exist.
- For each workflow file, check if it already exists and prompt before overwriting.
- Copy the files.

**`copy_skills()`**
- Same acquisition mechanism as workflows.
- Copy `.agents/skills/` into the target repository.
- Prompt before overwriting existing skill files.

**`copy_python_source()`**
- Copy `src/oz_workflows/` and all `src/*.py` entrypoints into the target repository.
- Copy `src/requirements.txt`.
- If a virtual environment is detected (`.venv/`, `venv/`, or `$VIRTUAL_ENV` is set), run `pip install -r src/requirements.txt`.
- Otherwise, print instructions for setting up a virtual environment.

**`bootstrap_triage()`**
- Ask the user if they want to bootstrap triage configuration.
- If yes, check if the `bootstrap-issue-config` skill file was copied in the previous step.
- Run the triage bootstrap logic. Since the bootstrap skill is designed to be run by an Oz agent, the script can either:
  - (a) Execute a lightweight Python helper that replicates the core label-discovery and STAKEHOLDERS-generation logic using `gh` CLI calls, or
  - (b) Print instructions for the user to trigger a bootstrap run via Oz.
- Option (b) is simpler for the initial version and avoids duplicating the skill logic in Bash.

**`print_summary()`**
- Print a table of what was configured (secrets, variables, files).
- Print remaining manual steps:
  - If GitHub App was not yet created, link to documentation.
  - Remind the user to enable GitHub Actions on the repo if not already enabled.
  - Suggest opening a test issue to trigger triage and verify the setup.

#### 2. Modified file: `README.md`

Add an "Onboarding" or "Getting Started" section before the existing "Local development" section. Content:

```markdown
## Onboarding a new repository

To adopt the Oz management layer in your repository, run the onboarding script from the root of your target repository:

\`\`\`sh
curl -fsSL https://raw.githubusercontent.com/warpdotdev/oz-for-oss/main/scripts/onboard.sh | bash
\`\`\`

The script will guide you through:
1. Configuring Warp API keys and GitHub App credentials as repository secrets.
2. Setting Oz agent environment IDs as repository variables.
3. Copying workflow files, skill files, and Python source into your repository.
4. Optionally bootstrapping triage configuration.

### Prerequisites
- A Warp account with a team API key ([create one here](https://docs.warp.dev/reference/cli/api-keys))
- A GitHub App installed on your repository (for workflow authentication)
- `git`, `gh` (GitHub CLI), and `python3` (>= 3.11) installed locally
```

#### 3. Modified file: `CONTRIBUTING.md`

Add a brief note in the preamble or a new section pointing contributors to the onboarding script for setting up their own test repositories.

#### 4. New file: `scripts/README.md`

Short documentation file for the `scripts/` directory explaining what `onboard.sh` does and how to test it locally.

### File change summary

New files:
- `scripts/onboard.sh` — main onboarding script
- `scripts/README.md` — documentation for the scripts directory

Modified files:
- `README.md` — add onboarding section
- `CONTRIBUTING.md` — reference the onboarding script

### Risks and open technical questions

1. **Staging API hardcoding**: `oz_client.py` uses `base_url="https://staging.warp.dev/api/v1"` and requires `STAGING_ORIGIN_TOKEN` via Google Cloud Workload Identity Federation. External adopters cannot use this staging endpoint. The onboarding script either needs to (a) provide a way to configure a production API base URL, or (b) the `oz_client.py` must be updated to support configurable base URLs before external onboarding is viable. This is the most significant blocker for external adoption and should be resolved before or alongside this work.

2. **File acquisition strategy**: The simplest approach is to clone the full `oz-for-oss` repo into a temp directory and copy files. An alternative is `gh api` with the contents endpoint or `git archive --remote` for selective file fetching. The clone approach is more reliable across different git configurations and avoids dealing with API rate limits. The temp directory is cleaned up at the end.

3. **Idempotency of secret/variable creation**: `gh secret set` and `gh variable set` are inherently idempotent (they overwrite). The script should still check for existing values and warn the user before overwriting, since silently replacing credentials could break a working setup.

4. **Skill path references**: The `skill_spec()` helper in `oz_client.py` constructs skill paths as `{repo_slug}:.agents/skills/{name}/SKILL.md`. After onboarding, `repo_slug()` will resolve to the target repository's slug, so skill references will correctly point to the target repo's skills. No changes needed here.

5. **Triage bootstrap in shell**: The `bootstrap-issue-config` skill is designed to run as an Oz agent skill, not as a standalone script. For the initial version, the onboarding script should recommend the user trigger a bootstrap run via Oz rather than attempting to replicate the skill logic in Bash. A future iteration could extract the bootstrap logic into a standalone Python CLI.

6. **Workflow file customization**: Some workflows contain repository-specific references (e.g. Google Cloud Workload Identity Federation provider paths in the `auth` steps). Copied workflow files will not work without modification for repositories that use different cloud providers or authentication mechanisms. The onboarding script should warn about this and suggest reviewing the copied workflows.

7. **Testing strategy**: The script should be tested with a disposable test repository. Testing can use `gh repo create --private` to create a temporary repo, run the script, verify secrets/variables/files are in place, and then clean up. Consider adding a `--dry-run` flag that prints what the script would do without making changes.
