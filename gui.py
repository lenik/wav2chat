"""Desktop GUI entry point for wav2chat."""

from __future__ import annotations

import argparse
import logging

from wav2chat.i18n import set_locale


def _wx_import_error() -> str:
    return (
        "GUI requires wxPython (the wx module).\n\n"
        "On Debian/Ubuntu:\n"
        "  sudo apt install python3-wxgtk4.0\n\n"
        "If you use a virtualenv, recreate it with system site packages:\n"
        "  python3 -m venv --system-site-packages .venv\n"
        "  source .venv/bin/activate\n"
        "  pip install -e .\n\n"
        "Then run: wav2chat -g"
    )


def run_gui(args: argparse.Namespace) -> int:
    import os

    os.environ.setdefault("TQDM_DISABLE", "1")
    set_locale(args.ui_lang)

    try:
        from wav2chat.gui_wx import main as wx_main
    except ImportError as exc:
        if exc.name != "wx":
            raise
        logging.error("%s", _wx_import_error())
        return 1

    return wx_main(args)
