#!/usr/bin/env bash
# Build a single-file wav2chat executable on Linux (PyInstaller onefile).
#
# Usage:
#   ./packager/linux.sh
#
# Options (environment variables):
#   PACKAGER_PYTHON=python3.11     Python used to create the venv
#   PACKAGER_VENV=$PWD/.packager-venv
#   PACKAGER_VENV_CREATE_ARGS="--system-site-packages"   use system wx on Debian
#   PACKAGER_GUI=0                 CLI-only build (smaller, no wx)
#   PACKAGER_SKIP_INSTALL=1        reuse an already-prepared venv
#
# Recommended system packages (Debian/Ubuntu):
#   sudo apt install python3-venv python3-dev python3-wxgtk4.0 ffmpeg build-essential

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

packager_linux_check_wx() {
  if [[ "${PACKAGER_GUI:-1}" == "0" ]]; then
    return 0
  fi

  local py="${PACKAGER_PYTHON:-}"
  if [[ -z "$py" ]]; then
    py="$(packager_find_python || true)"
  fi
  if [[ -n "$py" ]] && "$py" -c "import wx" 2>/dev/null; then
    return 0
  fi

  cat >&2 <<'EOF'
wxPython is required to bundle the GUI (wav2chat -g).

Debian/Ubuntu (recommended):
  sudo apt install python3-wxgtk4.0
  PACKAGER_VENV_CREATE_ARGS="--system-site-packages" ./packager/linux.sh

Or install wx into the packager venv:
  pip install wxPython

CLI-only build (no GUI):
  PACKAGER_GUI=0 ./packager/linux.sh
EOF
  exit 1
}

main() {
  packager_linux_check_wx
  packager_prepare
  packager_build
}

main "$@"
