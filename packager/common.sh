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

packager_python_has_wx() {
  "$1" -c "import wx" >/dev/null 2>&1
}

packager_resolve_python() {
  local py="$1"
  if [[ ! -x "$py" ]]; then
    py="$(command -v "$py")" || return 1
  fi
  printf '%s' "$py"
}

packager_system_wx_dir() {
  local host_py="$1"
  if packager_python_has_wx "$host_py"; then
    "$host_py" -c "import wx, os; print(os.path.dirname(os.path.realpath(wx.__file__)))"
    return 0
  fi
  local ver
  ver="$("$host_py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
  local base
  for base in "/usr/lib/python${ver}/dist-packages" "/usr/lib/python3/dist-packages"; do
    if [[ -d "$base/wx" ]]; then
      printf '%s/wx' "$base"
      return 0
    fi
  done
  return 1
}

packager_find_python_with_wx() {
  local candidate resolved
  if [[ -n "${PACKAGER_PYTHON:-}" ]]; then
    if resolved="$(packager_resolve_python "$PACKAGER_PYTHON")" \
      && packager_python_version_ok "$resolved" \
      && packager_python_has_wx "$resolved"; then
      printf '%s' "$resolved"
      return 0
    fi
    return 1
  fi
  for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && resolved="$(packager_resolve_python "$candidate")" \
      && packager_python_version_ok "$resolved" \
      && packager_python_has_wx "$resolved"; then
      printf '%s' "$resolved"
      return 0
    fi
  done
  return 1
}

