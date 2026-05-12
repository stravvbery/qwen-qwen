"""Gemini API proxy with automatic key rotation (standalone module).

This is a standalone version NOT integrated into the main app routing.
It coexists with the existing backend/app/gemini_proxy.py which is used
by the main application.

See README.md for usage instructions.
"""

from .provider import GeminiKeyRotationProxy, KeyState, KeyStatus

__all__ = ["GeminiKeyRotationProxy", "KeyState", "KeyStatus"]
