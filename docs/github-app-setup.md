# GitHub App Setup

All workflows in this repository authenticate with the GitHub API through a GitHub App installation. The app token is created at the start of each workflow run using the [`actions/create-github-app-token`](https://github.com/actions/create-github-app-token) action with two repository secrets: `GHA_APP_ID` and `GHA_PRIVATE_KEY`.

This guide walks through creating the app, configuring its permissions, installing it on your repository, and populating the required secrets.

## 1. Create the GitHub App

1. Go to **Settings → Developer settings → GitHub Apps → New GitHub App** on your GitHub account or organization.
   - Direct link for a personal account: `https://github.com/settings/apps/new`
   - Direct link for an organization: `https://github.com/organizations/<ORG>/settings/apps/new`

2. Fill in the basic fields:
   - **GitHub App name** — choose a descriptive name (e.g. `oz-workflows-<your-repo>`). The name must be globally unique on GitHub.
   - **Homepage URL** — any valid URL (e.g. your repository URL).
   - **Webhook** — uncheck **Active**. The workflows do not rely on app webhooks.

3. Under **Permissions**, expand **Repository permissions** and set:

   | Permission       | Access         |
   |------------------|----------------|
   | **Contents**     | Read and write |
   | **Issues**       | Read and write |
   | **Pull requests**| Read and write |
   | **Metadata**     | Read-only      |

   No organization or account permissions are needed.

   > **Why these permissions?** The workflows read and write issue comments, labels, and assignees (Issues); create branches and read file contents (Contents); open, update, and review pull requests (Pull requests). Metadata read access is required for all GitHub Apps.

4. Under **Where can this GitHub App be installed?**, select **Only on this account**.

5. Click **Create GitHub App**.

## 2. Generate a private key

1. After creation you are redirected to the app settings page. Note the **App ID** displayed near the top — you will need it later.

2. Scroll to the **Private keys** section and click **Generate a private key**. Your browser downloads a `.pem` file.

3. Store this file securely. You will paste its contents into a repository secret in step 4.

## 3. Install the app on your repository

1. From the app settings page, click **Install App** in the left sidebar.

2. Choose the account or organization that owns your repository.

3. Select **Only select repositories** and pick the repository where the workflows run.

4. Click **Install**.

## 4. Add repository secrets

The workflows expect two repository secrets:

- **`GHA_APP_ID`** — the numeric App ID from step 2.
- **`GHA_PRIVATE_KEY`** — the full contents of the `.pem` file from step 2.

### Option A: GitHub web UI

1. Go to **Settings → Secrets and variables → Actions** in your repository.
2. Click **New repository secret**.
3. Create `GHA_APP_ID` with the App ID value.
4. Create `GHA_PRIVATE_KEY` by pasting the entire contents of the `.pem` file (including the `-----BEGIN RSA PRIVATE KEY-----` and `-----END RSA PRIVATE KEY-----` lines).

### Option B: `gh` CLI

```sh
# Set the app ID
gh secret set GHA_APP_ID --body "<YOUR_APP_ID>"

# Set the private key from the downloaded .pem file
gh secret set GHA_PRIVATE_KEY < /path/to/your-app.private-key.pem
```

### Option C: Bootstrap script

This repository includes a helper script that wraps the `gh` commands above:

```sh
scripts/setup-github-app-secrets.sh --app-id <APP_ID> --private-key /path/to/key.pem
```

See [scripts/setup-github-app-secrets.sh](../scripts/setup-github-app-secrets.sh) for details.

## 5. Other required secrets and variables

Beyond the GitHub App, the workflows also reference:

| Secret / Variable | Type | Purpose |
|---|---|---|
| `WARP_API_KEY` | Secret | Authenticates with the Warp API to run Oz agents. |
| `WARP_AGENT_PROFILE` | Variable (optional) | Oz agent profile override. |
| `WARP_AGENT_MODEL` | Variable (optional) | Oz agent model override. |
| `WARP_AGENT_MCP` | Variable (optional) | Oz agent MCP configuration. |
| `WARP_AGENT_ENVIRONMENT_ID` | Variable (optional) | Default Oz cloud environment ID. |
| `WARP_AGENT_TRIAGE_ENVIRONMENT_ID` | Variable (optional) | Environment ID for triage runs. |
| `WARP_AGENT_SPEC_ENVIRONMENT_ID` | Variable (optional) | Environment ID for spec creation runs. |
| `WARP_AGENT_IMPLEMENTATION_ENVIRONMENT_ID` | Variable (optional) | Environment ID for implementation runs. |
| `WARP_AGENT_REVIEW_ENVIRONMENT_ID` | Variable (optional) | Environment ID for PR review runs. |
| `WARP_AGENT_ENFORCEMENT_ENVIRONMENT_ID` | Variable (optional) | Environment ID for PR enforcement runs. |

Set secrets under **Settings → Secrets and variables → Actions → Secrets** and variables under **Settings → Secrets and variables → Actions → Variables**.

## Verifying the setup

After completing the steps above, trigger any workflow manually (e.g. the triage workflow via `workflow_dispatch`) or open a test issue. A successful run confirms that the app token is being created correctly. If the `Create GitHub App token` step fails, double-check that:

- The App ID matches the installed app.
- The private key is the full `.pem` contents (not just the path).
- The app is installed on the correct repository.
- The app has the required permissions listed in step 1.
