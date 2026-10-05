#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-sa-east-1}"
PROFILE="${AWS_PROFILE:-cloud-media-workstations}"

if ! command -v aws >/dev/null 2>&1; then
  arch="$(uname -m)"
  case "$arch" in
    x86_64) url="https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" ;;
    aarch64|arm64) url="https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" ;;
    *) echo "UNSUPPORTED_ARCH=$arch" >&2; exit 2 ;;
  esac

  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl --fail --show-error --location "$url" -o "$tmp/awscliv2.zip"
  unzip -q "$tmp/awscliv2.zip" -d "$tmp"
  mkdir -p "$HOME/.local/bin" "$HOME/.local/share/aws-cli"
  "$tmp/aws/install" --install-dir "$HOME/.local/share/aws-cli" --bin-dir "$HOME/.local/bin" --update
fi

export PATH="$HOME/.local/bin:$PATH"
aws --version

echo "AUTH_MODE=AWS_IAM_IDENTITY_CENTER"
echo "PROFILE=$PROFILE"
echo "REGION=$AWS_REGION"
echo "Starting interactive SSO configuration; no long-lived key material is written by this script."
aws configure sso --profile "$PROFILE"

echo "Verify the temporary SSO session:"
aws sts get-caller-identity --profile "$PROFILE" --region "$AWS_REGION"
echo "AWS_AUTH=PASS"
echo "STS=PASS"
