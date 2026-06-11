#!/usr/bin/env bash
# Build a protected wav2chat bundle on Linux (PyInstaller onedir, fast startup).
#
# Usage:
#   ./packager/linux.sh
#
# Output (default): dist/wav2chat/wav2chat  + libraries alongside (no /tmp extract)
#
# Protection (application code only; third-party libs unchanged):
#   PACKAGER_PROTECT=cython   compile project .py to .so, remove sources (default)
#   PACKAGER_PROTECT=pyarmor  obfuscate with PyArmor (trial limits large files)
#   PACKAGER_PROTECT=none     no protection (debug)
#
# Size vs startup:
#   PACKAGER_ONEFILE=0        onedir, fast startup (default)
#   PACKAGER_ONEFILE=1        single file, slow cold start (not recommended)
#
# Fast iteration (spec / bundle debugging; not for release):
#   PACKAGER_PROTECT=none PACKAGER_SKIP_INSTALL=1 ./packager/linux.sh
#   PACKAGER_PYI_CLEAN=1 ./packager/linux.sh   # full PyInstaller rebuild when needed
#
# Linux GUI: isolated venv + symlink apt wxPython.
#
# Local wheels (faster rebuilds, optional offline):
#   ./packager/fetch-wheels.sh          # download once while online
#   ./packager/linux.sh                 # reuse .packager-wheelhouse/
#   PACKAGER_OFFLINE=1 ./packager/linux.sh
#
# Recommended system packages (Debian/Ubuntu):
#   sudo apt install python3-venv python3-dev python3-wxgtk4.0 ffmpeg build-essential

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

main() {
  packager_prepare
  packager_ensure_wx
  packager_require_wx
  packager_build
}

main "$@"
