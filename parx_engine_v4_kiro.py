"""
Backward-compatibility shim for older imports.

New code should import HorseRacingEngine from horse_racing_engine.
"""

from horse_racing_engine import HorseRacingEngine, ParxRacingEngineV4  # noqa: F401
from horse_racing_horse import Horse  # noqa: F401
