"""
Parx Racing Predictive Engine v4.0 (Kiro)
Enhanced engine to extract, model, and visualize horse racing probabilities.
Uses comprehensive past performance data for predictions.

Changes from v3:
  - Fix 4: Track odds_parsed flag on Horse; skip value analysis for horses with
            default fallback odds to avoid comparing model output against fabricated
            market signals.
  - Fix 5: Replace string concatenation loop in extract_text_from_pdf with list +
            join (O(n) instead of O(n²)). Replace global pd.set_option calls in
            print_detailed_predictions with pd.option_context to avoid leaking
            display state.
  - Fix 6: Align Horse.avg_finish default (0.0 -> 5.0) with compute_features
            fallback so pre-compute reads are consistent. Add Horse.__repr__ for
            readable debugging output.

Changes from v4 (model enhancement):
  - Prime Power removed from composite score; used as benchmark column only
  - Jockey Win % added (was parsed but never weighted)
  - Class Delta added: horse claim price vs race claim price (drop = advantage)
  - Distance Match added: best_speed_at_dist / best_speed ratio
  - Surface Match added: sire/dam mud SPI for off-track, surface affinity flag
  - HTML report shows PP Rank as independent benchmark vs model rank
"""

import re
import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pdfplumber
from datetime import datetime
import logging

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


class Horse:
    """Individual horse with comprehensive data."""

    def __init__(self, name):
        self.name = name
        self.odds = 0.0
        # Fix 4: track whether odds were actually parsed from the PDF.
        # When False, market-based value analysis is skipped to avoid
        # comparing model output against the 10.0 fallback.
        self.odds_parsed = False

        self.prime_power = 0.0
        self.pp_rank = 0
        self.style = "P"
        self.style_num = 0
        self.claim_price = 0
        self.color_sex = ""
        self.foal_year = 0
        self.sire = ""
        self.dam_sire = ""

        # Life stats
        self.starts = 0
        self.wins = 0
        self.places = 0
        self.shows = 0
        self.earnings = 0.0
        self.best_speed = 0
        self.best_speed_surface = ""

        # Current form
        self.class_rating = 0
        self.last_speed = 0
        self.best_speed_at_dist = 0

        # Trainer/Jockey
        self.trainer_name = ""
        self.trainer_stats = ""  # e.g., "156 43-23-31 28%"
        self.trainer_win_pct = 0.0
        self.jockey_name = ""
        self.jockey_stats = ""
        self.jockey_win_pct = 0.0

        # Sire stats
        self.sire_awd = 0.0
        self.sire_mud_sts = 0
        self.sire_mud_spi = 0.0
        self.dam_sire_awd = 0.0
        self.dam_sire_mud_sts = 0
        self.dam_sire_mud_spi = 0.0

        # Past performances (list of dicts)
        self.past_races = []

        # Workouts (list of times)
        self.workouts = []

        # Derived features
        self.recent_form = ""  # e.g., "312"
        # Fix 6: default matches the fallback value set in compute_features so
        # any code that reads avg_finish before compute_features is called sees
        # a neutral 5.0 rather than a misleading 0.0 (perfect finish).
        self.avg_finish = 5.0
        self.early_speed_pct = 0.0
        self.closer_speed_pct = 0.0
        self.train_wins = 0
        self.jky_wins = 0

    # Fix 6: human-readable repr for easier debugging and logging.
    def __repr__(self):
        return (
            f"Horse({self.name!r}, pp={self.prime_power:.1f}, "
            f"odds={self.odds}/1, parsed_odds={self.odds_parsed})"
        )
    
    # Validation results storage
    validation_results = []

    def compute_features(self):
        """Compute derived features from parsed data."""
        # avg_finish from Life stats: estimate average finish from win/place/show rates.
        # A horse that wins 30% of the time has a much better avg finish than one at 5%.
        # Formula: weight positions 1,2,3 by their frequency, assume rest finish ~midfield.
        if self.starts > 0:
            n = self.starts
            # Weighted average: wins finish 1st, places 2nd, shows 3rd, rest at midfield
            midfield = (n + 1) / 2  # average of remaining positions
            others   = n - self.wins - self.places - self.shows
            self.avg_finish = (
                self.wins   * 1 +
                self.places * 2 +
                self.shows  * 3 +
                max(others, 0) * midfield
            ) / n

        if not self.past_races:
            return

        # Best speed figure from past races (supplements header Fst() value)
        speeds = [r.get('speed', 0) for r in self.past_races if r.get('speed', 0) > 0]
        if speeds and self.best_speed == 0:
            self.best_speed = max(speeds)

        # Last race speed
        if self.past_races and self.last_speed == 0:
            self.last_speed = self.past_races[0].get('speed', 0)

        # Early vs Late speed averages from E1/E2 fractions
        early_spd = [r.get('e1', 0) for r in self.past_races if r.get('e1', 0) > 0]
        late_spd  = [r.get('e2', 0) for r in self.past_races if r.get('e2', 0) > 0]
        if early_spd:
            self.early_speed_pct = np.mean(early_spd)
        if late_spd:
            self.closer_speed_pct = np.mean(late_spd)

    def best_speed_at_distance(self, target_dist: float, tolerance: float = 0.5) -> int:
        """
        Return the best speed figure from past races run within `tolerance`
        furlongs of `target_dist`. Returns 0 if no matching races found.
        """
        speeds = [
            r['speed'] for r in self.past_races
            if r.get('speed', 0) > 0
            and abs(r.get('dist', -99) - target_dist) <= tolerance
        ]
        return max(speeds) if speeds else 0


