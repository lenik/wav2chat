#!/usr/bin/env bash
# Shared helpers for wav2chat PyInstaller packager scripts.

packager_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  printf '%s' "$here"
}

packager_python_version_ok() {
  "$1" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

packager_find_python() {
  local candidate
  if [[ -n "${PACKAGER_PYTHON:-}" ]]; then
    printf '%s' "$PACKAGER_PYTHON"
    return 0
  fi
  for candidate in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && packager_python_version_ok "$candidate"; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

packager_venv_python() {
  local venv="${1:-$VENV}"
  if [[ -x "$venv/Scripts/python.exe" ]]; then
    printf '%s' "$venv/Scripts/python.exe"
  elif [[ -x "$venv/bin/python" ]]; then
    printf '%s' "$venv/bin/python"
  else
    return 1
  fi
}

packager_activate_venv() {
  local venv="${1:-$VENV}"
  if [[ -f "$venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$venv/bin/activate"
  elif [[ -f "$venv/Scripts/activate" ]]; then
    # shellcheck disable=SC1091
    source "$venv/Scripts/activate"
  else
    echo "error: cannot activate venv at $venv" >&2
    exit 1
  fi
}

packager_prepare() {
  ROOT="$(packager_root)"
  cd "$ROOT"

  PYTHON="$(packager_find_python)" || {
    echo "error: Python 3.10+ is required (set PACKAGER_PYTHON to override)." >&2
    exit 1
  }

  VENV="${PACKAGER_VENV:-$ROOT/.packager-venv}"
  if [[ ! -d "$VENV" ]]; then
    echo "Creating packager venv: $VENV"
    # shellcheck disable=SC2086
    "$PYTHON" -m venv ${PACKAGER_VENV_CREATE_ARGS:-} "$VENV"
  fi

  packager_activate_venv "$VENV"
  PYTHON="$(packager_venv_python "$VENV")"

  if [[ "${PACKAGER_SKIP_INSTALL:-0}" != "1" ]]; then
    echo "Installing build dependencies..."
    "$PYTHON" -m pip install -U pip wheel setuptools
    "$PYTHON" -m pip install -e .
    "$PYTHON" -m pip install "pyinstaller>=6.0"
  fi

  export PACKAGER_GUI="${PACKAGER_GUI:-1}"
}

packager_build() {
  ROOT="$(packager_root)"
  cd "$ROOT"

  VENV="${PACKAGER_VENV:-$ROOT/.packager-venv}"
  PYTHON="$(packager_venv_python "$VENV")"

  echo "Building single-file executable (PACKAGER_GUI=$PACKAGER_GUI)..."
  "$PYTHON" -m PyInstaller \
    --clean \
    --noconfirm \
    "$ROOT/packager/wav2chat.spec"

  local exe="$ROOT/dist/wav2chat"
  if [[ -f "${exe}.exe" ]]; then
    exe="${exe}.exe"
  fi
  if [[ ! -f "$exe" ]]; then
    echo "error: expected output not found under dist/" >&2
    exit 1
  fi

  echo
  echo "Built: $exe"
  ls -lh "$exe"
  echo
  echo "Runtime notes:"
  echo "  - ffmpeg must be installed and on PATH"
  echo "  - FunASR / ModelScope models download on first use (~/.cache/modelscope)"
  if [[ "$PACKAGER_GUI" == "1" ]]; then
    echo "  - GUI: $exe (default when run with no arguments)"
    echo "  - CLI: $exe audio.m4a"
  else
    echo "  - CLI: $exe audio.m4a"
  fi
}

packager_ensure_wx() {
  if [[ "${PACKAGER_GUI:-1}" == "0" ]]; then
    return 0
  fi
  local venv="${PACKAGER_VENV:-$(packager_root)/.packager-venv}"
  local py
  py="$(packager_venv_python "$venv")" || return 1
  if "$py" -c "import wx" 2>/dev/null; then
    return 0
  fi
  echo "Installing wxPython into packager venv..."
  "$py" -m pip install wxPython
}
