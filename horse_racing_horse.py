"""Horse data model — individual horse with all parsed attributes."""

import numpy as np


class Horse:
    """Individual horse with comprehensive data."""

    def __init__(self, name):
        self.name = name
        self.odds = 0.0
        # Fix 4: track whether odds were actually parsed from the PDF.
        # When False, market-based value analysis is skipped to avoid
        # comparing model output against the 10.0 fallback.
        self.odds_parsed = False

        self.post_position = 0
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
        self.trainer_stats = ""
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
        self.recent_form = ""
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
            midfield = (n + 1) / 2
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
