"""
Diagnostic Reporter component for the Robust PDF Parsing System.

Generates comprehensive parse quality reports showing per-field and per-race
extraction success rates, validation failures, and recommended actions.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class FieldStats:
    """Statistics for a single field's extraction across all horses."""
    field_name: str
    total_attempts: int
    successful: int
    failed: int
    success_rate: float
    sample_failures: List[Tuple[str, str]] = field(default_factory=list)  # (horse_name, raw_text)

    def __str__(self) -> str:
        return (f"{self.field_name}: {self.successful}/{self.total_attempts} "
                f"({self.success_rate:.1%})")


@dataclass
class RaceStats:
    """Statistics for a single race's extraction."""
    race_num: str
    total_horses: int
    field_stats: Dict[str, FieldStats] = field(default_factory=dict)
    overall_success_rate: float = 0.0

    def compute_overall_rate(self) -> None:
        """Compute overall success rate as average across all fields."""
        if not self.field_stats:
            self.overall_success_rate = 0.0
            return
        rates = [fs.success_rate for fs in self.field_stats.values()]
        self.overall_success_rate = sum(rates) / len(rates)


class DiagnosticReporter:
    """
    Generates detailed parse quality reports for debugging and monitoring.

    Aggregates extraction statistics across all races and horses, flags
    low-quality races, and provides sample failures for debugging.
    """

    # Fields to track with their check functions and model weights
    FIELD_CHECKS = {
        'odds_parsed':        (lambda h: h.odds_parsed,                    0.18),
        'jockey_parsed':      (lambda h: h.jockey_win_pct > 0 or h.jockey_name != "", 0.15),
        'speed_parsed':       (lambda h: h.best_speed > 0,                 0.15),
        'form_parsed':        (lambda h: h.starts > 0,                     0.13),
        # Claim price is often legitimately absent in non-claiming races. Keep
        # reporting the fill rate, but do not flag a race solely because this is
        # missing.
        'claim_price_parsed': (lambda h: h.claim_price > 0,                0.00),
        'past_races_parsed':  (lambda h: len(h.past_races) > 0,            0.10),
        'trainer_parsed':     (lambda h: h.trainer_win_pct > 0 or h.trainer_name != "", 0.06),
        'style_parsed':       (lambda h: h.style_num > 0,                  0.02),
        'life_parsed':        (lambda h: h.starts > 0,                     0.02),
    }

    def generate_field_report(self, all_races: Dict[str, List]) -> Dict[str, FieldStats]:
        """
        Generate per-field extraction statistics across all races.

        Args:
            all_races: Dict mapping race_num to list of Horse objects

        Returns:
            Dict mapping field name to FieldStats
        """
        stats: Dict[str, FieldStats] = {}

        for field_name, (check_fn, _weight) in self.FIELD_CHECKS.items():
            total = 0
            successful = 0
            failures: List[Tuple[str, str]] = []

            for rn, horses in all_races.items():
                for horse in horses:
                    total += 1
                    if check_fn(horse):
                        successful += 1
                    else:
                        if len(failures) < 3:  # Keep first 3 sample failures
                            failures.append((horse.name, f"Race {rn}"))

            failed = total - successful
            rate = successful / total if total > 0 else 0.0
            stats[field_name] = FieldStats(
                field_name=field_name,
                total_attempts=total,
                successful=successful,
                failed=failed,
                success_rate=rate,
                sample_failures=failures,
            )

        return stats

    def generate_race_report(self, all_races: Dict[str, List]) -> Dict[str, RaceStats]:
        """
        Generate per-race extraction statistics.

        Args:
            all_races: Dict mapping race_num to list of Horse objects

        Returns:
            Dict mapping race_num to RaceStats
        """
        race_stats: Dict[str, RaceStats] = {}

        for rn in sorted(all_races.keys(), key=int):
            horses = all_races[rn]
            rs = RaceStats(race_num=rn, total_horses=len(horses))

            for field_name, (check_fn, _weight) in self.FIELD_CHECKS.items():
                total = len(horses)
                successful = sum(1 for h in horses if check_fn(h))
                failed = total - successful
                rate = successful / total if total > 0 else 0.0
                failures = [
                    (h.name, f"Race {rn}")
                    for h in horses if not check_fn(h)
                ][:3]
                rs.field_stats[field_name] = FieldStats(
                    field_name=field_name,
                    total_attempts=total,
                    successful=successful,
                    failed=failed,
                    success_rate=rate,
                    sample_failures=failures,
                )

            rs.compute_overall_rate()
            race_stats[rn] = rs

        return race_stats

    def flag_low_quality_races(self, all_races: Dict[str, List],
                               threshold: float = 0.8) -> List[str]:
        """
        Return list of race numbers with <threshold success rate for any weighted field.

        Args:
            all_races: Dict mapping race_num to list of Horse objects
            threshold: Minimum acceptable success rate (default 0.8 = 80%)

        Returns:
            List of race numbers with low quality fields
        """
        race_report = self.generate_race_report(all_races)
        flagged = []

        for rn, rs in race_report.items():
            for field_name, fs in rs.field_stats.items():
                weight = self.FIELD_CHECKS[field_name][1]
                if weight > 0 and fs.success_rate < threshold:
                    flagged.append(rn)
                    break  # Only flag each race once

        return sorted(flagged, key=int)

    def generate_quality_report(self, all_races: Dict[str, List],
                                 validation_results: Optional[Dict[str, Any]] = None,
                                 model_weights: Optional[Dict[str, float]] = None) -> str:
        """
        Generate comprehensive quality report combining extraction and validation stats.

        Args:
            all_races: Dict mapping race_num to list of Horse objects
            validation_results: Optional dict of validation results per horse
            model_weights: Optional dict of model feature weights for context

        Returns:
            Formatted string report
        """
        total_horses = sum(len(h) for h in all_races.values())
        total_races = len(all_races)

        field_report = self.generate_field_report(all_races)
        race_report = self.generate_race_report(all_races)
        flagged_races = self.flag_low_quality_races(all_races)

        lines = []
        lines.append("=" * 70)
        lines.append(f"  PARSE QUALITY DIAGNOSTIC  —  {total_horses} horses across {total_races} races")
        lines.append("=" * 70)
        lines.append(f"  {'Feature':<22} {'Field':<22} {'Parsed':>8} {'Missing':>8} {'Fill%':>7}  {'Weight':>7}")
        lines.append(f"  {'-'*65}")

        issues = []
        for field_name, fs in field_report.items():
            weight = self.FIELD_CHECKS[field_name][1]
            flag = "  <-- WARNING" if fs.success_rate < 0.5 and weight > 0 else ""
            lines.append(
                f"  {field_name:<22} {field_name:<22} {fs.successful:>8} {fs.failed:>8} "
                f"{fs.success_rate:>6.0%}  {weight:>6.0%}{flag}"
            )
            if fs.success_rate < 0.5 and weight > 0:
                issues.append((field_name, fs.success_rate, weight))

        lines.append(f"  {'-'*65}")

        if issues:
            lines.append(f"\n  HIGH-IMPACT MISSING FIELDS  (>50% unparsed with weight > 0%)")
            for fname, rate, w in sorted(issues, key=lambda x: -x[2]):
                lines.append(
                    f"    {fname}: {rate:.0%} fill  x  {w:.0%} weight"
                    f"  ->  contributing noise instead of signal"
                )

        # Per-race jockey parse rate (highest weighted unverified signal)
        lines.append(f"\n  PER-RACE JOCKEY PARSE RATE  (15% weight — highest unverified signal):")
        lines.append(f"  {'Race':<8} {'Horses':>8} {'Jockey OK':>10} {'Fill%':>7}")
        lines.append(f"  {'-'*36}")
        for rn in sorted(all_races.keys(), key=int):
            horses = all_races[rn]
            parsed = sum(1 for h in horses if h.jockey_win_pct > 0 or h.jockey_name != "")
            rate = parsed / len(horses) if horses else 0.0
            flag = "  <-- WARNING" if rate < 0.5 else ""
            lines.append(f"  {rn:<8} {len(horses):>8} {parsed:>10} {rate:>6.0%}{flag}")

        # Sample jockey values
        lines.append(f"\n  SAMPLE JOCKEY VALUES  (first 3 horses per race):")
        for rn in sorted(all_races.keys(), key=int):
            horses = all_races[rn][:3]
            samples = [
                (h.name, h.jockey_name or 'NOT PARSED', f"{h.jockey_win_pct:.1%}")
                for h in horses
            ]
            lines.append(f"  Race {rn}: " + "  |  ".join(
                f"{n} -> '{j}' {p}" for n, j, p in samples
            ))

        # Flagged races
        if flagged_races:
            lines.append(f"\n  FLAGGED RACES (< 80% on any weighted field): {', '.join(flagged_races)}")
            lines.append(f"  RECOMMENDED ACTIONS:")
            for rn in flagged_races:
                rs = race_report[rn]
                low_fields = [
                    f"{fn} ({fs.success_rate:.0%})"
                    for fn, fs in rs.field_stats.items()
                    if fs.success_rate < 0.8 and self.FIELD_CHECKS[fn][1] > 0
                ]
                lines.append(f"    Race {rn}: Review patterns for {', '.join(low_fields)}")

        lines.append(f"\n{'='*70}\n")
        return "\n".join(lines)
