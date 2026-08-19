from __future__ import annotations

import logging
import os


def configure_app_logging() -> None:
    level = os.environ.get("ROUNDTABLE_AGENT_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )
