#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "CODEX_SANDBOX_HOST_POLICY=FAIL"
  echo "CODEX_SANDBOX_HOST_REASON=NON_LINUX"
  exit 1
fi

current_userns="$(sysctl -n kernel.unprivileged_userns_clone 2>/dev/null || true)"
if [[ -n "${current_userns}" && "${current_userns}" != "1" ]]; then
  sudo sysctl -w kernel.unprivileged_userns_clone=1 >/dev/null
fi

max_userns="$(sysctl -n user.max_user_namespaces 2>/dev/null || true)"
if [[ -z "${max_userns}" || ! "${max_userns}" =~ ^[0-9]+$ || "${max_userns}" -le 0 ]]; then
  echo "CODEX_SANDBOX_HOST_POLICY=FAIL"
  echo "CODEX_SANDBOX_HOST_REASON=USER_NAMESPACE_LIMIT"
  exit 1
fi

current_apparmor="$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || true)"
if [[ -n "${current_apparmor}" && "${current_apparmor}" != "0" ]]; then
  sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 >/dev/null
fi

verified_userns="$(sysctl -n kernel.unprivileged_userns_clone 2>/dev/null || true)"
verified_apparmor="$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || true)"
verified_max="$(sysctl -n user.max_user_namespaces 2>/dev/null || true)"

if [[ -n "${verified_userns}" && "${verified_userns}" != "1" ]]; then
  echo "CODEX_SANDBOX_HOST_POLICY=FAIL"
  echo "CODEX_SANDBOX_HOST_REASON=UNPRIVILEGED_USERNS_DISABLED"
  exit 1
fi
if [[ -n "${verified_apparmor}" && "${verified_apparmor}" != "0" ]]; then
  echo "CODEX_SANDBOX_HOST_POLICY=FAIL"
  echo "CODEX_SANDBOX_HOST_REASON=APPARMOR_USERNS_RESTRICTED"
  exit 1
fi
if [[ -z "${verified_max}" || ! "${verified_max}" =~ ^[0-9]+$ || "${verified_max}" -le 0 ]]; then
  echo "CODEX_SANDBOX_HOST_POLICY=FAIL"
  echo "CODEX_SANDBOX_HOST_REASON=USER_NAMESPACE_LIMIT"
  exit 1
fi

if ! unshare -Ur /bin/true >/dev/null 2>&1; then
  echo "CODEX_SANDBOX_HOST_POLICY=FAIL"
  echo "CODEX_SANDBOX_HOST_REASON=USER_NAMESPACE_PROBE_FAILED"
  exit 1
fi

echo "CODEX_SANDBOX_HOST_POLICY=PASS"
echo "CODEX_SANDBOX_USERNS=PASS"
echo "CODEX_SANDBOX_APPARMOR_GATE=PASS"
echo "CODEX_SANDBOX_MAX_USER_NAMESPACES=PASS"
