#!/usr/bin/env bash
# Pre-download packager dependency wheels for offline / faster rebuilds.
#
# Usage:
#   ./packager/fetch-wheels.sh
#
# First run: installs deps into .packager-venv (slow once), then exports wheels
# from pip cache with --no-deps (no full dependency re-resolution).
#
# Later runs: skips export if .packager-wheelhouse/ already populated.
#
# Wheels: .packager-wheelhouse/   (PACKAGER_WHEELHOUSE)
# Pip cache: .packager-pip-cache/  (PACKAGER_PIP_CACHE)
#
# Force re-export all wheels:
#   PACKAGER_REFRESH_WHEELHOUSE=1 ./packager/fetch-wheels.sh
#
# Offline rebuild:
#   PACKAGER_OFFLINE=1 ./packager/linux.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

main() {
  export PIP_DISABLE_PIP_VERSION_CHECK=1
  export PACKAGER_REFRESH_WHEELHOUSE="${PACKAGER_REFRESH_WHEELHOUSE:-0}"
  packager_prepare
  echo
  echo "Done. Rebuild with: ./packager/linux.sh"
  echo "Offline rebuild:    PACKAGER_OFFLINE=1 ./packager/linux.sh"
}

main "$@"