packager_find_python() {
  local candidate
  if [[ -n "${PACKAGER_PYTHON:-}" ]]; then
    printf '%s' "$PACKAGER_PYTHON"
    return 0
  fi
  for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
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

packager_venv_has_system_site_packages() {
  local venv="$1"
  [[ -f "$venv/pyvenv.cfg" ]] \
    && grep -q 'include-system-site-packages = true' "$venv/pyvenv.cfg"
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

packager_uses_system_site_packages() {
  [[ "${PACKAGER_VENV_CREATE_ARGS:-}" == *system-site-packages* ]]
}

packager_wheelhouse_dir() {
  printf '%s' "${PACKAGER_WHEELHOUSE:-$(packager_root)/.packager-wheelhouse}"
}

packager_pip_cache_dir() {
  printf '%s' "${PACKAGER_PIP_CACHE:-$(packager_root)/.packager-pip-cache}"
}

packager_wheelhouse_has_wheels() {
  local wheelhouse
  wheelhouse="$(packager_wheelhouse_dir)"
  [[ -d "$wheelhouse" ]] && compgen -G "$wheelhouse/*.whl" >/dev/null 2>&1
}

packager_pip() {
  local py="$1"
  shift
  local wheelhouse cache_dir extra=()
  wheelhouse="$(packager_wheelhouse_dir)"
  cache_dir="$(packager_pip_cache_dir)"
  mkdir -p "$wheelhouse" "$cache_dir"

  if [[ "${PACKAGER_OFFLINE:-0}" == "1" ]]; then
    if ! packager_wheelhouse_has_wheels; then
      echo "error: PACKAGER_OFFLINE=1 but no wheels in $wheelhouse" >&2
      echo "Run ./packager/fetch-wheels.sh while online first." >&2
      exit 1
    fi
    extra+=(--no-index --find-links "$wheelhouse")
  else
    extra+=(--cache-dir "$cache_dir" --find-links "$wheelhouse" --prefer-binary)
  fi

  if packager_uses_system_site_packages; then
    extra+=(--no-warn-conflicts)
  fi
  local packager_constraints
  packager_constraints="$(packager_root)/packager/constraints-packager.txt"
  if [[ -f "$packager_constraints" ]]; then
    extra+=(-c "$packager_constraints")
  fi
  "$py" -m pip install "${extra[@]}" "$@"
}

packager_pip_cpu_index_args() {
  if [[ -z "$(packager_debian_constraints "$1")" ]] \
    && [[ "${PACKAGER_TORCH:-cpu}" == "cpu" ]]; then
    printf '%s\n' \
      --index-url https://download.pytorch.org/whl/cpu \
      --extra-index-url https://pypi.org/simple
  fi
}

packager_install_runtime_deps() {
  local py="$1"
  local -a index_args=()
  if mapfile -t index_args < <(packager_pip_cpu_index_args "$py"); then
    :
  fi
  if ((${#index_args[@]})); then
    packager_pip "$py" "${index_args[@]}" \
      "funasr>=1.0.0" "modelscope>=1.9.0" "coverage>=7.6.1" torch torchaudio
  else
    packager_pip "$py" "funasr>=1.0.0" "modelscope>=1.9.0" "coverage>=7.6.1" torch torchaudio
  fi
}

packager_install_editable() {
  local py="$1"
  local dir="$2"
  local constraints
  constraints="$(packager_debian_constraints "$py")"

  if [[ -n "$constraints" ]]; then
    echo "Using Debian system-torch constraints: $constraints"
    packager_pip "$py" -e "$dir" -c "$constraints"
    return 0
  fi

  echo "Installing runtime dependencies..."
  packager_install_runtime_deps "$py"
  echo "Installing editable project from $dir (no-deps)..."
  packager_pip "$py" -e "$dir" --no-deps
}

packager_pip_download() {
  local py="$1"
  shift
  local wheelhouse cache_dir
  local -a download=()
  wheelhouse="$(packager_wheelhouse_dir)"
  cache_dir="$(packager_pip_cache_dir)"
  mkdir -p "$wheelhouse" "$cache_dir"
  download=(
    "$py" -m pip download
    -d "$wheelhouse"
    --cache-dir "$cache_dir"
    --find-links "$wheelhouse"
    "--exists-action" "i"
    --prefer-binary
  )
  "${download[@]}" "$@"
}

packager_export_wheels_from_venv() {
  local py="$1"
  local wheelhouse cache_dir
  local -a index_args=() packages=()
  wheelhouse="$(packager_wheelhouse_dir)"
  cache_dir="$(packager_pip_cache_dir)"
  mkdir -p "$wheelhouse" "$cache_dir"

  if ! "$py" -c "import funasr, torch, modelscope" >/dev/null 2>&1; then
    echo "error: packager venv is missing runtime deps; cannot export wheels" >&2
    return 1
  fi

  mapfile -t packages < <(
    "$py" -m pip freeze | grep -E '^[A-Za-z0-9_.-]+==' | cut -d= -f1
  )
  if ((${#packages[@]} == 0)); then
    echo "error: pip freeze returned no packages" >&2
    return 1
  fi

  mapfile -t index_args < <(packager_pip_cpu_index_args "$py")

  echo "Exporting ${#packages[@]} installed packages to $wheelhouse (cache + skip existing)..."
  if ((${#index_args[@]})); then
    packager_pip_download "$py" "${index_args[@]}" --no-deps "${packages[@]}"
  else
    packager_pip_download "$py" --no-deps "${packages[@]}"
  fi
}

packager_refresh_wheelhouse() {
  local py="$1"
  local wheelhouse
  wheelhouse="$(packager_wheelhouse_dir)"
  mkdir -p "$wheelhouse" "$(packager_pip_cache_dir)"

  if [[ "${PACKAGER_REFRESH_WHEELHOUSE:-0}" != "1" ]] \
    && packager_wheelhouse_has_wheels; then
    local count
    count="$(find "$wheelhouse" -maxdepth 1 -name '*.whl' 2>/dev/null | wc -l)"
    echo "Local wheelhouse: $wheelhouse ($count wheels, use PACKAGER_REFRESH_WHEELHOUSE=1 to re-export)"
    return 0
  fi

  packager_export_wheels_from_venv "$py"

  local count
  count="$(find "$wheelhouse" -maxdepth 1 -name '*.whl' 2>/dev/null | wc -l)"
  echo "Wheelhouse ready: $wheelhouse ($count wheels)"
}

# Debian apt wxPython has no pip wheels; link the system package into an isolated venv
# so pip does not see unrelated system tools (awscli, etc.).
packager_link_system_wx() {
  local venv_py="$1"
  local wx_dir="${2:-${PACKAGER_WX_DIR:-}}"
  if packager_python_has_wx "$venv_py"; then
    return 0
  fi
  if [[ -z "$wx_dir" ]]; then
    echo "error: PACKAGER_WX_DIR not set (system wx path unknown)" >&2
    return 1
  fi
  if [[ ! -d "$wx_dir" ]]; then
    echo "error: system wx not found at $wx_dir" >&2
    return 1
  fi

  local site
  site="$("$venv_py" -c "import site; print(site.getsitepackages()[0])")"
  echo "Linking apt wxPython into isolated venv: $wx_dir -> $site/wx"
  ln -sfn "$wx_dir" "$site/wx"
  packager_python_has_wx "$venv_py"
}

packager_configure_linux_gui_python() {
  [[ "${PACKAGER_GUI:-1}" == "1" ]] || return 0
  [[ "$(uname -s)" == Linux ]] || return 0

  local host_py wx_dir
  if ! host_py="$(packager_find_python_with_wx)"; then
    cat >&2 <<'EOF'
Linux GUI build requires apt wxPython (pip cannot build wx here).

  sudo apt install python3-wxgtk4.0

Or build CLI-only:
  PACKAGER_GUI=0 ./packager/linux.sh
EOF
    exit 1
  fi
  if ! wx_dir="$(packager_system_wx_dir "$host_py")"; then
    echo "error: could not locate apt wx files for $host_py" >&2
    exit 1
  fi

  PYTHON="$host_py"
  PACKAGER_WX_HOST_PYTHON="$host_py"
  PACKAGER_WX_DIR="$wx_dir"
  export PACKAGER_WX_HOST_PYTHON PACKAGER_WX_DIR
  echo "Linux GUI: venv Python $host_py; apt wx at $wx_dir"
}

packager_debian_system_torch() {
  local py="$1"
  packager_uses_system_site_packages || return 1
  "$py" -c "import torch" >/dev/null 2>&1 || return 1
  local version
  version="$("$py" -c "import torch; print(torch.__version__)")"
  [[ "$version" == *debian* || "$version" == *+deb* ]]
}

packager_debian_constraints() {
  local py="$1"
  if packager_debian_system_torch "$py"; then
    printf '%s/packager/constraints-debian-system.txt' "$(packager_root)"
  fi
}

packager_reconcile_debian_torch_deps() {
  local py="$1"
  local constraints
  constraints="$(packager_debian_constraints "$py")"
  [[ -n "$constraints" ]] || return 0
  echo "Reconciling Debian system torch dependency pins..."
  packager_pip "$py" -c "$constraints" 'sympy==1.13.1'
}

packager_reconcile_setuptools() {
  local py="$1"
  "$py" -c "import torch" >/dev/null 2>&1 || return 0
  echo "Ensuring setuptools is compatible with torch (<82)..."
  packager_pip "$py" "setuptools>=61,<82"
}

packager_install_project() {
  packager_install_editable "$1" "."
}

packager_prepare() {
  ROOT="$(packager_root)"
  cd "$ROOT"
  export PIP_DISABLE_PIP_VERSION_CHECK=1

  PYTHON="$(packager_find_python)" || {
    echo "error: Python 3.10+ is required (set PACKAGER_PYTHON to override)." >&2
    exit 1
  }

  packager_configure_linux_gui_python

  VENV="${PACKAGER_VENV:-$ROOT/.packager-venv}"
  if [[ -d "$VENV" ]] && [[ "${PACKAGER_GUI:-1}" == "1" ]]; then
    existing_py="$(packager_venv_python "$VENV" 2>/dev/null || true)"
    if [[ -n "$existing_py" ]] && ! packager_python_has_wx "$existing_py"; then
      echo "Removing packager venv (wxPython not available)."
      rm -rf "$VENV"
    elif [[ "$(uname -s)" == Linux ]] \
      && ! packager_uses_system_site_packages \
      && packager_venv_has_system_site_packages "$VENV"; then
      echo "Removing legacy system-site-packages venv (isolated venv + apt wx link)."
      rm -rf "$VENV"
    fi
  fi

  if [[ ! -d "$VENV" ]]; then
    echo "Creating packager venv: $VENV"
    # shellcheck disable=SC2086
    "$PYTHON" -m venv ${PACKAGER_VENV_CREATE_ARGS:-} "$VENV"
  fi

  if [[ "${PACKAGER_GUI:-1}" == "1" ]] \
    && [[ "$(uname -s)" == Linux ]] \
    && ! packager_uses_system_site_packages \
    && [[ -n "${PACKAGER_WX_DIR:-}" ]]; then
    packager_link_system_wx "$(packager_venv_python "$VENV")" "$PACKAGER_WX_DIR"
  fi

  packager_activate_venv "$VENV"
  PYTHON="$(packager_venv_python "$VENV")"

  if [[ "${PACKAGER_SKIP_INSTALL:-0}" != "1" ]]; then
    echo "Installing build dependencies..."
    if packager_uses_system_site_packages; then
      packager_pip "$PYTHON" pip wheel
    else
      packager_pip "$PYTHON" -U pip wheel
    fi
    packager_install_project "$PYTHON"
    packager_pip "$PYTHON" "pyinstaller>=6.0"
    packager_reconcile_setuptools "$PYTHON"
    packager_reconcile_debian_torch_deps "$PYTHON"
    packager_refresh_wheelhouse "$PYTHON"
  fi

  export PACKAGER_GUI="${PACKAGER_GUI:-1}"
  export PACKAGER_ONEFILE="${PACKAGER_ONEFILE:-0}"
  export PACKAGER_TORCH="${PACKAGER_TORCH:-cpu}"
  export PACKAGER_PROTECT="${PACKAGER_PROTECT:-cython}"
}

packager_stage_release() {
  local root="$1"
  local stage="$root/build/packager_stage"
  rm -rf "$stage"
  mkdir -p "$stage/packager"
  rsync -a \
    --exclude '.packager-venv' \
    --exclude 'build' \
    --exclude 'dist' \
    --exclude '.git' \
    --exclude 'packager' \
    --exclude '__pycache__' \
    --exclude '.pyarmor' \
    --exclude 'wav2chat.egg-info' \
    --exclude 'data' \
    "$root/" "$stage/"
  cp "$root/packager/_entry.py" "$stage/packager/"
  printf '%s' "$stage"
}

packager_protect_stage() {
  local root="$1"
  local py="$2"
  local stage="$3"
  local mode="${PACKAGER_PROTECT:-cython}"

  case "$mode" in
    none)
      echo "Protection: disabled (PACKAGER_PROTECT=none)"
      return 0
      ;;
    cython)
      echo "Protection: compiling application sources to native extensions (Cython)..."
      packager_pip "$py" cython
      "$py" "$root/packager/cythonize_setup.py" "$stage" --strip-py
      ;;
    pyarmor)
      echo "Protection: obfuscating application sources (PyArmor)..."
      packager_pip "$py" pyarmor
      "$py" "$root/packager/obfuscate_setup.py" "$stage"
      ;;
    *)
      echo "error: unknown PACKAGER_PROTECT=$mode (use cython, pyarmor, or none)" >&2
      exit 1
      ;;
  esac
}

packager_build() {
  ROOT="$(packager_root)"
  cd "$ROOT"

  VENV="${PACKAGER_VENV:-$ROOT/.packager-venv}"
  PYTHON="$(packager_venv_python "$VENV")"
  export PACKAGER_GUI="${PACKAGER_GUI:-1}"
  export PACKAGER_ONEFILE="${PACKAGER_ONEFILE:-0}"
  export PACKAGER_TORCH="${PACKAGER_TORCH:-cpu}"
  export PACKAGER_PROTECT="${PACKAGER_PROTECT:-cython}"

  if [[ "${PACKAGER_GUI}" == "1" ]]; then
    echo "PyInstaller: GUI enabled (PACKAGER_GUI=1, bundling wx)"
  else
    echo "PyInstaller: CLI-only (PACKAGER_GUI=0, wx excluded; -g will not work)"
  fi

  local stage=""
  if [[ "${PACKAGER_PROTECT}" != "none" ]]; then
    stage="$(packager_stage_release "$ROOT")"
    packager_protect_stage "$ROOT" "$PYTHON" "$stage"
    echo "Installing protected staging tree for PyInstaller..."
    packager_pip "$PYTHON" -e "$stage" --no-deps
  fi

  if [[ "$PACKAGER_ONEFILE" == "1" ]]; then
    echo "Building one-file bundle (slow cold start; not recommended)..."
  else
    echo "Building onedir bundle (fast startup; PACKAGER_PROTECT=$PACKAGER_PROTECT)..."
  fi

  local -a pyi_args=(--noconfirm)
  if [[ "${PACKAGER_PYI_CLEAN:-0}" == "1" ]]; then
    pyi_args=(--clean "${pyi_args[@]}")
    echo "PyInstaller: full rebuild (--clean)"
  else
    echo "PyInstaller: incremental rebuild (set PACKAGER_PYI_CLEAN=1 for --clean)"
  fi

  "$PYTHON" -m PyInstaller \
    "${pyi_args[@]}" \
    "$ROOT/packager/wav2chat.spec"

  if [[ -n "$stage" ]]; then
    echo "Restoring editable install from source tree..."
    packager_pip "$PYTHON" -e "$ROOT" --no-deps
  fi

  local exe dir
  if [[ "$PACKAGER_ONEFILE" == "1" ]]; then
    exe="$ROOT/dist/wav2chat"
    [[ -f "${exe}.exe" ]] && exe="${exe}.exe"
  else
    exe="$ROOT/dist/wav2chat/wav2chat"
    [[ -f "${exe}.exe" ]] && exe="${exe}.exe"
  fi
  if [[ ! -f "$exe" ]]; then
    echo "error: expected output not found under dist/" >&2
    exit 1
  fi

  echo
  echo "Built: $exe"
  ls -lh "$exe"
  if [[ "$PACKAGER_ONEFILE" != "1" ]]; then
    dir="$(dirname "$exe")"
    echo "Bundle directory: $dir ($(du -sh "$dir" | cut -f1))"
    echo "Distribute: tar -C dist -czf wav2chat-linux.tar.gz wav2chat"
  fi
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
  if [[ "$PACKAGER_ONEFILE" == "1" ]]; then
    echo "  - Tip: PACKAGER_ONEFILE=0 yields faster startup (onedir default)"
  fi
}

packager_ensure_wx() {
  if [[ "${PACKAGER_GUI:-1}" == "0" ]]; then
    return 0
  fi
  local venv="${PACKAGER_VENV:-$(packager_root)/.packager-venv}"
  local py
  py="$(packager_venv_python "$venv")" || return 1
  if packager_python_has_wx "$py"; then
    return 0
  fi

  if [[ "$(uname -s)" == Linux ]] && [[ -n "${PACKAGER_WX_DIR:-}" ]]; then
    packager_link_system_wx "$py" "$PACKAGER_WX_DIR"
    return 0
  fi

  echo "Installing wxPython via pip..."
  packager_pip "$py" wxPython
}

packager_require_wx() {
  if [[ "${PACKAGER_GUI:-1}" == "0" ]]; then
    return 0
  fi
  local venv="${PACKAGER_VENV:-$(packager_root)/.packager-venv}"
  local py
  py="$(packager_venv_python "$venv")" || return 1
  if packager_python_has_wx "$py"; then
    return 0
  fi

  cat >&2 <<'EOF'
wxPython is required to bundle the GUI.

Linux (Debian/Ubuntu):
  sudo apt install python3-wxgtk4.0
  rm -rf .packager-venv
  ./packager/linux.sh

CLI-only build:
  PACKAGER_GUI=0 ./packager/linux.sh
EOF
  exit 1
}
