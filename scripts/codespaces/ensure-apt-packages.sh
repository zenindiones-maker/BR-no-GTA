#!/usr/bin/env bash
set -euo pipefail

if (( $# == 0 )); then
  echo "APT_PACKAGES=BLOCKED_EMPTY_SET"
  exit 2
fi

packages=("$@")

all_packages_ready() {
  local pkg
  for pkg in "${packages[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null |
      grep -q 'install ok installed' || return 1
  done
}

verify_packages() {
  local pkg
  for pkg in "${packages[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null |
      grep -q 'install ok installed' || {
        echo "APT_PACKAGE_MISSING=$pkg"
        return 1
      }
  done
}

if all_packages_ready; then
  echo "APT_PACKAGES=PASS_ALREADY_PRESENT"
  echo "APT_NETWORK_REFRESH=SKIPPED"
  echo "APT_PACKAGE_COUNT=${#packages[@]}"
  exit 0
fi

echo "APT_PACKAGES=INSTALL_OR_REPAIR"
echo "APT_NETWORK_REFRESH=REQUIRED"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}"
verify_packages || exit 20
sudo apt-get clean

echo "APT_PACKAGES=PASS_INSTALLED"
echo "APT_PACKAGE_COUNT=${#packages[@]}"
