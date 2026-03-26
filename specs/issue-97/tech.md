# Issue #97: Add onboarding script for Oz management layer

## Tech Spec

### Problem
There is no single entry point for adopting the Oz management layer in a new repository. A user must manually create GitHub Actions secrets and variables, install skill files, and configure workflow references — with no guided path. This spec describes the implementation of an interactive onboarding shell script that automates this process end-to-end.

### Current state
- All GitHub Actions workflows live in `.github/workflows/` (9 workflow files). Each workflow expects specific secrets and variables to be configured on the target repository.
- Required secrets (from workflow files): `WARP_API_KEY`, `GHA_APP_ID`, `GHA_PRIVATE_KEY`.
- Required variables (from workflow files): `WARP_AGENT_ENVIRONMENT_ID`. Optional per-workflow overrides: `WARP_AGENT_TRIAGE_ENVIRONMENT_ID`, `WARP_AGENT_SPEC_ENVIRONMENT_ID`, `WARP_AGENT_IMPLEMENTATION_ENVIRONMENT_ID`, `WARP_AGENT_REVIEW_ENVIRONMENT_ID`, `WARP_AGENT_ENFORCEMENT_ENVIRONMENT_ID`. Optional agent tuning: `WARP_AGENT_MODEL`, `WARP_AGENT_MCP`, `WARP_AGENT_PROFILE`.
- Workflows also use Google Cloud Workload Identity Federation to resolve a `STAGING_ORIGIN_TOKEN` at runtime. This is specific to the staging environment and will need to be addressed for external adopters.
- Skill files live in `.agents/skills/` (7 skills). These are referenced by workflows via the `skill_spec()` helper which constructs `{repo_slug}:.agents/skills/{name}/SKILL.md` paths.
- Python entrypoints are in `src/` (8 scripts). Shared library code is in `src/oz_workflows/` (8 modules). Dependencies are in `src/requirements.txt` (currently just `oz-sdk-python` from GitHub).
- Triage configuration lives in `.github/issue-triage/config.json` and `.github/STAKEHOLDERS`. The `bootstrap-issue-config` skill already automates generating these files.
- `README.md` documents local development setup but contains no onboarding instructions for external repositories.
- No existing onboarding tooling or bootstrap script exists in the repository.

### Proposed changes

#### 1. New file: `scripts/onboard.sh`

A standalone Bash script that drives the entire onboarding flow. Located at `scripts/onboard.sh` in the `oz-for-oss` repository. The recommended acquisition is to download and inspect before running:

```
curl -fsSL https://raw.githubusercontent.com/warpdotdev/oz-for-oss/main/scripts/onboard.sh -o onboard.sh
less onboard.sh   # inspect before running
bash onboard.sh
```

A `curl | bash` shorthand is available for convenience but carries the usual risks of piped execution (partial downloads, no inspection opportunity).

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
install_workflows()
copy_skills()
print_triage_guidance()
print_summary()

main() {
    info "Oz management layer onboarding"
    check_prerequisites
    configure_secrets
    configure_variables
    install_workflows
    copy_skills
    print_triage_guidance
    print_summary
}

