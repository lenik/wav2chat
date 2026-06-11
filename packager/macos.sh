#!/usr/bin/env bash
# Build a single-file wav2chat executable on macOS (PyInstaller onefile).
#
# Usage:
#   ./packager/macos.sh
#
# Options (environment variables):
#   PACKAGER_PYTHON=python3.12
#   PACKAGER_VENV=$PWD/.packager-venv
#   PACKAGER_GUI=0                 CLI-only build (no wx)
#   PACKAGER_SKIP_INSTALL=1
#
# Prerequisites:
#   - Xcode command-line tools (clang)
#   - Homebrew ffmpeg recommended: brew install ffmpeg

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

packager_macos_check() {
  if ! command -v clang >/dev/null 2>&1; then
    echo "error: Xcode command-line tools are required (xcode-select --install)." >&2
    exit 1
  fi

  if [[ "${PACKAGER_GUI:-1}" == "1" ]]; then
    local py="${PACKAGER_PYTHON:-}"
    if [[ -z "$py" ]]; then
      py="$(packager_find_python || true)"
    fi
    if [[ -n "$py" ]] && ! "$py" -c "import wx" 2>/dev/null; then
      echo "wxPython not found; it will be installed into the packager venv via pip."
    fi
  fi

  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "warning: ffmpeg not found on PATH (needed at runtime). Install with: brew install ffmpeg" >&2
  fi
}

main() {
  packager_macos_check
  packager_prepare
  packager_ensure_wx
  packager_build
  echo "Optional: codesign the binary for Gatekeeper:"
  echo "  codesign --force --deep --sign - dist/wav2chat"
}

main "$@"
