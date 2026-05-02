"""Feature engineering and prediction — mixin for HorseRacingEngine."""

import pandas as pd
import numpy as np


class FeaturesMixin:
    """
    Provides MODEL_WEIGHTS, feature metadata, normalization, and prediction.
    Expects instance attributes set by engine __init__:
        self.all_races  — dict
        self.race_info  — dict
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

    # Maps each MODEL_WEIGHTS key to (display_label, raw_format_fn).
    # raw_format_fn receives the row and returns a human-readable string.
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
        race_dist_f = race_info.get('distance_f', 0.0)

        features = []
        for horse in horses:
            # Class Delta: positive = dropping in class (advantage).
            if race_clm > 0 and horse.claim_price > 0:
                class_delta = (horse.claim_price - race_clm) / race_clm
            else:
                class_delta = 0.0

            # Distance Match: ratio of best speed at today's distance to overall best.
            best_at_dist = horse.best_speed_at_distance(race_dist_f) if race_dist_f > 0 else 0
            if horse.best_speed > 0 and best_at_dist > 0:
                dist_match = best_at_dist / horse.best_speed
            elif horse.best_speed > 0 and best_at_dist == 0:
                dist_match = 0.5    # no distance-specific data — neutral
            else:
                dist_match = 0.0

            # Surface / Mud Match: average sire and dam's sire mud SPI.
            mud_signals = [
                s for s in [horse.sire_mud_spi, horse.dam_sire_mud_spi] if s > 0
            ]
            surface_score = float(np.mean(mud_signals)) if mud_signals else 0.0

            earnings_per_start = (
                horse.earnings / horse.starts if horse.starts > 0 else 0.0
            )

            f = {
                'Horse':          horse.name,
                'PostPos':        horse.post_position,
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
                'Class_Delta':    class_delta,
                'Distance_Match': dist_match,
                'Surface_Score':  surface_score,
            }
            features.append(f)

        df = pd.DataFrame(features)
        df = self._normalize_features(df)

        if model_type == "simple":
            df['Composite_Score'] = df['PP_Score_Norm']
        else:
            df['Composite_Score'] = sum(
                df[col] * weight for col, weight in self.MODEL_WEIGHTS.items()
            )

        exp_scores = np.exp(df['Composite_Score'] - df['Composite_Score'].max())
        df['Win_Prob'] = exp_scores / exp_scores.sum()

        df['Analysis'] = df.apply(lambda row: self._generate_analysis(row, df), axis=1)

        return df.sort_values('Win_Prob', ascending=False)

    def _normalize_features(self, df):
        """Normalize features to [0, 1] using min-max scaling."""
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
        df['Class_Delta_Norm']    = self._minmax_scale(df['Class_Delta'])
        df['Distance_Match_Norm'] = self._minmax_scale(df['Distance_Match'])
        df['Surface_Match_Norm']  = self._minmax_scale(df['Surface_Score'])
        # No mud data → neutral (0.5) rather than penalized at the minimum
        df.loc[df['Surface_Score'] == 0.0, 'Surface_Match_Norm'] = 0.5
        return df
