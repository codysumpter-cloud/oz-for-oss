from __future__ import annotations

import signal
import sys
from types import FrameType


def install_signal_handlers() -> None:
    """Install handlers that convert termination signals into SystemExit.

    Only SIGTERM is handled because GitHub Actions sends SIGTERM on
    workflow cancellation.  SIGINT is left to Python's default handler.
    """

    def _handle_term(signum: int, frame: FrameType | None) -> None:
        del frame
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _handle_term)