class ParxRacingEngineV4:
    """
    Parx Racing Engine v4 (Kiro).
    Extracts comprehensive data and builds predictive models.

    Improvements over v3:
      - Odds-parsed flag prevents fabricated market signals from polluting analysis
      - O(n) PDF text extraction via list+join instead of string concatenation loop
      - pd.option_context replaces global pd.set_option to avoid display state leaks
      - Horse.avg_finish default aligned with compute_features fallback (5.0)
      - Horse.__repr__ for readable debugging output
    """

    # Model weights as a class-level constant.
    # Each key maps to a normalized feature column produced by _normalize_features.
    # Weights represent relative importance of each signal; they must sum to 1.0.
    #
    # Prime Power is intentionally excluded — it is a composite figure that already
    # incorporates speed, class, and form. Including it alongside those raw signals
    # would double-count them. Instead, PP Rank is shown as an independent benchmark
    # in the HTML report so you can compare our model's picks against it directly.
    MODEL_WEIGHTS = {
        'Market_Prob_Norm':   0.18,  # Implied probability from morning-line odds
        'Jockey_WPct_Norm':   0.15,  # Jockey win percentage at current meet
        'Speed_Norm':         0.15,  # Best speed figure (Beyer/Ragozin equivalent)
        'Form_Norm':          0.13,  # Recent finish positions (inverted)
        'Class_Delta_Norm':   0.12,  # Class drop/rise vs today's race level
        'Distance_Match_Norm':0.10,  # best_speed_at_dist / best_speed ratio
        'Surface_Match_Norm': 0.07,  # Surface/mud affinity from sire stats
        'Trainer_WPct_Norm':  0.06,  # Trainer win percentage
        'Style_Norm':         0.02,  # Running style number (pace pressure proxy)
        'WinPct_Norm':        0.02,  # Career win percentage (small signal)
        'EarlySpeed_Norm':    0.00,  # Early pace fraction (E1) average
        'CloserSpeed_Norm':   0.00,  # Late pace fraction (E2) — captured by Form
        'Earnings_Norm':      0.00,  # Earnings per start — captured by Class Delta
        'LastSpeed_Norm':     0.00,  # Last race speed — captured by Speed_Norm
    }

    assert abs(sum(MODEL_WEIGHTS.values()) - 1.0) < 1e-9, \
        f"MODEL_WEIGHTS must sum to 1.0, got {sum(MODEL_WEIGHTS.values())}"

    def __init__(self):
        self.all_races = {}   # Structure: { '1': [Horse, Horse, ...], '2': [...] }
        self.race_info = {}   # Race metadata
        self.actual_results = {}  # Structure: { '1': ['Horse A', 'Horse B', ...] } finish order
        
        # Initialize validator if validation modules are available
        self.validator = None
        if VALIDATION_AVAILABLE:
            try:
                with open('config/validation.json', 'r') as f:
                    config_json = f.read()
                config = ValidationConfig.from_json(config_json, CUSTOM_VALIDATORS)
                self.validator = Validator(config)
                print("[+] Validation framework initialized")
            except FileNotFoundError:
                print("[!] Warning: config/validation.json not found - validation disabled")
            except Exception as e:
                print(f"[!] Warning: Failed to initialize validator: {e}")
        
        # Initialize pattern configuration and compile patterns
        self.pattern_config = None
        self.compiled_patterns = {}
        if PATTERN_CONFIG_AVAILABLE:
            try:
                with open('config/patterns.json', 'r') as f:
                    config_json = f.read()
                self.pattern_config = PatternConfig.from_json(config_json)
                # Compile all regex patterns once at initialization for performance
                self.compiled_patterns = self.pattern_config.compile_all_patterns()
                print(f"[+] Pattern configuration loaded: {len(self.compiled_patterns)} field patterns compiled")
            except FileNotFoundError:
                print("[!] Warning: config/patterns.json not found - using hardcoded patterns")
            except Exception as e:
                print(f"[!] Warning: Failed to load pattern configuration: {e}")

        # Initialize normalizer for distance and name normalization
        self.normalizer = None
        if NORMALIZER_AVAILABLE:
            self.normalizer = Normalizer()
            print("[+] Normalizer initialized")

        # Initialize diagnostic reporter
        self.reporter = None
        if REPORTER_AVAILABLE:
            self.reporter = DiagnosticReporter()
            print("[+] Diagnostic reporter initialized")


    def add_results(self, race_num: str, finish_order: list):
        """
        Record the actual finish order for a race so the HTML report can
        show predicted vs actual side-by-side.

        Args:
            race_num:     Race number as a string, e.g. '1'
            finish_order: List of horse names in finishing order (1st to last).
                          Names are matched case-insensitively with spaces and
                          punctuation stripped, so 'Downtown Chalybrown' will
                          match the PDF's 'Downtownchalybrown'.
        """
        self.actual_results[str(race_num)] = [h.strip() for h in finish_order]
        print(f"[+] Results recorded for Race {race_num}: "
              f"{', '.join(finish_order[:3])}{'...' if len(finish_order) > 3 else ''}")

    def _extract_field_with_patterns(self, field_name: str, text: str, context: str = "") -> tuple:
        """
        Extract a field value using pattern priority logic from configuration.
        
        Args:
            field_name: Name of the field to extract (must exist in pattern_config)
            text: Text to search in (can be full block or line-by-line)
            context: Optional context string for logging (e.g., horse name)
        
        Returns:
            Tuple of (extracted_value, pattern_index) where pattern_index is the
            0-based index of the pattern that matched, or (default_value, -1) if no match.
        """
        if not self.pattern_config or field_name not in self.compiled_patterns:
            # Fallback: no pattern config available
            return (None, -1)
        
        field_pattern = self.pattern_config.get_field(field_name)
        compiled_patterns = self.compiled_patterns[field_name]
        
        # Apply pre-filter optimization if specified
        if field_pattern.pre_filter and field_pattern.pre_filter not in text:
            return (field_pattern.default_value, -1)
        
        # Try each pattern in priority order
        for pattern_idx, compiled_pattern in enumerate(compiled_patterns):
            # For line-by-line matching with exclude_keywords
            if field_pattern.exclude_keywords:
                for line in text.split('\n'):
                    line_stripped = line.strip()
                    # Skip lines containing exclude keywords
                    if any(kw in line_stripped for kw in field_pattern.exclude_keywords):
                        continue
                    match = compiled_pattern.search(line_stripped)
                    if match:
                        logging.info(f"[Pattern Match] {field_name} (pattern #{pattern_idx+1}){' for ' + context if context else ''}")
                        return (match, pattern_idx)
            else:
                # Direct pattern matching on full text
                match = compiled_pattern.search(text)
                if match:
                    logging.info(f"[Pattern Match] {field_name} (pattern #{pattern_idx+1}){' for ' + context if context else ''}")
                    return (match, pattern_idx)
        
        # No pattern matched - return default value
        return (field_pattern.default_value, -1)

    @staticmethod
    def _normalize_name(name: str) -> str:
        """
        Normalize a horse name for fuzzy matching.
        Lowercases and removes spaces and common punctuation so that
        'Downtown Chalybrown' == 'Downtownchalybrown',
        "Nezy's Girl" == "NezysGirl", etc.
        """
        return re.sub(r"[\s\'\-\.\,]", "", name).lower()

    @staticmethod
    def _minmax_scale(series: pd.Series) -> pd.Series:
        """
        Min-max scale a Series to [0, 1].
        Returns 0.5 for every row when all values are identical (zero variance)
        so the feature contributes nothing to differentiation.
        """
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series(0.5, index=series.index)
        return (series - mn) / (mx - mn)

    def extract_text_from_pdf(self, pdf_path):
        """Extract raw text from PDF."""
        print(f"[*] Reading PDF: {pdf_path}...")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                print(f"[*] Total pages: {total_pages}")

                # Fix 5: collect into a list and join once — O(n) instead of the
                # O(n²) string concatenation that += produces in a loop.
                pages = []
                for i, page in enumerate(pdf.pages):
                    print(f"[*] Reading page {i+1}/{total_pages}...", end='\r')
                    text = page.extract_text()
                    if text:
                        pages.append(f"\n--- PAGE {i+1} ---\n{text}\n")

                full_text = "".join(pages)
                print(f"\n[*] Extracted {len(full_text)} characters")
            return full_text if full_text.strip() else None
        except Exception as e:
            print(f"[!] Critical error reading PDF: {e}")
            return None

    def parse_races(self, text):
        """Parse races from extracted text."""
        race_markers = list(re.finditer(r'Race\s+(\d+)\s*\n#\s+Speed', text))

        for idx, match in enumerate(race_markers):
            race_num = match.group(1)
            start_pos = match.start()
            end_pos = race_markers[idx + 1].start() if idx + 1 < len(race_markers) else len(text)
            race_content = text[start_pos:end_pos]

            print(f"[*] Processing Race {race_num} ({len(race_content)} chars)")

            self._parse_race_info(race_num, race_content)

            horses = self._parse_horses(race_content)
            if horses:
                self.all_races[race_num] = horses
                print(f"[+] Race {race_num}: {len(horses)} horses parsed")
            else:
                print(f"[!] No horses found in Race {race_num}")

        # Generate diagnostic report after all races parsed (if reporter available)
        # Note: diagnose_parse_quality() still works for detailed output;
        # reporter provides the structured version for programmatic use.
        if self.reporter and self.all_races:
            flagged = self.reporter.flag_low_quality_races(self.all_races)
            if flagged:
                print(f"[!] Low parse quality in races: {', '.join(flagged)} — run --diagnose for details")

    def _parse_race_info(self, race_num, text):
        """Parse race metadata (distance, purse, conditions)."""
        info = {'race_num': race_num}

        # Distance — use Normalizer if available for full format support
        # (handles Unicode fractions like ½, mojibake, miles+yards, etc.)
        dist_f = 0.0
        dist_str = ''
        for line in text.split('\n'):
            s = line.strip()
            if 'Purse' not in s and 'Furlongs' not in s and 'yds' not in s:
                continue
            # Extract the raw distance token from the line
            # Try miles+yards first (most specific)
            m = re.search(r'(\d+m\d+yds?)', s, re.IGNORECASE)
            if m:
                dist_str = m.group(1)
                if self.normalizer:
                    dist_f = self.normalizer.normalize_distance(dist_str)
                else:
                    mm = re.search(r'(\d+)m(\d+)yds?', dist_str, re.IGNORECASE)
                    dist_f = int(mm.group(1)) * 8 + int(mm.group(2)) / 220 if mm else 0.0
                if dist_f > 0:
                    break
            # Furlongs token — grab everything up to and including "Furlongs"
            m = re.search(r'(\S{0,6}Furlongs?)', s, re.IGNORECASE)
            if m:
                # Include leading digit(s) before the match
                start = max(0, m.start() - 4)
                raw_token = s[start:m.end()].strip()
                dist_str = raw_token
                if self.normalizer:
                    dist_f = self.normalizer.normalize_distance(raw_token)
                else:
                    mm = re.search(r'(\d+(?:\.\d+)?)\S{0,6}Furlongs?', raw_token, re.IGNORECASE)
                    dist_f = float(mm.group(1)) if mm else 0.0
                if dist_f > 0:
                    break

        if dist_f > 0:
            info['distance']   = dist_str
            info['distance_f'] = round(dist_f, 2)

        clm_match = re.search(r'Clm\s*(\d+)', text, re.IGNORECASE)
        if clm_match:
            info['claim_price'] = int(clm_match.group(1))

        purse_match = re.search(r'Purse\s*\$?([\d,]+)', text, re.IGNORECASE)
        if purse_match:
            info['purse'] = int(purse_match.group(1).replace(',', ''))

        self.race_info[race_num] = info

    def _parse_horses(self, text):
        """Parse all horses in a race."""
        horses = []
        horse_pattern = r'(\d+)\s+([A-Z][a-zA-Z\s\'\-\.]+?)\s*\(([A-Z/]+)\s*(\d+)\)'
        matches = list(re.finditer(horse_pattern, text))

        for idx, match in enumerate(matches):
            horse_name = match.group(2).strip()
            style_str = match.group(3)
            style_num = match.group(4)

            start_pos = match.start()
            end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            block = text[start_pos:end_pos]

            horse = self._parse_horse_block(block, horse_name, style_str, style_num)
            if horse and horse.name:
                horses.append(horse)

        return horses

    def _parse_horse_block(self, block, name, style_str, style_num):
        """Parse a single horse's data block."""
        horse = Horse(name)

        # Running style
        horse.style = style_str.split()[0] if style_str else "P"

        try:
            horse.style_num = int(style_num) if style_num else 0
        except ValueError as e:
            print(f"[!] Warning: could not parse style_num '{style_num}' for {name}: {e}")
            horse.style_num = 0

        # ML Odds
        # Fix 4: set odds_parsed=True only on a successful parse so downstream
        # analysis can distinguish real market data from the 10.0 fallback.
        if self.pattern_config:
            odds_match, pattern_idx = self._extract_field_with_patterns('odds', block, name)
            if odds_match and pattern_idx >= 0:
                try:
                    num, den = map(int, odds_match.group(1).split('/'))
                    horse.odds = num / den
                    horse.odds_parsed = True
                except (ValueError, ZeroDivisionError) as e:
                    print(f"[!] Warning: could not parse odds '{odds_match.group(1)}' for {name}: {e}")
                    horse.odds = 10.0
                    horse.odds_parsed = False
            else:
                horse.odds = 10.0
                horse.odds_parsed = False
        else:
            # Fallback to hardcoded pattern
            odds_match = re.search(r'(\d+/\d+)\s+[O]', block)
            if odds_match:
                try:
                    num, den = map(int, odds_match.group(1).split('/'))
                    horse.odds = num / den
                    horse.odds_parsed = True
                except (ValueError, ZeroDivisionError) as e:
                    print(f"[!] Warning: could not parse odds '{odds_match.group(1)}' for {name}: {e}")
                    horse.odds = 10.0
                    horse.odds_parsed = False
            else:
                horse.odds = 10.0
                horse.odds_parsed = False

        # Claim price — format: $16,000 or $7500
        if self.pattern_config:
            clm_match, pattern_idx = self._extract_field_with_patterns('claim_price', block, name)
            if clm_match and pattern_idx >= 0:
                horse.claim_price = int(clm_match.group(1).replace(',', ''))
        else:
            # Fallback to hardcoded pattern
            clm_match = re.search(r'\$(\d{1,3}(?:,\d{3})+|\d{4,6})', block)
            if clm_match:
                horse.claim_price = int(clm_match.group(1).replace(',', ''))

        # Prime Power
        if self.pattern_config:
            pp_match, pattern_idx = self._extract_field_with_patterns('prime_power', block, name)
            if pp_match and pattern_idx >= 0:
                horse.prime_power = float(pp_match.group(1))
                horse.pp_rank = int(pp_match.group(2))
        else:
            # Fallback to hardcoded pattern
            pp_match = re.search(r'Prime Power:\s*([\d.]+)\s*\((\d+)(?:st|nd|rd|th)\)', block)
            if pp_match:
                horse.prime_power = float(pp_match.group(1))
                horse.pp_rank = int(pp_match.group(2))

        # Life stats
        if self.pattern_config:
            life_match, pattern_idx = self._extract_field_with_patterns('life_stats', block, name)
            if life_match and pattern_idx >= 0:
                horse.starts = int(life_match.group(1))
                horse.wins = int(life_match.group(2))
                horse.places = int(life_match.group(3))
                horse.shows = int(life_match.group(4))
                try:
                    horse.earnings = float(life_match.group(5).replace(',', ''))
                except ValueError as e:
                    print(f"[!] Warning: could not parse earnings '{life_match.group(5)}' for {name}: {e}")
                    horse.earnings = 0.0
        else:
            # Fallback to hardcoded pattern
            life_match = re.search(r'Life:\s*(\d+)\s+(\d+)\s*-?\s*(\d+)\s*-?\s*(\d+)\s*\$?([\d,]+)', block)
            if life_match:
                horse.starts = int(life_match.group(1))
                horse.wins = int(life_match.group(2))
                horse.places = int(life_match.group(3))
                horse.shows = int(life_match.group(4))
                try:
                    horse.earnings = float(life_match.group(5).replace(',', ''))
                except ValueError as e:
                    print(f"[!] Warning: could not parse earnings '{life_match.group(5)}' for {name}: {e}")
                    horse.earnings = 0.0

        # Best speed (Fst)
        if self.pattern_config:
            speed_match, pattern_idx = self._extract_field_with_patterns('best_speed', block, name)
            if speed_match and pattern_idx >= 0:
                horse.best_speed = int(speed_match.group(1))
        else:
            # Fallback to hardcoded pattern
            speed_match = re.search(r'Fst\((\d+)\)', block)
            if speed_match:
                horse.best_speed = int(speed_match.group(1))

        # Class Rating
        if self.pattern_config:
            cr_match, pattern_idx = self._extract_field_with_patterns('class_rating', block, name)
            if cr_match and pattern_idx >= 0:
                horse.class_rating = int(cr_match.group(1))
        else:
            # Fallback to hardcoded pattern
            cr_match = re.search(r'(\d+)\s+Fst', block)
            if cr_match:
                horse.class_rating = int(cr_match.group(1))

        # Last race speed
        last_spd_match = re.search(r'(\d+)\s+\d+/\s*\d+\s+\d+\s+-\s*\d+', block)
        if last_spd_match:
            horse.last_speed = int(last_spd_match.group(1))

        # Trainer — handles names like "Pattershall Mary A", "Reid, Jr. Robert E"
        if self.pattern_config:
            trnr_match, pattern_idx = self._extract_field_with_patterns('trainer_name', block, name)
            if trnr_match and pattern_idx >= 0:
                horse.trainer_name = trnr_match.group(1).strip()
                try:
                    horse.trainer_win_pct = float(trnr_match.group(6)) / 100
                except (ValueError, IndexError) as e:
                    print(f"[!] Warning: could not parse trainer win pct for {name}: {e}")
                    horse.trainer_win_pct = 0.0
        else:
            # Fallback to hardcoded pattern matching
            trnr_match = re.search(
                r'Trnr:\s+([A-Za-z\s\-\'\.]+?)\s+\(([\d]+)\s+([\d]+)-([\d]+)-([\d]+)\s+(\d+)%\)', block
            )
            if not trnr_match:
                # Fallback: allow comma in name (e.g. "Reid, Jr. Robert E")
                trnr_match = re.search(
                    r'Trnr:\s+([A-Za-z\s\-\'\.,]+?)\s+\(([\d]+)\s+([\d]+)-([\d]+)-([\d]+)\s+(\d+)%\)', block
                )
            if trnr_match:
                horse.trainer_name = trnr_match.group(1).strip()
                try:
                    horse.trainer_win_pct = float(trnr_match.group(6)) / 100
                except ValueError as e:
                    print(f"[!] Warning: could not parse trainer win pct for {name}: {e}")
                    horse.trainer_win_pct = 0.0

        # Jockey — PDF format: "LASTNAME FIRSTNAME (starts wins-places-shows win%)"
        # Variants seen:
        #   HAZLEWOOD YEDSIT (178 44-35-23 25%)
        #   SANCHEZ MYCHEL J (203 59-27-30 29%)
        #   VARGAS, JR. JORGE A (63 12-12-6 19%)
        #   BEATO INOEL (4 0-1-1 0%)
        #   CORA DAVID (2 0-0-0 0%)
        # Strategy: line-by-line match to avoid catastrophic backtracking.
        # Accept uppercase words, commas, dots, and spaces before the stats paren.
        
        # Try pattern-based extraction first if available
        if self.pattern_config:
            jky_match, pattern_idx = self._extract_field_with_patterns('jockey_name', block, name)
            if jky_match and pattern_idx >= 0:
                # Raw name e.g. "VARGAS, JR. JORGE A" or "SANCHEZ MYCHEL J"
                raw = jky_match.group(1).strip()
                # Remove punctuation artifacts, split into words
                words = [w.strip(',.') for w in raw.split() if w.strip(',.')]
                # Filter out suffixes like JR, SR, II, III
                suffixes = {'JR', 'SR', 'II', 'III', 'IV', 'JR.', 'SR.'}
                name_words = [w for w in words if w.upper() not in suffixes]
                if len(name_words) >= 2:
                    # Convention: last word in all-caps block = last name, rest = first name
                    last  = name_words[0].capitalize()
                    first = ' '.join(w.capitalize() for w in name_words[1:])
                    horse.jockey_name = f"{first} {last}"
                else:
                    horse.jockey_name = raw.title()
                try:
                    horse.jockey_win_pct = float(jky_match.group(3)) / 100
                except (ValueError, IndexError) as e:
                    print(f"[!] Warning: could not parse jockey win pct for {name}: {e}")
                    horse.jockey_win_pct = 0.0
        else:
            # Fallback to hardcoded pattern matching
            jky_match = None
            for _line in block.split('\n'):
                _s = _line.strip()
                # Quick pre-filter: must start with 2+ uppercase letters and contain ( and %
                if len(_s) < 8 or not _s[0].isupper() or '(' not in _s or '%' not in _s:
                    continue
                # First word must be all-uppercase (jockey last name)
                _first_word = _s.split()[0].rstrip(',.')
                if not _first_word.isupper() or len(_first_word) < 2:
                    continue
                # Skip non-jockey lines
                if any(kw in _s for kw in ('Trnr:', 'Life:', 'Sire', 'Dam', 'JKYw', 'PRX', 'Trf')):
                    continue
                _m = re.match(
                    r'([A-Z][A-Z,\.\s]+?)\s+\((\d+)\s+\d+-\d+-\d+\s+(\d+)%\)',
                    _s
                )
                if _m:
                    jky_match = _m
                    break
            if jky_match:
                # Raw name e.g. "VARGAS, JR. JORGE A" or "SANCHEZ MYCHEL J"
                raw = jky_match.group(1).strip()
                # Remove punctuation artifacts, split into words
                words = [w.strip(',.') for w in raw.split() if w.strip(',.')]
                # Filter out suffixes like JR, SR, II, III
                suffixes = {'JR', 'SR', 'II', 'III', 'IV', 'JR.', 'SR.'}
                name_words = [w for w in words if w.upper() not in suffixes]
                if len(name_words) >= 2:
                    # Convention: last word in all-caps block = last name, rest = first name
                    last  = name_words[0].capitalize()
                    first = ' '.join(w.capitalize() for w in name_words[1:])
                    horse.jockey_name = f"{first} {last}"
                else:
                    horse.jockey_name = raw.title()
                try:
                    horse.jockey_win_pct = float(jky_match.group(3)) / 100
                except ValueError as e:
                    print(f"[!] Warning: could not parse jockey win pct for {name}: {e}")
                    horse.jockey_win_pct = 0.0

        # Past performance lines — extract E1, E2, speed figure, and distance.
        # Key format issues found in PDF:
        #   1. Distance: "6┬╜ft" (mojibake for 6½) — grab leading digit(s) before 'f'
        #   2. E1/E2: sometimes "95104/" (CR jammed onto E1, no space) vs "82 78/"
        #   3. Mile races: "1m" or "├á1╦åfm" — extract leading digit only
        pp_date_re  = re.compile(r'^\d{2}[A-Za-z]{3}\d{2}')
        # E1/E2: two separate patterns to avoid the \s* ambiguity that caused 95104 -> 951+4.
        # Pattern A (spaced):  "82 78/ 80 +1 +5 90"  -> E1=82, E2=78, SPD=90
        # Pattern B (jammed):  "95104/ 80 +1 +5 90"  -> CR=95 (2 digits), E1=104, SPD=90
        # For jammed: CR is always 2 digits, E1 is 2-3 digits immediately after.
        pp_speed_spaced = re.compile(r'(\d{2,3})\s+(\d{2,3})/\s*\d{2,3}\s+[+-]?\d+\s+[+-]?\d+\s+(\d{2,3})')
        pp_speed_jammed = re.compile(r'\d{2}(\d{2,3})/\s*\d{2,3}\s+[+-]?\d+\s+[+-]?\d+\s+(\d{2,3})')

        for line in block.split('\n'):
            line = line.strip()
            if not pp_date_re.match(line):
                continue
            # Try spaced pattern first (more common), fall back to jammed
            sm = pp_speed_spaced.search(line)
            if sm:
                e1, e2, spd = int(sm.group(1)), int(sm.group(2)), int(sm.group(3))
            else:
                sm = pp_speed_jammed.search(line)
                if not sm:
                    continue
                # Jammed: CR+E1 merged, E2 not separately captured — use E1 for both
                e1 = int(sm.group(1))
                e2 = e1   # best approximation when E2 can't be separated
                spd = int(sm.group(2))
            try:
                # Distance: scan tokens 1-4 (skip date) for one starting with digit + f/m
                tokens = line.split()
                dist_f = 0.0
                for tok in tokens[1:5]:
                    dm = re.match(r'^(\d+(?:\.\d+)?)', tok)
                    if dm and ('f' in tok.lower() or tok.lower().endswith('m')):
                        raw_dist = float(dm.group(1))
                        if tok.lower().endswith('m') and 'f' not in tok.lower():
                            raw_dist *= 8
                        dist_f = raw_dist
                        break

                if e1 > 0 and spd > 0:
                    horse.past_races.append({
                        'dist':   dist_f,
                        'e1':     e1,
                        'e2':     e2,
                        'speed':  spd,
                        'finish': 0,
                    })
            except (ValueError, IndexError):
                pass

        # Sire stats
        sire_match = re.search(
            r'Sire Stats:\s+AWD\s*([\d.]+)\s+(\d+)%\s+.*Mud\s*(\d+)MudSts\s*([\d.]+)spi', block
        )
        if sire_match:
            horse.sire_awd = float(sire_match.group(1))
            horse.sire_mud_sts = int(sire_match.group(3))
            horse.sire_mud_spi = float(sire_match.group(4))

        # Dam's Sire stats
        dam_match = re.search(
            r"Dam'sSire:\s+AWD\s*([\d.]+)\s+(\d+)%.*Mud\s*(\d+)MudSts\s*([\d.]+)spi", block
        )
        if dam_match:
            horse.dam_sire_awd = float(dam_match.group(1))
            horse.dam_sire_mud_sts = int(dam_match.group(3))
            horse.dam_sire_mud_spi = float(dam_match.group(4))

        horse.compute_features()

        # Apply normalizer to names if available
        if self.normalizer:
            self.normalizer.normalize_horse_record(horse)

        # Validate horse record if validator is available
        if self.validator:
            validation_results = self.validator.validate_horse_record(horse)
            horse.validation_results = validation_results
            
            # Log validation failures
            failures = [r for r in validation_results if not r.is_valid]
            if failures:
                for result in failures:
                    print(f"[!] Validation {result.rule.severity}: {horse.name} - {result.message}")
        
        return horse

    def predict_race(self, race_num, model_type="enhanced"):
        """
        Predict race outcomes using multiple features.

        model_type: "simple" (Prime Power rank only), "enhanced" (all MODEL_WEIGHTS features)
        """
        if race_num not in self.all_races:
            return None

        horses = self.all_races[race_num]
        if not horses:
            return None

        race_info   = self.race_info.get(race_num, {})
        race_clm    = race_info.get('claim_price', 0)
        race_dist_f = race_info.get('distance_f', 0.0)  # already parsed to furlongs float

        features = []
        for horse in horses:
            # ── Class Delta ───────────────────────────────────────────
            # Positive = dropping in class (advantage), negative = rising (disadvantage).
            # Normalised later so direction is preserved via min-max.
            if race_clm > 0 and horse.claim_price > 0:
                class_delta = (horse.claim_price - race_clm) / race_clm
            else:
                class_delta = 0.0   # non-claiming or unknown — neutral

            # ── Distance Match ────────────────────────────────────────
            # Ratio of best speed at today's distance to overall best speed.
            # 1.0 = horse runs its best at this distance; 0.0 = no data.
            best_at_dist = horse.best_speed_at_distance(race_dist_f) if race_dist_f > 0 else 0
            if horse.best_speed > 0 and best_at_dist > 0:
                dist_match = best_at_dist / horse.best_speed
            elif horse.best_speed > 0 and best_at_dist == 0:
                dist_match = 0.5    # no distance-specific data — neutral
            else:
                dist_match = 0.0

            # ── Surface / Mud Match ───────────────────────────────────
            # Use sire mud SPI as a proxy for off-track/turf affinity.
            # Average sire and dam's sire SPI; fall back to 0 if unparsed.
            mud_signals = [
                s for s in [horse.sire_mud_spi, horse.dam_sire_mud_spi] if s > 0
            ]
            surface_score = float(np.mean(mud_signals)) if mud_signals else 0.0

            # ── Earnings per start ────────────────────────────────────
            earnings_per_start = (
                horse.earnings / horse.starts if horse.starts > 0 else 0.0
            )

            f = {
                'Horse':          horse.name,
                'PrimePower':     horse.prime_power,
                'PP_Rank':        horse.pp_rank,
                'ML_Odds':        horse.odds,
                'Odds_Parsed':    horse.odds_parsed,
                'Market_Prob':    1 / (horse.odds + 1) if horse.odds > 0 else 0.1,
                'Starts':         horse.starts,
                'Wins':           horse.wins,
                'Win_Pct':        horse.wins / horse.starts if horse.starts > 0 else 0,
                'Earnings':       horse.earnings,
                'EarningsPerStart': earnings_per_start,
                'Best_Speed':     horse.best_speed,
                'Last_Speed':     horse.last_speed,
                'Class_Rating':   horse.class_rating,
                'Best_Speed_Dist': best_at_dist,
                'Trainer_Win_Pct':horse.trainer_win_pct,
                'Jockey_Win_Pct': horse.jockey_win_pct,
                'Style_Num':      horse.style_num,
                'Avg_Finish':     horse.avg_finish,
                'Early_Speed':    horse.early_speed_pct,
                'Closer_Speed':   horse.closer_speed_pct,
                # New contextual features
                'Class_Delta':    class_delta,
                'Distance_Match': dist_match,
                'Surface_Score':  surface_score,
            }
            features.append(f)

        df = pd.DataFrame(features)
        df = self._normalize_features(df)

        if model_type == "simple":
            # Benchmark mode: rank purely by Prime Power
            df['Composite_Score'] = df['PP_Score_Norm']
        else:
            df['Composite_Score'] = sum(
                df[col] * weight for col, weight in self.MODEL_WEIGHTS.items()
            )

        # Softmax transformation
        exp_scores = np.exp(df['Composite_Score'] - df['Composite_Score'].max())
        df['Win_Prob'] = exp_scores / exp_scores.sum()

        df['Analysis'] = df.apply(lambda row: self._generate_analysis(row, df), axis=1)

        return df.sort_values('Win_Prob', ascending=False)

    def _normalize_features(self, df):
        """Normalize features to [0, 1] using min-max scaling."""
        # Existing features
        df['PP_Score_Norm']      = self._minmax_scale(df['PrimePower'])
        df['Market_Prob_Norm']   = self._minmax_scale(df['Market_Prob'])
        df['Trainer_WPct_Norm']  = self._minmax_scale(df['Trainer_Win_Pct'])
        df['Jockey_WPct_Norm']   = self._minmax_scale(df['Jockey_Win_Pct'])
        df['Speed_Norm']         = self._minmax_scale(df['Best_Speed'])
        df['LastSpeed_Norm']     = self._minmax_scale(df['Last_Speed'])
        # Form: lower average finish is better, so invert after scaling
        df['Form_Norm']          = 1 - self._minmax_scale(df['Avg_Finish'])
        df['Style_Norm']         = self._minmax_scale(df['Style_Num'])
        df['WinPct_Norm']        = self._minmax_scale(df['Win_Pct'])
        df['Earnings_Norm']      = self._minmax_scale(df['EarningsPerStart'])
        df['EarlySpeed_Norm']    = self._minmax_scale(df['Early_Speed'])
        df['CloserSpeed_Norm']   = self._minmax_scale(df['Closer_Speed'])
        # New contextual features
        df['Class_Delta_Norm']    = self._minmax_scale(df['Class_Delta'])
        df['Distance_Match_Norm'] = self._minmax_scale(df['Distance_Match'])
        df['Surface_Match_Norm']  = self._minmax_scale(df['Surface_Score'])
        return df

    # ------------------------------------------------------------------
    # Scorecard display helpers
    # ------------------------------------------------------------------

    # Maps each MODEL_WEIGHTS key to:
    #   (display_label, raw_column, raw_format_fn)
    # raw_format_fn receives the row and returns a human-readable string
    # for the "raw value" column of the scorecard.
    _SCORECARD_META = {
        'Market_Prob_Norm': (
            'Market Odds',
            lambda row: (
                f"{row['ML_Odds']:.1f}/1 -> Market Prob: {row['Market_Prob']:.3f}"
                if row['Odds_Parsed']
                else "N/A (odds not parsed)"
            ),
        ),
        'Jockey_WPct_Norm': (
            'Jockey Win %',
            lambda row: (
                f"{row['Jockey_Win_Pct']:.1%}"
                if row['Jockey_Win_Pct'] > 0
                else "Not parsed"
            ),
        ),
        'Speed_Norm': (
            'Speed',
            lambda row: (
                f"Best speed figure: {int(row['Best_Speed'])}"
                if row['Best_Speed'] > 0
                else "Not parsed"
            ),
        ),
        'Form_Norm': (
            'Form',
            lambda row: f"Avg finish: {row['Avg_Finish']:.2f}",
        ),
        'Class_Delta_Norm': (
            'Class Delta',
            lambda row: (
                f"Horse clm ${int(row.get('Class_Delta', 0) * 100 + 100):.0f} "
                f"-> {'+' if row.get('Class_Delta', 0) >= 0 else ''}"
                f"{row.get('Class_Delta', 0):.1%} vs field"
                if row.get('Class_Delta', 0) != 0
                else "Non-claiming / no data"
            ),
        ),
        'Distance_Match_Norm': (
            'Distance Match',
            lambda row: (
                f"Speed at dist: {int(row['Best_Speed_Dist'])} / "
                f"Best: {int(row['Best_Speed'])} = "
                f"{row['Distance_Match']:.2f}"
                if row['Best_Speed'] > 0 and row['Best_Speed_Dist'] > 0
                else "No distance-specific data"
            ),
        ),
        'Surface_Match_Norm': (
            'Surface / Mud Affinity',
            lambda row: (
                f"Mud SPI: {row['Surface_Score']:.2f}"
                if row['Surface_Score'] > 0
                else "No sire mud data"
            ),
        ),
        'Trainer_WPct_Norm': (
            'Trainer Win %',
            lambda row: (
                f"{row['Trainer_Win_Pct']:.1%}"
                if row['Trainer_Win_Pct'] > 0
                else "Not parsed"
            ),
        ),
        'Style_Norm': (
            'Running Style',
            lambda row: f"Style number: {int(row['Style_Num'])}",
        ),
        'WinPct_Norm': (
            'Win Percentage',
            lambda row: (
                f"{row['Win_Pct']:.1%} ({int(row['Wins'])}/{int(row['Starts'])} starts)"
                if row['Starts'] > 0
                else "No starts"
            ),
        ),
        'EarlySpeed_Norm': (
            'Early Speed (E1)',
            lambda row: (
                f"Avg E1: {row['Early_Speed']:.1f}"
                if row['Early_Speed'] > 0
                else "No pace data"
            ),
        ),
        'CloserSpeed_Norm': (
            'Closer Speed (E2)',
            lambda row: (
                f"Avg E2: {row['Closer_Speed']:.1f}"
                if row['Closer_Speed'] > 0
                else "No pace data"
            ),
        ),
        'Earnings_Norm': (
            'Earnings / Start',
            lambda row: (
                f"${row['EarningsPerStart']:,.0f}"
                if row['EarningsPerStart'] > 0
                else "No earnings"
            ),
        ),
        'LastSpeed_Norm': (
            'Last Race Speed',
            lambda row: (
                f"{int(row['Last_Speed'])}"
                if row['Last_Speed'] > 0
                else "Not parsed"
            ),
        ),
    }

    def _print_horse_scorecard(self, row):
        """
        Print the full component-by-component scorecard for a single horse,
        matching the format:
          Prime Power: 123.4 (Rank #1) → Normalized: 1.000 → Contribution: 0.250 (25%)
          ...
          Total Composite Score: 0.858 → Win Probability: 15.7%
        """
        odds_label = f"{row['ML_Odds']:.1f}/1" if row['Odds_Parsed'] else "N/A"
        print(f"\n  {'─'*70}")
        print(f"  Key Components for {row['Horse']} ({odds_label})")
        print(f"  {'─'*70}")

        for norm_col, weight in self.MODEL_WEIGHTS.items():
            label, raw_fn = self._SCORECARD_META[norm_col]
            raw_str   = raw_fn(row)
            norm_val  = row[norm_col]
            contrib   = norm_val * weight
            print(
                f"  {label}: {raw_str}"
                f"\n    → Normalized: {norm_val:.3f}"
                f"  → Contribution: {contrib:.3f} ({contrib:.1%})"
            )

        print(f"\n  Total Composite Score: {row['Composite_Score']:.3f}"
              f"  → Win Probability: {row['Win_Prob']:.1%}"
              f" (after softmax transformation)")
        print(f"  Analysis: {row['Analysis']}")

    def _generate_analysis(self, horse_row, df):
        """Generate analysis text for a horse."""
        reasons = []

        # Prime Power — shown as benchmark info, not a scoring signal
        if horse_row['PP_Rank'] == 1:
            reasons.append("PP #1 (benchmark)")
        elif horse_row['PP_Rank'] <= 3:
            reasons.append(f"PP Rank #{int(horse_row['PP_Rank'])}")

        # Market value vs model
        if horse_row['Odds_Parsed']:
            market_prob = horse_row['Market_Prob']
            if horse_row['Win_Prob'] > market_prob * 1.4:
                reasons.append("HIGH VALUE")
            elif horse_row['Win_Prob'] < market_prob * 0.6:
                reasons.append("Overvalued")
        else:
            reasons.append("Odds unavailable")

        # Jockey
        if horse_row['Jockey_Win_Pct'] >= 0.25:
            reasons.append("Elite jockey")
        elif horse_row['Jockey_Win_Pct'] >= 0.15:
            reasons.append("Solid jockey")

        # Trainer
        if horse_row['Trainer_Win_Pct'] >= 0.25:
            reasons.append("Elite trainer")
        elif horse_row['Trainer_Win_Pct'] >= 0.15:
            reasons.append("Solid trainer")

        # Class
        if horse_row.get('Class_Delta', 0) > 0.15:
            reasons.append("Dropping in class")
        elif horse_row.get('Class_Delta', 0) < -0.15:
            reasons.append("Rising in class")

        # Distance
        if horse_row.get('Distance_Match', 0) >= 0.95:
            reasons.append("Proven at distance")
        elif horse_row.get('Distance_Match', 0) == 0.5:
            reasons.append("Unproven at distance")

        # Form
        if horse_row['Avg_Finish'] <= 3:
            reasons.append("Excellent recent form")
        elif horse_row['Avg_Finish'] >= 5:
            reasons.append("Needs improvement")

        return " | ".join(reasons) if reasons else "Mixed metrics"

    def plot_race(self, race_num):
        """Visualize race predictions."""
        df = self.predict_race(race_num)
        if df is None or df.empty:
            print("No data to plot")
            return

        fig = make_subplots(
            rows=1, cols=2,
            specs=[[{"type": "bar"}, {"type": "indicator"}]],
            subplot_titles=("Win Probability", "Top Contender")
        )

        df_sorted = df.sort_values('Win_Prob', ascending=True)

        colors = ['green' if x > 0.25 else 'blue' if x > 0.15 else 'gray'
                  for x in df_sorted['Win_Prob']]

        fig.add_trace(
            go.Bar(
                x=df_sorted['Win_Prob'],
                y=df_sorted['Horse'],
                orientation='h',
                marker_color=colors,
                text=df_sorted['Win_Prob'].apply(lambda x: f"{x:.1%}"),
                textposition='auto'
            ),
            row=1, col=1
        )

        top = df.iloc[0]
        fig.add_trace(
            go.Indicator(
                mode="gauge+number",
                value=top['Win_Prob'] * 100,
                title={'text': top['Horse']},
                gauge={'axis': {'range': [0, 100]}, 'bar': {'color': 'darkgreen'}},
                number={'suffix': "%"}
            ),
            row=1, col=2
        )

        fig.update_layout(
            title=f"Race {race_num} Prediction Model",
            template="plotly_dark",
            showlegend=False,
            height=500
        )
        fig.show()

    def diagnose_parse_quality(self):
        """
        Print a feature population report for every parsed horse across all races.

        For each feature used in MODEL_WEIGHTS, shows:
          - How many horses have a non-zero / non-default value (parsed successfully)
          - How many are defaulting to 0 (parse failed or field not in PDF)
          - The fill rate as a percentage

        This makes it immediately visible which signals are contributing real data
        vs. collapsing to 0.5 noise in _minmax_scale.
        """
        FEATURE_MAP = {
            'Market_Prob_Norm':    ('odds_parsed',        lambda h: h.odds_parsed),
            'Jockey_WPct_Norm':    ('jockey_win_pct',     lambda h: h.jockey_win_pct > 0),
            'Speed_Norm':          ('best_speed',         lambda h: h.best_speed > 0),
            'Form_Norm':           ('avg_finish',         lambda h: h.starts > 0),
            'Class_Delta_Norm':    ('claim_price',        lambda h: h.claim_price > 0),
            'Distance_Match_Norm': ('best_speed_at_dist', lambda h: len(h.past_races) > 0 and h.best_speed > 0),
            'Surface_Match_Norm':  ('sire_mud_spi',       lambda h: h.sire_mud_spi > 0 or h.dam_sire_mud_spi > 0),
            'Trainer_WPct_Norm':   ('trainer_win_pct',    lambda h: h.trainer_win_pct > 0),
            'Style_Norm':          ('style_num',          lambda h: h.style_num > 0),
            'WinPct_Norm':         ('starts/wins',        lambda h: h.starts > 0),
            'EarlySpeed_Norm':     ('early_speed_pct',    lambda h: h.early_speed_pct > 0),
            'CloserSpeed_Norm':    ('closer_speed_pct',   lambda h: h.closer_speed_pct > 0),
            'Earnings_Norm':       ('earnings',           lambda h: h.earnings > 0),
            'LastSpeed_Norm':      ('last_speed',         lambda h: h.last_speed > 0),
        }

        all_horses = []
        for rn in sorted(self.all_races.keys(), key=int):
            for h in self.all_races[rn]:
                all_horses.append((rn, h))

        total = len(all_horses)
        if total == 0:
            print("[!] No horses parsed yet. Run parse_races() first.")
            return

        print(f"\n{'='*70}")
        print(f"  PARSE QUALITY DIAGNOSTIC  —  {total} horses across {len(self.all_races)} races")
        print(f"{'='*70}")
        print(f"  {'Feature':<22} {'Field':<20} {'Parsed':>8} {'Missing':>8} {'Fill%':>7}  {'Weight':>7}")
        print(f"  {'-'*65}")

        issues = []
        for norm_col, (field_name, check_fn) in FEATURE_MAP.items():
            weight  = self.MODEL_WEIGHTS.get(norm_col, 0)
            parsed  = sum(1 for _, h in all_horses if check_fn(h))
            missing = total - parsed
            pct     = parsed / total * 100
            label   = self._SCORECARD_META.get(norm_col, (norm_col,))[0]
            flag    = "  <-- WARNING" if pct < 50 and weight > 0 else ""
            print(f"  {label:<22} {field_name:<20} {parsed:>8} {missing:>8} {pct:>6.0f}%  {weight:>6.0%}{flag}")
            if pct < 50 and weight > 0:
                issues.append((label, pct, weight))

        print(f"  {'-'*65}")

        if issues:
            print(f"\n  HIGH-IMPACT MISSING FIELDS  (>50% unparsed with weight > 0%)")
            for label, pct, weight in sorted(issues, key=lambda x: -x[2]):
                print(f"    {label}: {pct:.0f}% fill  x  {weight:.0%} weight"
                      f"  ->  contributing noise instead of signal")

        print(f"\n  PER-RACE JOCKEY PARSE RATE  (15% weight — highest unverified signal):")
        print(f"  {'Race':<8} {'Horses':>8} {'Jockey OK':>10} {'Fill%':>7}")
        print(f"  {'-'*36}")
        for rn in sorted(self.all_races.keys(), key=int):
            horses = self.all_races[rn]
            parsed = sum(1 for h in horses if h.jockey_win_pct > 0)
            pct    = parsed / len(horses) * 100 if horses else 0
            flag   = "  <-- WARNING" if pct < 50 else ""
            print(f"  {rn:<8} {len(horses):>8} {parsed:>10} {pct:>6.0f}%{flag}")

        print(f"\n  SAMPLE JOCKEY VALUES  (first 3 horses per race):")
        for rn in sorted(self.all_races.keys(), key=int):
            horses = self.all_races[rn][:3]
            samples = [(h.name, h.jockey_name or 'NOT PARSED', f"{h.jockey_win_pct:.1%}") for h in horses]
            print(f"  Race {rn}: " + "  |  ".join(
                f"{n} -> '{j}' {p}" for n, j, p in samples
            ))

        print(f"\n{'='*70}\n")

    def print_predictions(self, race_num):
        """Print predictions to console."""
        df = self.predict_race(race_num)
        if df is None or df.empty:
            print(f"No data for Race {race_num}")
            return

        print(f"\n{'='*60}")
        print(f"RACE {race_num} PREDICTIONS")
        print(f"{'='*60}")

        for _, row in df.iterrows():
            odds_label = f"{row['ML_Odds']}/1" if row['Odds_Parsed'] else "N/A"
            print(f"\n{row['Horse']} ({odds_label})")
            print(f"  Win Prob: {row['Win_Prob']:.1%}")
            print(f"  Prime Power: {row['PrimePower']:.1f} (Rank #{row['PP_Rank']})")
            print(f"  Analysis: {row['Analysis']}")

    def print_detailed_predictions(self, race_num):
        """
        Print full per-horse scorecards showing every model component:
          raw value → normalized → contribution (weight × normalized)
        followed by composite score and win probability for each horse.
        """
        df = self.predict_race(race_num)
        if df is None or df.empty:
            print(f"No data for Race {race_num}")
            return

        weight_summary = "  |  ".join(
            f"{self._SCORECARD_META[col][0]}={w:.0%}"
            for col, w in self.MODEL_WEIGHTS.items()
        )

        print(f"\n{'='*72}")
        print(f"  RACE {race_num} — FULL COMPOSITE SCORECARD")
        print(f"{'='*72}")
        print(f"  Model weights: {weight_summary}")

        # Summary table first — quick overview of all horses ranked by win prob
        print(f"\n  {'#':<3} {'Horse':<28} {'Odds':<8} {'Score':<8} {'Win Prob'}")
        print(f"  {'─'*60}")
        for rank, (_, row) in enumerate(df.iterrows(), 1):
            odds_label = f"{row['ML_Odds']:.1f}/1" if row['Odds_Parsed'] else "N/A"
            print(
                f"  {rank:<3} {row['Horse']:<28} {odds_label:<8} "
                f"{row['Composite_Score']:.3f}   {row['Win_Prob']:.1%}"
            )

        # Per-horse scorecards
        print(f"\n{'='*72}")
        print(f"  COMPONENT BREAKDOWN BY HORSE")
        print(f"{'='*72}")
        for _, row in df.iterrows():
            self._print_horse_scorecard(row)

        print(f"\n{'='*72}")

    # ------------------------------------------------------------------
    # HTML export
    # ------------------------------------------------------------------

    def export_html(self, output_path="parx_results.html", auto_open=True):
        """
        Build a self-contained HTML report with one tab per race.
        Each tab contains:
          - A ranked summary table (horse, odds, composite score, win prob, analysis)
          - A full component scorecard table (one row per component per horse)
        Opens the file in the default browser when auto_open=True.
        """
        import webbrowser, pathlib

        if not self.all_races:
            print("[!] No race data to export. Run parse_races() first.")
            return

        race_nums = sorted(self.all_races.keys(), key=lambda x: int(x))
        race_dfs  = {}
        for rn in race_nums:
            df = self.predict_race(rn)
            if df is not None and not df.empty:
                race_dfs[rn] = df

        if not race_dfs:
            print("[!] predict_race returned no data for any race.")
            return

        # ── helpers ───────────────────────────────────────────────────
        def _ordinal(n):
            return {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")

        def pct_bar(value, color):
            """Inline SVG progress bar for win probability."""
            w = max(0, min(100, value * 100))
            return (
                f'<div class="bar-wrap">'
                f'<div class="bar" style="width:{w:.1f}%;background:{color}"></div>'
                f'<span class="bar-label">{value:.1%}</span>'
                f'</div>'
            )

        def rank_color(rank):
            return {1: "#2ecc71", 2: "#3498db", 3: "#9b59b6"}.get(rank, "#95a5a6")

        def summary_rows(df, actual):
            """
            actual: list of horse names in finish order, or empty list if unknown.
            PP Rank shown as independent benchmark alongside model rank.
            """
            actual_pos = {self._normalize_name(name): i+1 for i, name in enumerate(actual)}
            rows = []
            for pred_rank, (_, r) in enumerate(df.iterrows(), 1):
                odds  = f"{r['ML_Odds']:.1f}/1" if r['Odds_Parsed'] else "N/A"
                color = rank_color(pred_rank)
                bar   = pct_bar(r['Win_Prob'], color)
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(pred_rank, f"#{pred_rank}")
                pp_rank_cell = f"<td class='muted'>#{int(r['PP_Rank'])}</td>"

                # Actual finish cell
                apos = actual_pos.get(self._normalize_name(r['Horse']))
                if not actual or apos is None:
                    actual_cell = ""
                else:
                    diff = pred_rank - apos
                    if apos == 1:
                        fin_badge = f"<span class='fin-badge fin-win'>1st ✓</span>"
                    elif apos <= 3:
                        fin_badge = f"<span class='fin-badge fin-place'>{apos}{_ordinal(apos)}</span>"
                    else:
                        fin_badge = f"<span class='fin-badge fin-other'>{apos}{_ordinal(apos)}</span>"

                    if diff == 0:
                        delta = "<span class='delta exact'>= exact</span>"
                    elif diff < 0:
                        delta = f"<span class='delta better'>▲ {abs(diff)} better</span>"
                    else:
                        delta = f"<span class='delta worse'>▼ {diff} worse</span>"
                    actual_cell = f"<td>{fin_badge}</td><td>{delta}</td>"

                rows.append(
                    f"<tr>"
                    f"<td><span class='medal'>{medal}</span></td>"
                    f"<td class='horse-name'>{r['Horse']}</td>"
                    f"<td>{odds}</td>"
                    f"{pp_rank_cell}"
                    f"<td>{r['Composite_Score']:.3f}</td>"
                    f"<td>{bar}</td>"
                    f"{actual_cell}"
                    f"<td class='analysis'>{r['Analysis']}</td>"
                    f"</tr>"
                )
            return "\n".join(rows)

        def scorecard_rows(df):
            """One accordion card per horse with component breakdown table."""
            cards = []
            for rank, (_, r) in enumerate(df.iterrows(), 1):
                odds  = f"{r['ML_Odds']:.1f}/1" if r['Odds_Parsed'] else "N/A"
                color = rank_color(rank)
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

                comp_rows = []
                for norm_col, weight in self.MODEL_WEIGHTS.items():
                    label, raw_fn = self._SCORECARD_META[norm_col]
                    raw_str  = raw_fn(r)
                    norm_val = r[norm_col]
                    contrib  = norm_val * weight
                    bar_html = (
                        f'<div class="mini-bar-wrap">'
                        f'<div class="mini-bar" style="width:{norm_val*100:.1f}%;'
                        f'background:{color}"></div>'
                        f'</div>'
                    )
                    comp_rows.append(
                        f"<tr>"
                        f"<td>{label}</td>"
                        f"<td class='raw-val'>{raw_str}</td>"
                        f"<td>{bar_html}{norm_val:.3f}</td>"
                        f"<td><strong>{contrib:.3f}</strong> ({contrib:.1%})</td>"
                        f"</tr>"
                    )

                comp_table = (
                    "<table class='comp-table'>"
                    "<thead><tr>"
                    "<th>Component</th><th>Raw Value</th>"
                    "<th>Normalized</th><th>Contribution</th>"
                    "</tr></thead>"
                    "<tbody>" + "\n".join(comp_rows) + "</tbody>"
                    "</table>"
                )

                cards.append(
                    f"<details class='horse-card'>"
                    f"<summary style='border-left:4px solid {color}'>"
                    f"  <span class='medal'>{medal}</span>"
                    f"  <span class='horse-name'>{r['Horse']}</span>"
                    f"  <span class='odds-badge'>{odds}</span>"
                    f"  <span class='score-badge'>Score: {r['Composite_Score']:.3f}</span>"
                    f"  <span class='prob-badge' style='background:{color}'>"
                    f"    {r['Win_Prob']:.1%}"
                    f"  </span>"
                    f"</summary>"
                    f"<div class='card-body'>{comp_table}"
                    f"<p class='analysis-line'>Analysis: {r['Analysis']}</p>"
                    f"</div>"
                    f"</details>"
                )
            return "\n".join(cards)

        def results_section(rn, df, actual):
            """
            Build the Predicted vs Actual comparison table + grouped bar chart.
            Shows model accuracy AND Prime Power benchmark accuracy side by side.
            """
            if not actual:
                return ""

            actual_pos  = {self._normalize_name(name): i+1 for i, name in enumerate(actual)}
            pred_order  = list(df['Horse'])
            pred_pos    = {self._normalize_name(name): i+1 for i, name in enumerate(pred_order)}

            # PP benchmark order (sorted by PP_Rank ascending)
            pp_df       = df.sort_values('PP_Rank')
            pp_order    = list(pp_df['Horse'])
            pp_pos      = {self._normalize_name(name): i+1 for i, name in enumerate(pp_order)}

            def _accuracy(order, actual_pos_map):
                """Return (winner_correct, top3_overlap, rho)."""
                wc = (self._normalize_name(order[0]) == self._normalize_name(actual[0])
                      if order and actual else False)
                t3a = {self._normalize_name(h) for h in actual[:3]}
                t3p = {self._normalize_name(h) for h in order[:3]}
                ov  = len(t3a & t3p)
                common = [h for h in actual
                          if self._normalize_name(h) in
                          {self._normalize_name(n) for n in order}]
                if len(common) >= 2:
                    apos_map = {self._normalize_name(h): i+1 for i, h in enumerate(actual)}
                    ppos_map = {self._normalize_name(h): i+1 for i, h in enumerate(order)}
                    d2  = sum((apos_map[self._normalize_name(h)] -
                               ppos_map[self._normalize_name(h)])**2
                              for h in common)
                    nc  = len(common)
                    rho = 1 - (6 * d2) / (nc * (nc**2 - 1))
                else:
                    rho = None
                return wc, ov, rho

            m_wc, m_ov, m_rho = _accuracy(pred_order, actual_pos)
            p_wc, p_ov, p_rho = _accuracy(pp_order,   actual_pos)

            def _badge(wc, ov, rho, label):
                wc_b = (f"<span class='stat-badge stat-good'>{label}: Winner ✓</span>"
                        if wc else
                        f"<span class='stat-badge stat-miss'>{label}: Winner ✗</span>")
                ov_b = (f"<span class='stat-badge "
                        f"{'stat-good' if ov >= 2 else 'stat-warn' if ov == 1 else 'stat-miss'}'>"
                        f"{label}: {ov}/3 top-3</span>")
                rho_b = (f"<span class='stat-badge stat-info'>{label} rank corr: {rho:.2f}</span>"
                         if rho is not None else "")
                return wc_b + " " + ov_b + " " + rho_b

            model_badges = _badge(m_wc, m_ov, m_rho, "Model")
            pp_badges    = _badge(p_wc, p_ov, p_rho, "Prime Power")

            # ── Chart data ────────────────────────────────────────────
            # Build per-horse arrays ordered by actual finish
            chart_labels  = []   # short horse names
            chart_actual  = []   # actual finish position
            chart_model   = []   # model predicted rank
            chart_pp      = []   # PP rank

            for horse_name in actual:
                short = horse_name.split()[0]  # first word fits in chart
                chart_labels.append(short)
                chart_actual.append(actual_pos.get(self._normalize_name(horse_name), 0))
                chart_model.append(pred_pos.get(self._normalize_name(horse_name), 0))
                chart_pp.append(pp_pos.get(self._normalize_name(horse_name), 0))

            # Serialize to JS arrays
            import json
            js_labels = json.dumps(chart_labels)
            js_actual = json.dumps(chart_actual)
            js_model  = json.dumps(chart_model)
            js_pp     = json.dumps(chart_pp)
            n_horses  = len(actual)
            chart_id  = f"chart_race{rn}"

            chart_html = f"""
<div class='chart-box'>
  <h3>Rank Comparison Chart — Race {rn}</h3>
  <p class='hint'>Lower bar = better rank. Bars grouped per horse: Actual (gold) · Our Model (blue) · Prime Power (purple).</p>
  <canvas id='{chart_id}' class='rank-chart'></canvas>
</div>
<script>
(function() {{
  var canvas = document.getElementById('{chart_id}');
  var labels  = {js_labels};
  var actual  = {js_actual};
  var model   = {js_model};
  var pp      = {js_pp};
  var n       = labels.length;
  var maxRank = Math.max(...actual, ...model, ...pp, 1);

  // Sizing
  var BAR_W   = 18, GAP = 6, GROUP_PAD = 20, PAD_L = 36, PAD_T = 16, PAD_B = 56, PAD_R = 16;
  var groupW  = 3 * BAR_W + 2 * GAP;
  var totalW  = PAD_L + n * (groupW + GROUP_PAD) - GROUP_PAD + PAD_R;
  var totalH  = 260;
  var chartH  = totalH - PAD_T - PAD_B;

  canvas.width  = totalW;
  canvas.height = totalH;
  var ctx = canvas.getContext('2d');

  // Background
  ctx.fillStyle = '#1a1d27';
  ctx.fillRect(0, 0, totalW, totalH);

  // Y-axis gridlines + labels
  ctx.strokeStyle = '#2e3250';
  ctx.fillStyle   = '#8892b0';
  ctx.font        = '11px Segoe UI, sans-serif';
  ctx.textAlign   = 'right';
  for (var rank = 1; rank <= maxRank; rank++) {{
    var y = PAD_T + chartH - ((rank / maxRank) * chartH);
    ctx.beginPath();
    ctx.moveTo(PAD_L - 4, y);
    ctx.lineTo(totalW - PAD_R, y);
    ctx.stroke();
    ctx.fillText(rank, PAD_L - 6, y + 4);
  }}

  // Bars
  var COLORS = {{ actual: '#f1c40f', model: '#3498db', pp: '#9b59b6' }};
  var datasets = [
    {{ data: actual, color: COLORS.actual,  label: 'Actual' }},
    {{ data: model,  color: COLORS.model,   label: 'Model'  }},
    {{ data: pp,     color: COLORS.pp,      label: 'PP'     }},
  ];

  for (var gi = 0; gi < n; gi++) {{
    var gx = PAD_L + gi * (groupW + GROUP_PAD);
    for (var di = 0; di < datasets.length; di++) {{
      var val  = datasets[di].data[gi];
      if (!val) continue;
      var barH = (val / maxRank) * chartH;
      var bx   = gx + di * (BAR_W + GAP);
      var by   = PAD_T + chartH - barH;

      // Bar fill
      ctx.fillStyle = datasets[di].color;
      ctx.fillRect(bx, by, BAR_W, barH);

      // Value label on top of bar
      ctx.fillStyle   = '#e8eaf6';
      ctx.font        = 'bold 10px Segoe UI, sans-serif';
      ctx.textAlign   = 'center';
      ctx.fillText('#' + val, bx + BAR_W / 2, by - 3);
    }}

    // Horse name label below group
    ctx.fillStyle = '#8892b0';
    ctx.font      = '10px Segoe UI, sans-serif';
    ctx.textAlign = 'center';
    var labelX = gx + groupW / 2;
    ctx.fillText(labels[gi], labelX, totalH - PAD_B + 14);
  }}

  // Legend
  var legendX = PAD_L;
  var legendY = totalH - 14;
  datasets.forEach(function(ds, i) {{
    ctx.fillStyle = ds.color;
    ctx.fillRect(legendX, legendY - 9, 12, 10);
    ctx.fillStyle   = '#8892b0';
    ctx.font        = '11px Segoe UI, sans-serif';
    ctx.textAlign   = 'left';
    ctx.fillText(ds.label, legendX + 15, legendY);
    legendX += 80;
  }});
}})();
</script>"""

            # Comparison rows — iterate actual finish order
            rows = []
            for fin_pos, horse_name in enumerate(actual, 1):
                m_ppos = pred_pos.get(self._normalize_name(horse_name))
                p_ppos = pp_pos.get(self._normalize_name(horse_name))

                def _delta_cell(ppos, fin_pos):
                    if ppos is None:
                        return "<span class='muted'>—</span>"
                    diff = ppos - fin_pos
                    if diff == 0:
                        return f"#{ppos} <span class='delta exact'>= exact</span>"
                    elif diff < 0:
                        return f"#{ppos} <span class='delta better'>▲ {abs(diff)}</span>"
                    else:
                        return f"#{ppos} <span class='delta worse'>▼ {diff}</span>"

                fin_label = {1: "🥇 1st", 2: "🥈 2nd", 3: "🥉 3rd"}.get(fin_pos, f"#{fin_pos}")
                row_class = "res-win" if fin_pos == 1 else "res-place" if fin_pos <= 3 else ""
                rows.append(
                    f"<tr class='{row_class}'>"
                    f"<td><strong>{fin_label}</strong></td>"
                    f"<td class='horse-name'>{horse_name}</td>"
                    f"<td>{_delta_cell(m_ppos, fin_pos)}</td>"
                    f"<td>{_delta_cell(p_ppos, fin_pos)}</td>"
                    f"</tr>"
                )

            return (
                f"<div class='results-box'>"
                f"<h3>Predicted vs Actual — Model vs Prime Power Benchmark</h3>"
                f"<div class='stat-badges'>{model_badges}</div>"
                f"<div class='stat-badges'>{pp_badges}</div>"
                f"{chart_html}"
                f"<table class='results-table'>"
                f"<thead><tr>"
                f"<th>Actual Finish</th><th>Horse</th>"
                f"<th>Our Model</th><th>Prime Power</th>"
                f"</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody>"
                f"</table>"
                f"</div>"
            )

        # ── tab buttons & panels ───────────────────────────────────────
        tab_buttons = []
        tab_panels  = []

        for rn, df in race_dfs.items():
            info      = self.race_info.get(rn, {})
            dist      = info.get('distance', '—')
            purse     = f"${info.get('purse', 0):,}" if 'purse' in info else '—'
            top_horse = df.iloc[0]['Horse']
            top_prob  = df.iloc[0]['Win_Prob']
            actual    = self.actual_results.get(rn, [])

            tab_buttons.append(
                f"<button class='tab-btn' onclick=\"showTab('race{rn}')\" "
                f"id='btn-race{rn}'>"
                f"Race {rn}"
                f"<span class='tab-sub'>{top_horse} {top_prob:.0%}</span>"
                f"</button>"
            )

            weight_pills = " ".join(
                f"<span class='pill'>{self._SCORECARD_META[col][0]}: "
                f"{w:.0%}</span>"
                for col, w in self.MODEL_WEIGHTS.items()
            )

            # Show actual finish columns only if results are available
            actual_headers = (
                "<th>Actual Finish</th><th>vs Predicted</th>"
                if actual else ""
            )

            tab_panels.append(
                f"<div class='tab-panel' id='race{rn}'>"
                f"<div class='race-header'>"
                f"  <h2>Race {rn}</h2>"
                f"  <div class='race-meta'>"
                f"    <span>📏 {dist}</span>"
                f"    <span>💰 Purse {purse}</span>"
                f"    <span>🐎 {len(df)} horses</span>"
                f"  </div>"
                f"  <div class='weight-pills'>{weight_pills}</div>"
                f"</div>"
                f"{results_section(rn, df, actual)}"
                f"<h3>Rankings</h3>"
                f"<p class='hint'>PP Rank column is the Prime Power benchmark — independent of our model.</p>"
                f"<table class='summary-table'>"
                f"<thead><tr>"
                f"<th>Model #</th><th>Horse</th><th>Odds</th>"
                f"<th>PP Rank ⚖</th><th>Composite Score</th>"
                f"<th>Win Probability</th>"
                f"{actual_headers}"
                f"<th>Analysis</th>"
                f"</tr></thead>"
                f"<tbody>{summary_rows(df, actual)}</tbody>"
                f"</table>"
                f"<h3>Component Scorecards</h3>"
                f"<p class='hint'>Click a horse to expand its full breakdown.</p>"
                f"{scorecard_rows(df)}"
                f"</div>"
            )

        first_race = f"race{race_nums[0]}"

        # ── full HTML document ─────────────────────────────────────────
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Parx Racing — Predictions</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --border: #2e3250; --text: #e8eaf6; --muted: #8892b0;
    --green: #2ecc71; --blue: #3498db; --purple: #9b59b6;
    --gold: #f1c40f; --radius: 8px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; }}

  /* ── header ── */
  .page-header {{ background: linear-gradient(135deg, #1a1d27 0%, #0f1117 100%);
    border-bottom: 1px solid var(--border); padding: 24px 32px; }}
  .page-header h1 {{ font-size: 1.6rem; color: var(--green); letter-spacing: 1px; }}
  .page-header p  {{ color: var(--muted); margin-top: 4px; font-size: 0.85rem; }}

  /* ── tab bar ── */
  .tab-bar {{ display: flex; flex-wrap: wrap; gap: 6px;
    padding: 16px 32px; background: var(--surface); border-bottom: 1px solid var(--border); }}
  .tab-btn {{ background: var(--surface2); border: 1px solid var(--border); color: var(--muted);
    border-radius: var(--radius); padding: 8px 16px; cursor: pointer;
    display: flex; flex-direction: column; align-items: center; gap: 2px;
    transition: all .15s; font-size: 0.85rem; font-weight: 600; }}
  .tab-btn:hover  {{ border-color: var(--blue); color: var(--text); }}
  .tab-btn.active {{ background: var(--blue); border-color: var(--blue); color: #fff; }}
  .tab-sub {{ font-size: 0.7rem; font-weight: 400; opacity: .85; }}

  /* ── panels ── */
  .tab-panel {{ display: none; padding: 28px 32px; max-width: 1200px; margin: 0 auto; }}
  .tab-panel.active {{ display: block; }}

  .race-header {{ margin-bottom: 20px; }}
  .race-header h2 {{ font-size: 1.3rem; color: var(--green); margin-bottom: 8px; }}
  .race-meta {{ display: flex; gap: 20px; color: var(--muted); font-size: 0.85rem; margin-bottom: 10px; }}
  .weight-pills {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .pill {{ background: var(--surface2); border: 1px solid var(--border);
    border-radius: 20px; padding: 2px 10px; font-size: 0.75rem; color: var(--muted); }}

  h3 {{ font-size: 1rem; color: var(--muted); text-transform: uppercase;
    letter-spacing: 1px; margin: 24px 0 12px; }}
  .hint {{ color: var(--muted); font-size: 0.8rem; margin-bottom: 12px; }}

  /* ── summary table ── */
  .summary-table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
  .summary-table th {{ background: var(--surface2); color: var(--muted);
    text-align: left; padding: 10px 12px; font-size: 0.75rem;
    text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid var(--border); }}
  .summary-table td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  .summary-table tr:hover td {{ background: var(--surface2); }}
  .horse-name {{ font-weight: 600; color: var(--text); }}
  .analysis   {{ color: var(--muted); font-size: 0.8rem; max-width: 260px; }}
  .medal      {{ font-size: 1.1rem; }}

  /* ── win prob bar ── */
  .bar-wrap {{ display: flex; align-items: center; gap: 8px; min-width: 160px; }}
  .bar      {{ height: 8px; border-radius: 4px; min-width: 2px; transition: width .3s; }}
  .bar-label {{ font-size: 0.8rem; color: var(--text); white-space: nowrap; }}

  /* ── horse accordion cards ── */
  .horse-card {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); margin-bottom: 10px; overflow: hidden; }}
  .horse-card summary {{ display: flex; align-items: center; gap: 12px;
    padding: 14px 18px; cursor: pointer; list-style: none;
    border-left: 4px solid transparent; }}
  .horse-card summary::-webkit-details-marker {{ display: none; }}
  .horse-card summary:hover {{ background: var(--surface2); }}
  .odds-badge  {{ margin-left: auto; color: var(--muted); font-size: 0.8rem; }}
  .score-badge {{ background: var(--surface2); border: 1px solid var(--border);
    border-radius: 4px; padding: 2px 8px; font-size: 0.8rem; color: var(--muted); }}
  .prob-badge  {{ border-radius: 4px; padding: 3px 10px;
    font-size: 0.85rem; font-weight: 700; color: #fff; }}

  .card-body {{ padding: 0 18px 18px; }}

  /* ── component table ── */
  .comp-table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  .comp-table th {{ background: var(--surface2); color: var(--muted);
    text-align: left; padding: 8px 12px; font-size: 0.72rem;
    text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid var(--border); }}
  .comp-table td {{ padding: 9px 12px; border-bottom: 1px solid var(--border);
    vertical-align: middle; font-size: 0.82rem; }}
  .comp-table tr:last-child td {{ border-bottom: none; }}
  .raw-val {{ color: var(--muted); max-width: 240px; }}

  .mini-bar-wrap {{ display: inline-block; width: 80px; height: 6px;
    background: var(--surface2); border-radius: 3px; margin-right: 8px;
    vertical-align: middle; }}
  .mini-bar {{ height: 6px; border-radius: 3px; }}

  .analysis-line {{ color: var(--muted); font-size: 0.8rem;
    margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }}

  /* ── rank comparison chart ── */
  .chart-box {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px 24px; margin: 16px 0; overflow-x: auto; }}
  .rank-chart {{ display: block; border-radius: 4px; }}

  /* ── results comparison ── */
  .results-box {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px 24px; margin-bottom: 24px; }}
  .stat-badges {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 16px; }}
  .stat-badge {{ border-radius: 20px; padding: 3px 12px; font-size: 0.78rem; font-weight: 600; }}
  .stat-good {{ background: #1a3a2a; color: var(--green); border: 1px solid var(--green); }}
  .stat-miss {{ background: #3a1a1a; color: #e74c3c;    border: 1px solid #e74c3c; }}
  .stat-warn {{ background: #3a2e1a; color: var(--gold); border: 1px solid var(--gold); }}
  .stat-info {{ background: var(--surface2); color: var(--blue); border: 1px solid var(--blue); }}

  .results-table {{ width: 100%; border-collapse: collapse; }}
  .results-table th {{ background: var(--surface2); color: var(--muted);
    text-align: left; padding: 8px 12px; font-size: 0.72rem;
    text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid var(--border); }}
  .results-table td {{ padding: 9px 12px; border-bottom: 1px solid var(--border); font-size: 0.85rem; }}
  .results-table tr.res-win  td {{ background: #0d2b1a; }}
  .results-table tr.res-place td {{ background: #0d1a2b; }}

  .delta       {{ font-size: 0.75rem; margin-left: 8px; font-weight: 600; }}
  .delta.exact  {{ color: var(--green); }}
  .delta.better {{ color: var(--blue); }}
  .delta.worse  {{ color: #e74c3c; }}
  .fin-badge   {{ border-radius: 4px; padding: 2px 8px; font-size: 0.78rem; font-weight: 600; }}
  .fin-win     {{ background: #1a3a2a; color: var(--green); }}
  .fin-place   {{ background: #0d1a2b; color: var(--blue); }}
  .fin-other   {{ background: var(--surface2); color: var(--muted); }}
  .muted       {{ color: var(--muted); }}

  /* ── footer ── */
  .page-footer {{ text-align: center; padding: 24px; color: var(--muted);
    font-size: 0.75rem; border-top: 1px solid var(--border); margin-top: 40px; }}
</style>
</head>
<body>

<div class="page-header">
  <h1>🏇 Parx Racing — Predictive Engine v4.0</h1>
  <p>Generated {datetime.now().strftime("%B %d, %Y at %I:%M %p")} &nbsp;·&nbsp;
     {len(race_dfs)} races &nbsp;·&nbsp;
     {sum(len(df) for df in race_dfs.values())} horses total</p>
</div>

<div class="tab-bar">
  {''.join(tab_buttons)}
</div>

{''.join(tab_panels)}

<div class="page-footer">
  Parx Racing Predictive Engine v4.0 (Kiro) &nbsp;·&nbsp;
  Model weights: {' | '.join(f"{self._SCORECARD_META[c][0]} {w:.0%}" for c, w in self.MODEL_WEIGHTS.items())}
</div>

<script>
  function showTab(id) {{
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    document.getElementById('btn-' + id).classList.add('active');
  }}
  // activate first tab on load
  showTab('{first_race}');
</script>
</body>
</html>"""

        out = pathlib.Path(output_path)
        out.write_text(html, encoding="utf-8")
        print(f"[+] HTML report saved → {out.resolve()}")

        if auto_open:
            webbrowser.open(out.resolve().as_uri())
            print("[*] Opened in browser.")

        return str(out.resolve())


# Main execution
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--pdf', default='prx0422y.pdf', help='PDF file path')
    parser.add_argument('--race', default='1', help='Race number to analyze')
    parser.add_argument('--plot', action='store_true', help='Show plot')
    parser.add_argument('--detailed', action='store_true', help='Show detailed model breakdown')
    parser.add_argument('--scorecard', action='store_true', help='Show full per-horse composite scorecard')
    parser.add_argument('--html', action='store_true', help='Export results to HTML and open in browser')
    parser.add_argument('--html-out', default='parx_results.html', help='HTML output file path')
    parser.add_argument('--diagnose', action='store_true', help='Print feature parse quality diagnostic')
    args = parser.parse_args()

    engine = ParxRacingEngineV4()

    print("\n" + "="*50)
    print(" PARX RACING PREDICTIVE ENGINE v4.0 (Kiro)")
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

            # ── Known actual results ──────────────────────────────────
            # Format: finish order 1st -> last, PP# noted for reference
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
                engine.export_html(output_path=args.html_out)
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
        print(f"[X] File not found: {args.pdf}")
