"""PyInstaller entry point (run after `pip install -e .` in the build venv)."""

from wav2chat.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
