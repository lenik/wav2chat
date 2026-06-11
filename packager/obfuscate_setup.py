"""Obfuscate staged wav2chat sources with PyArmor."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SKIP_DIR_NAMES = {
    "packager",
    "build",
    "dist",
    "doc",
    ".packager-venv",
    ".git",
    "__pycache__",
    "wav2chat.egg-info",
    ".pyarmor",
}


def _skip(path: Path, stage: Path) -> bool:
    try:
        rel = path.relative_to(stage)
    except ValueError:
        return True
    return any(part in SKIP_DIR_NAMES for part in rel.parts)


def collect_sources(stage: Path) -> list[Path]:
    return sorted(
        path for path in stage.rglob("*.py") if not _skip(path, stage)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", type=Path, help="Staged source tree")
    args = parser.parse_args(argv)

    stage = args.stage.resolve()
    sources = collect_sources(stage)
    if not sources:
        print("error: no Python sources found to obfuscate", file=sys.stderr)
        return 1

    out = stage.parent / "packager-obf-out"
    if out.exists():
        shutil.rmtree(out)

    cmd = [
        sys.executable,
        "-m",
        "pyarmor.cli",
        "gen",
        "-O",
        str(out),
        "-r",
        *[str(path) for path in sources],
    ]
    print(f"PyArmor: obfuscating {len(sources)} module(s)")
    subprocess.run(cmd, check=True)

    for path in out.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(out)
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    runtime_dirs = list(out.glob("pyarmor_runtime_*"))
    for runtime in runtime_dirs:
        target = stage / runtime.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(runtime, target)

    shutil.rmtree(out)
    print(f"PyArmor: wrote obfuscated sources into {stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
