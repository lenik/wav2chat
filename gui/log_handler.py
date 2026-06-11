"""Logging handler that forwards records to the GUI queue."""

from __future__ import annotations

import logging


class GuiLogHandler(logging.Handler):
    def __init__(self, enqueue) -> None:
        super().__init__()
        self._enqueue = enqueue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._enqueue(record.levelno, self.format(record))
        except Exception:
            self.handleError(record)
