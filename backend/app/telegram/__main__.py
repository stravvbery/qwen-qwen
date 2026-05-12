"""Standalone entry point: python -m app.telegram"""

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from .bot import run_polling  # noqa: E402

asyncio.run(run_polling())
