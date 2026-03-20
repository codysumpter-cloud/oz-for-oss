#!/usr/bin/env bash

set -euo pipefail

channel="${INPUT_OZ_CHANNEL:-stable}"
version="${INPUT_OZ_VERSION:-latest}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "::error::Only Linux runners are supported."
  exit 1
fi

case "$channel" in
  stable)
    command_name="oz"
    ;;
  preview)
    command_name="oz-preview"
    ;;
  *)
    echo "::error::Unsupported Oz channel: $channel"
    exit 1
    ;;
esac

case "$(dpkg --print-architecture)" in
  amd64)
    arch="x86_64"
    deb_arch="amd64"
    ;;
  arm64)
    arch="aarch64"
    deb_arch="arm64"
    ;;
  *)
    echo "::error::Unsupported architecture: $(dpkg --print-architecture)"
    exit 1
    ;;
esac

if [[ "$version" == "latest" ]]; then
  resolution="$(
    node - "$channel" "$arch" <<'NODE'
const channel = process.argv[2];
const arch = process.argv[3];
const url = `https://app.warp.dev/download/cli?os=linux&package=deb&arch=${arch}&channel=${channel}`;

fetch(url, {
  method: 'GET',
  redirect: 'manual',
  headers: {
    'User-Agent': 'oz-action',
  },
}).then((response) => {
  if (response.status !== 301 && response.status !== 302) {
    throw new Error(`Expected redirect, got status ${response.status}`);
  }

  const location = response.headers.get('location');
  if (!location) {
    throw new Error('Redirect location header missing');
  }

  const parsed = new URL(location);
  const pathComponents = parsed.pathname.split('/').filter(Boolean);
  const resolvedVersion = pathComponents.length >= 2 ? pathComponents[1] : '';

  process.stdout.write(`${location}\n${resolvedVersion}\n`);
}).catch((error) => {
  console.error(error.message);
  process.exit(1);
});
NODE
  )" || {
    echo "::error::Unable to resolve the latest Oz release URL."
    exit 1
  }

  deb_url="$(printf '%s\n' "$resolution" | sed -n '1p')"
  resolved_version="$(printf '%s\n' "$resolution" | sed -n '2p')"

  if [[ -z "$deb_url" ]]; then
    echo "::error::Unable to resolve the latest Oz release URL."
    exit 1
  fi

  if [[ -n "$resolved_version" ]]; then
    version="$resolved_version"
  fi
else
  deb_version="${version#v}"
  version="v${deb_version}"
  deb_url="https://releases.warp.dev/${channel}/${version}/oz_${channel}_${deb_version}_${deb_arch}.deb"
fi

deb_path="${RUNNER_TEMP:-/tmp}/oz-${channel}.deb"
curl -fsSL "$deb_url" -o "$deb_path"

sudo dpkg -i "$deb_path" || true
sudo apt-get -f install -y

if ! command -v "$command_name" >/dev/null 2>&1; then
  echo "::error::Failed to install $command_name from $deb_url"
  exit 1
fi
