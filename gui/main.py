"""wx GUI main entry point."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import wx

from wav2chat.gui.frame import Wav2ChatFrame
from wav2chat.gui.models import GuiSettings


def main(args: argparse.Namespace) -> int:
    try:
        app = wx.App(False)
    except Exception as exc:
        logging.error("Failed to start wx GUI: %s", exc)
        return 1

    settings = GuiSettings(
        backend=args.backend,
        lang=args.lang,
        ui_lang=args.ui_lang,
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
        roles=getattr(args, "_roles", {}),
        keep_temp=args.keep_temp,
        verbose=args.verbose,
        quiet=args.quiet,
        refresh_models=getattr(args, "refresh_models", False),
    )

    initial_paths: list[Path] = []
    if args.input is not None:
        initial_paths.append(args.input)

    frame = Wav2ChatFrame(settings, initial_paths=initial_paths or None)
    frame.Show()
    app.MainLoop()
    return 0
