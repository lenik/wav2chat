"""Desktop GUI entry point for wav2chat."""

from __future__ import annotations

import argparse
import logging
import sys

from wav2chat.i18n import set_locale

_IBUS_LOG_HANDLER_ID: int | None = None
_ibus_log_filter_cb = None


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


def _install_ibus_log_filter() -> None:
    """Suppress IBus 'no capability of surrounding-text' warnings via GLib."""
    global _IBUS_LOG_HANDLER_ID, _ibus_log_filter_cb

    if sys.platform != "linux" or _IBUS_LOG_HANDLER_ID is not None:
        return

    try:
        from gi.repository import GLib
    except ImportError:
        return

    def ibus_log_filter(log_domain, log_level, message, user_data):
        if message and "surrounding-text" in message:
            return
        GLib.log_default_handler(log_domain, log_level, message, user_data)

    _ibus_log_filter_cb = ibus_log_filter
    _IBUS_LOG_HANDLER_ID = GLib.log_set_handler(
        "IBUS",
        GLib.LogLevelFlags.LEVEL_WARNING,
        ibus_log_filter,
        None,
    )


def run_gui(args: argparse.Namespace) -> int:
    import os

    os.environ.setdefault("TQDM_DISABLE", "1")
    _install_ibus_log_filter()
    set_locale(args.ui_lang)

    try:
        from wav2chat.gui_wx import main as wx_main
    except ImportError as exc:
        if exc.name != "wx":
            raise
        logging.error("%s", _wx_import_error())
        return 1

    return wx_main(args)
