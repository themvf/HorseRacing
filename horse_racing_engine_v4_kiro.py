"""
Backward-compatibility shim — import from horse_racing_engine for new code.

This module re-exports HorseRacingEngine and Horse so existing imports
(run.py, tests, notebooks) continue to work without changes.
"""

from horse_racing_engine import HorseRacingEngine, ParxRacingEngineV4  # noqa: F401
from horse_racing_horse import Horse  # noqa: F401
