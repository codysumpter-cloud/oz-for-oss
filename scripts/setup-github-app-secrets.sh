#!/usr/bin/env bash
# setup-github-app-secrets.sh — populate the GHA_APP_ID and GHA_PRIVATE_KEY
# repository secrets required by the oz-for-oss workflows.
#
# Prerequisites:
#   - The `gh` CLI must be installed and authenticated (`gh auth login`).
#   - You must have admin access to the target repository.
#
# Usage:
#   scripts/setup-github-app-secrets.sh --app-id <APP_ID> --private-key <PATH_TO_PEM>
#
# The script validates inputs, then calls `gh secret set` for each secret.
# See docs/github-app-setup.md for the full setup walkthrough.

set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --app-id <APP_ID> --private-key <PATH_TO_PEM> [--repo <OWNER/REPO>]

Required:
  --app-id        Numeric App ID of the GitHub App.
  --private-key   Path to the .pem private key file.

Optional:
  --repo          Target repository in OWNER/REPO format.
                  Defaults to the repository in the current directory.
  -h, --help      Show this help message.
EOF
}

APP_ID=""
PRIVATE_KEY_PATH=""
REPO_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-id)
      APP_ID="$2"
      shift 2
      ;;
    --private-key)
      PRIVATE_KEY_PATH="$2"
      shift 2
      ;;
    --repo)
      REPO_FLAG="--repo $2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown option $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# ---------- Validation ----------

if [[ -z "$APP_ID" ]]; then
  echo "Error: --app-id is required." >&2
  usage >&2
  exit 1
fi

if ! [[ "$APP_ID" =~ ^[0-9]+$ ]]; then
  echo "Error: --app-id must be a numeric value (got '$APP_ID')." >&2
  exit 1
fi

if [[ -z "$PRIVATE_KEY_PATH" ]]; then
  echo "Error: --private-key is required." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "$PRIVATE_KEY_PATH" ]]; then
  echo "Error: private key file not found at '$PRIVATE_KEY_PATH'." >&2
  exit 1
fi

if ! command -v gh &>/dev/null; then
  echo "Error: the 'gh' CLI is not installed. Install it from https://cli.github.com/" >&2
  exit 1
fi

# ---------- Set secrets ----------

echo "Setting GHA_APP_ID..."
# shellcheck disable=SC2086
gh secret set GHA_APP_ID --body "$APP_ID" $REPO_FLAG

echo "Setting GHA_PRIVATE_KEY..."
# shellcheck disable=SC2086
gh secret set GHA_PRIVATE_KEY < "$PRIVATE_KEY_PATH" $REPO_FLAG

echo ""
echo "Done. Both GHA_APP_ID and GHA_PRIVATE_KEY have been set."
echo "See docs/github-app-setup.md for the remaining setup steps."