main "$@"
```

**Step implementations:**

**`check_prerequisites()`**
- Verify `git` is installed and CWD is a git repository (`git rev-parse --is-inside-work-tree`).
- Verify `gh` is installed and authenticated (`gh auth status`).
- Derive `REPO_SLUG` from `gh repo view --json nameWithOwner -q .nameWithOwner` for use in subsequent `gh secret set` / `gh variable set` commands.
- Exit with a clear message if any check fails.

**`configure_secrets()`**
- For each of `WARP_API_KEY`, `GHA_APP_ID`, `GHA_PRIVATE_KEY`:
  - Print guidance on how to obtain the value (e.g. link to Warp team settings for the API key, link to GitHub App settings for App ID and private key).
  - Check if the secret already exists via `gh secret list` (parse output for the secret name).
  - If it exists, ask the user if they want to update it.
  - If not, prompt the user for the value.
  - For `GHA_PRIVATE_KEY`, accept a file path and read the file content.
  - Store via `gh secret set <NAME> --body-file <TMPFILE>` (or pipe via stdin) to avoid exposing values in the process list.

**`configure_variables()`**
- Prompt for `WARP_AGENT_ENVIRONMENT_ID` (required).
- Prompt for optional per-workflow environment IDs. Skip if the user presses Enter.
- Prompt for optional `WARP_AGENT_MODEL`, `WARP_AGENT_MCP`, `WARP_AGENT_PROFILE`.
- Store each non-empty value via `gh variable set <NAME> --body <VALUE>`.

**`install_workflows()`**
- Generate thin workflow files in the target repository's `.github/workflows/` directory.
- Each generated workflow triggers on the same events as its `oz-for-oss` counterpart but delegates execution via `uses: warpdotdev/oz-for-oss/.github/workflows/<name>.yml@main` with `secrets: inherit`.
- This approach keeps the Python source, dependencies, and workflow logic in `oz-for-oss` as the single source of truth. The target repository does not need its own copies of the Python code.
- For each workflow file, check if it already exists and prompt before overwriting.

**`copy_skills()`**
- Clone `oz-for-oss` into a temporary directory (or use `gh api` contents endpoint) and copy `.agents/skills/` into the target repository.
- Prompt before overwriting existing skill files.
- Clean up the temporary directory.

**`print_triage_guidance()`**
- Print documentation and instructions for bootstrapping triage configuration (`.github/issue-triage/config.json` and `.github/STAKEHOLDERS`).
- Suggest the user trigger a bootstrap run via Oz or configure triage manually.

**`print_summary()`**
- Print a table of what was configured (secrets, variables, files).
- Print remaining manual steps:
  - If GitHub App was not yet created, link to documentation.
  - Remind the user to enable GitHub Actions on the repo if not already enabled.
  - Suggest opening a test issue to trigger triage and verify the setup.

#### 2. Convert existing workflows to reusable workflows

The existing workflows in `.github/workflows/` need to be updated to support `workflow_call` triggers in addition to their current triggers. This allows external repositories to reference them with `uses:`. Each reusable workflow should accept `secrets: inherit` so the calling workflow can pass through its repository secrets.

This is a prerequisite for the onboarding script's `install_workflows()` step and may be tracked as a separate task.

#### 3. Modified file: `README.md`

Add an "Onboarding" or "Getting Started" section before the existing "Local development" section. Content:

```markdown
## Onboarding a new repository

To adopt the Oz management layer in your repository, run the onboarding script from the root of your target repository:

\`\`\`sh
curl -fsSL https://raw.githubusercontent.com/warpdotdev/oz-for-oss/main/scripts/onboard.sh -o onboard.sh
bash onboard.sh
\`\`\`

The script will guide you through:
1. Configuring Warp API keys and GitHub App credentials as repository secrets.
2. Setting Oz agent environment IDs as repository variables.
3. Installing workflow files that reference `oz-for-oss` reusable workflows.
4. Copying skill files into your repository.
5. Guidance on bootstrapping triage configuration.

### Prerequisites
- A Warp team with a team-scoped API key ([team settings](https://app.warp.dev/settings/team/api-keys))
- A GitHub App installed on your repository (for workflow authentication)
- `git` and `gh` (GitHub CLI) installed locally
```

#### 4. New file: `scripts/README.md`

Short documentation file for the `scripts/` directory explaining what `onboard.sh` does and how to test it locally.

### File change summary

New files:
- `scripts/onboard.sh` — main onboarding script
- `scripts/README.md` — documentation for the scripts directory

Modified files:
- `README.md` — add onboarding section
- `.github/workflows/*.yml` — add `workflow_call` triggers to make workflows reusable

### Risks and open technical questions

1. **Reusable workflow conversion**: The existing workflows need `workflow_call` triggers added to support external references. This requires careful testing to ensure the workflows still function correctly when called both directly (within `oz-for-oss`) and as reusable workflows (from external repos). Secrets and variables need to be passed through correctly.

2. **File acquisition strategy**: For copying skill files, the simplest approach is to clone the full `oz-for-oss` repo into a temp directory. An alternative is `gh api` with the contents endpoint or `git archive --remote` for selective file fetching. The clone approach is more reliable across different git configurations and avoids dealing with API rate limits. The temp directory is cleaned up at the end.

3. **Idempotency of secret/variable creation**: `gh secret set` and `gh variable set` are inherently idempotent (they overwrite). The script should still check for existing values and warn the user before overwriting, since silently replacing credentials could break a working setup.

4. **Skill path references**: The `skill_spec()` helper in `oz_client.py` constructs skill paths as `{repo_slug}:.agents/skills/{name}/SKILL.md`. After onboarding, `repo_slug()` will resolve to the target repository's slug, so skill references will correctly point to the target repo's skills. No changes needed here.

5. **Triage bootstrap**: The `bootstrap-issue-config` skill is designed to run as an Oz agent skill, not as a standalone script. The onboarding script provides documentation and instructions rather than attempting to replicate the skill logic in Bash.

6. **Testing strategy**: The script should be tested with a disposable test repository. Testing can use `gh repo create --private` to create a temporary repo, run the script, verify secrets/variables/files are in place, and then clean up. Consider adding a `--dry-run` flag that prints what the script would do without making changes.
