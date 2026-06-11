"""Compile staged wav2chat sources to native extensions (run from packager)."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from setuptools import Extension, setup

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
    if any(part in SKIP_DIR_NAMES for part in rel.parts):
        return True
    if rel.name == "__init__.py":
        return True
    name = rel.name.lower()
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return False


def collect_sources(stage: Path) -> list[Path]:
    return sorted(
        path
        for path in stage.rglob("*.py")
        if not _skip(path, stage)
    )


def module_name(path: Path, stage: Path) -> str:
    rel = path.relative_to(stage).with_suffix("")
    return ".".join(rel.parts)


def strip_compiled_py(stage: Path) -> int:
    removed = 0
    for path in collect_sources(stage):
        if any(path.parent.glob(f"{path.stem}.cpython-*.so")):
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", type=Path, help="Staged source tree to compile")
    parser.add_argument(
        "--strip-py",
        action="store_true",
        help="Remove .py after a matching .so is built",
    )
    args = parser.parse_args(argv)

    stage = args.stage.resolve()
    if not stage.is_dir():
        print(f"error: stage directory not found: {stage}", file=sys.stderr)
        return 1

    sources = collect_sources(stage)
    if not sources:
        print("error: no Python sources found to compile", file=sys.stderr)
        return 1

    from Cython.Build import cythonize

    os.chdir(stage)
    rel_sources = [str(path.relative_to(stage)) for path in sources]
    extensions = [
        Extension(module_name(path, stage), [str(path.relative_to(stage))])
        for path in sources
    ]

    print(f"Cython: compiling {len(sources)} module(s) in {stage}")
    setup(
        ext_modules=cythonize(
            extensions,
            compiler_directives={"language_level": "3"},
            nthreads=0,
        ),
        script_args=["build_ext", "--inplace"],
    )

    if args.strip_py:
        count = strip_compiled_py(Path("."))
        print(f"Cython: removed {count} compiled .py source(s)")

    for artifact in Path(".").rglob("*.c"):
        artifact.unlink(missing_ok=True)
    stage_build = Path("build")
    if stage_build.is_dir():
        shutil.rmtree(stage_build)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
