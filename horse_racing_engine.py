"""
Horse Racing Predictive Engine v4.0 (Kiro) — main orchestrator.

Composes ParserMixin, FeaturesMixin, and ReportingMixin into a single class.
Config files are resolved relative to this file so the engine can be launched
from any working directory.
"""

import os
import re
import json
import logging
from pathlib import Path

# Resolve config/ relative to this file, not the caller's cwd.
_CONFIG_DIR = Path(__file__).parent / "config"

# Import validation components
try:
    from validation_models import ValidationConfig
    from validator import Validator
    from custom_validators import CUSTOM_VALIDATORS
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False
    logging.warning("Validation modules not available - validation will be skipped")

# Import pattern configuration components
try:
    from pattern_models import PatternConfig, FieldPattern
    PATTERN_CONFIG_AVAILABLE = True
except ImportError:
    PATTERN_CONFIG_AVAILABLE = False
    logging.warning("Pattern configuration modules not available - using hardcoded patterns")

# Import normalizer component
try:
    from normalizer import Normalizer
    NORMALIZER_AVAILABLE = True
except ImportError:
    NORMALIZER_AVAILABLE = False
    logging.warning("Normalizer module not available - using inline normalization")

# Import diagnostic reporter
try:
    from diagnostic_reporter import DiagnosticReporter
    REPORTER_AVAILABLE = True
except ImportError:
    REPORTER_AVAILABLE = False
    logging.warning("DiagnosticReporter module not available")

from horse_racing_horse import Horse
from horse_racing_parser import ParserMixin
from horse_racing_features import FeaturesMixin
from horse_racing_reporting import ReportingMixin


