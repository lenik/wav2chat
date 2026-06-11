#!/usr/bin/env bash
# Build a single-file wav2chat.exe on Windows (Git Bash / MSYS2 / WSL + win Python).
#
# Usage (Git Bash / MSYS2, from repo root):
#   ./packager/windows.sh
#
# Options (environment variables):
#   PACKAGER_PYTHON=/c/Python312/python.exe
#   PACKAGER_VENV=$PWD/.packager-venv
#   PACKAGER_GUI=0                 CLI-only build (no wx)
#   PACKAGER_SKIP_INSTALL=1
#
# Prerequisites:
#   - Python 3.10+ for Windows
#   - ffmpeg on PATH (https://ffmpeg.org/download.html)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

packager_windows_check() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW* | MSYS* | CYGWIN*)
      ;;
    Linux)
      if [[ -z "${PACKAGER_PYTHON:-}" ]]; then
        cat >&2 <<'EOF'
On WSL, set PACKAGER_PYTHON to a Windows Python executable, e.g.:
  PACKAGER_PYTHON='/mnt/c/Python312/python.exe' ./packager/windows.sh
EOF
        exit 1
      fi
      ;;
    *)
      echo "warning: unexpected environment $(uname -s); continuing." >&2
      ;;
  esac

  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "warning: ffmpeg not found on PATH (needed at runtime)." >&2
  fi
}

main() {
  packager_windows_check
  packager_prepare
  packager_ensure_wx
  packager_require_wx
  packager_build
}

main "$@"