class HorseRacingEngine(ParserMixin, FeaturesMixin, ReportingMixin):
    """
    Horse Racing Engine v4 (Kiro).
    Extracts comprehensive data and builds predictive models.

    Improvements over v3:
      - Odds-parsed flag prevents fabricated market signals from polluting analysis
      - O(n) PDF text extraction via list+join instead of string concatenation loop
      - pd.option_context replaces global pd.set_option to avoid display state leaks
      - Horse.avg_finish default aligned with compute_features fallback (5.0)
      - Horse.__repr__ for readable debugging output
    """

    def __init__(self):
        self.all_races = {}
        self.race_info = {}
        self.actual_results = {}
        self.track_name = "Racing"  # overwritten by extract_text_from_pdf

        # Validator
        self.validator = None
        if VALIDATION_AVAILABLE:
            try:
                config_path = _CONFIG_DIR / "validation.json"
                with open(config_path, 'r') as f:
                    config_json = f.read()
                config = ValidationConfig.from_json(config_json, CUSTOM_VALIDATORS)
                self.validator = Validator(config)
                print("[+] Validation framework initialized")
            except FileNotFoundError:
                print(f"[!] Warning: {config_path} not found - validation disabled")
            except Exception as e:
                print(f"[!] Warning: Failed to initialize validator: {e}")

        # Pattern config
        self.pattern_config = None
        self.compiled_patterns = {}
        if PATTERN_CONFIG_AVAILABLE:
            try:
                config_path = _CONFIG_DIR / "patterns.json"
                with open(config_path, 'r') as f:
                    config_json = f.read()
                self.pattern_config = PatternConfig.from_json(config_json)
                self.compiled_patterns = self.pattern_config.compile_all_patterns()
                print(f"[+] Pattern configuration loaded: {len(self.compiled_patterns)} field patterns compiled")
            except FileNotFoundError:
                print(f"[!] Warning: {config_path} not found - using hardcoded patterns")
            except Exception as e:
                print(f"[!] Warning: Failed to load pattern configuration: {e}")

        # Normalizer
        self.normalizer = None
        if NORMALIZER_AVAILABLE:
            self.normalizer = Normalizer()
            print("[+] Normalizer initialized")

        # Diagnostic reporter
        self.reporter = None
        if REPORTER_AVAILABLE:
            self.reporter = DiagnosticReporter()
            print("[+] Diagnostic reporter initialized")

        # Meet stats (jockey/trainer win counts updated after results come in)
        self.meet_stats = self._load_meet_stats()

    # ── Meet stats ────────────────────────────────────────────────────────────

    def _load_meet_stats(self):
        stats_path = _CONFIG_DIR / "meet_stats.json"
        if not stats_path.exists():
            return None
        try:
            with open(stats_path, 'r') as f:
                data = json.load(f)
            meet = data.get('meet', 'Unknown meet')
            updated = data.get('last_updated', '?')
            races = data.get('races_counted', '?')
            print(f"[+] Meet stats loaded: {meet} — {races} races through {updated}")
            return data
        except Exception as e:
            print(f"[!] Warning: Could not load meet_stats.json: {e}")
            return None

    @staticmethod
    def _norm_person(name: str) -> str:
        """Lowercase + strip non-alpha + strip name suffixes for fuzzy matching."""
        base = re.sub(r'[^a-z]', '', name.lower())
        for sfx in ('iii', 'iv', 'jr', 'sr', 'ii'):
            if base.endswith(sfx):
                base = base[:-len(sfx)]
        return base

    def _apply_meet_stats(self):
        """
        Replace jockey/trainer win% on every parsed horse with current meet
        figures from meet_stats.json.  Falls back to the PDF-parsed value when
        the name is not found in the stats file.
        """
        if not self.meet_stats:
            return

        jockey_lookup = {
            self._norm_person(name): data
            for name, data in self.meet_stats.get('jockeys', {}).items()
        }
        trainer_lookup = {
            self._norm_person(name): data
            for name, data in self.meet_stats.get('trainers', {}).items()
        }

        updated_j = updated_t = 0
        for horses in self.all_races.values():
            for horse in horses:
                key = self._norm_person(horse.jockey_name)
                if key in jockey_lookup:
                    d = jockey_lookup[key]
                    if d['starts'] > 0:
                        horse.jockey_win_pct = d['wins'] / d['starts']
                        updated_j += 1

                key = self._norm_person(horse.trainer_name)
                if key in trainer_lookup:
                    d = trainer_lookup[key]
                    if d['starts'] > 0:
                        horse.trainer_win_pct = d['wins'] / d['starts']
                        updated_t += 1

        print(f"[+] Meet stats applied: {updated_j} jockey, {updated_t} trainer records updated")

    def parse_races(self, text):
        """Parse races then overlay current meet stats on jockey/trainer win %."""
        super().parse_races(text)
        self._apply_meet_stats()

    def add_results(self, race_num: str, finish_order: list):
        """
        Record the actual finish order for a race so the HTML report can
        show predicted vs actual side-by-side.

        Args:
            race_num:     Race number as a string, e.g. '1'
            finish_order: List of horse names in finishing order (1st to last).
                          Names are matched case-insensitively with spaces and
                          punctuation stripped.
        """
        self.actual_results[str(race_num)] = [h.strip() for h in finish_order]
        print(f"[+] Results recorded for Race {race_num}: "
              f"{', '.join(finish_order[:3])}{'...' if len(finish_order) > 3 else ''}")


# ── CLI entry point ───────────────────────────────────────────────────────────

ParxRacingEngineV4 = HorseRacingEngine

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--pdf', default='samples/prx0422y.pdf', help='PDF file path')
    parser.add_argument('--race', default='1', help='Race number to analyze')
    parser.add_argument('--plot', action='store_true', help='Show plot')
    parser.add_argument('--detailed', action='store_true', help='Show detailed model breakdown')
    parser.add_argument('--scorecard', action='store_true', help='Show full per-horse composite scorecard')
    parser.add_argument('--html', action='store_true', help='Export results to HTML and open in browser')
    parser.add_argument('--html-out', default=None, help='HTML output file path (default: <pdf_stem>_predictions.html)')
    parser.add_argument('--diagnose', action='store_true', help='Print feature parse quality diagnostic')
    args = parser.parse_args()

    engine = HorseRacingEngine()

    print("\n" + "="*50)
    print(" HORSE RACING PREDICTIVE ENGINE v4.0 (Kiro)")
    print("="*50)

    if os.path.exists(args.pdf):
        text = engine.extract_text_from_pdf(args.pdf)

        if text:
            engine.parse_races(text)

            print(f"\n[+] Found races: {list(engine.all_races.keys())}")

            for race_num in engine.all_races.keys():
                horses = engine.all_races[race_num]
                print(f"\n  Race {race_num}: {len(horses)} horses")
                for h in horses:
                    print(f"    - {h!r}")

            # Hardcoded actual results for the prx0422y.pdf sample only
            if Path(args.pdf).name == 'prx0422y.pdf':
                engine.add_results('1', [
                    'Downtown Chalybrown',   # PP7
                    'Yuletide Gallop',       # PP5
                    'Runandscore',           # PP3
                    'Borracho',              # PP2
                    'Cold Feet',             # PP4
                    'Three Captains',        # PP1
                    'Midlaner',              # PP6
                ])
                engine.add_results('2', [
                    'Transcendental',        # PP2
                    'Backside Buzz',         # PP3
                    'Ahsad',                 # PP4
                    'Fast Bob',              # PP5
                    'Romantic Gamble',       # PP1
                ])
                engine.add_results('3', [
                    'Luminous Secret',       # PP6
                    'Pittore d\'Oro',        # PP4
                    'Keystormrising',        # PP2
                    'Candothis',             # PP5
                    'Astrid',                # PP1
                    'Nezy\'s Girl',          # PP3
                ])
                engine.add_results('4', [
                    'Sugar Princess',        # PP2
                    'Tush Push',             # PP1
                    'Mariah\'s Big Girl',    # PP3
                    'Turn On Twiss',         # PP4
                ])
                engine.add_results('5', [
                    'Sunday Spirit',         # PP4
                    'Chachaching',           # PP6
                    'Epic Luck',             # PP3
                    'Elusive Target',        # PP5
                    'Missouri River',        # PP2
                    'Silent Mode',           # PP1
                ])
                engine.add_results('6', [
                    'Island Dream Girl',     # PP3
                    'Ambitiously Placed',    # PP1
                    'Moor Strength',         # PP2
                    'Popover Gal',           # PP5
                    'Society Ball',          # PP4
                    'Rolls Royce Joyce',     # PP7
                    'Shudabeenacowgirl',     # PP6
                ])
                engine.add_results('7', [
                    'Solemn Oath',           # PP3
                    'Fast Motion',           # PP6
                    'Dakota Springs',        # PP8
                    'Charm of the Song',     # PP5
                    'Sirani',                # PP1
                    'Sweet Mischief',        # PP4
                    'Queen Wiggy',           # PP7
                    'Five Star Fran',        # PP2
                ])
                engine.add_results('8', [
                    'Shane\'s Wonder',       # PP1
                    'Gold in My Hands',      # PP4
                    'Connor\'s Crew',        # PP2
                    'Presenceisapresent',    # PP3
                ])
                engine.add_results('9', [
                    'Carmelina',             # PP2
                    'Confirmed Star',        # PP5
                    'Carousel Queen',        # PP3
                    'Disco Ebo',             # PP1
                    'Pachelbel',             # PP6
                    'Bailout Billy',         # PP4
                ])
                engine.add_results('10', [
                    'Ninetyprcentmaddie',    # PP1
                    'Twisted Ride',          # PP2
                    'Insurmountable',        # PP3
                    'Crab Daddy',            # PP5
                    'Gordian Knot',          # PP6
                    'Big Boys Answer',       # PP4
                    "Kohler's",              # PP7
                ])

            if args.html:
                html_out = args.html_out or (Path(args.pdf).stem + "_predictions.html")
                engine.export_html(output_path=html_out)
            elif args.diagnose:
                engine.diagnose_parse_quality()
            else:
                if args.race in engine.all_races:
                    if args.scorecard or args.detailed:
                        engine.print_detailed_predictions(args.race)
                    else:
                        engine.print_predictions(args.race)
                    if args.plot:
                        engine.plot_race(args.race)
                else:
                    print(f"\nRace {args.race} not found")
    else:
        print(f"[!] PDF not found: {args.pdf}")
        print("Pass a valid path with --pdf path/to/file.pdf")
