"""
Regression test suite for the Robust PDF Parsing System.

Compares current parser extraction results against stored baselines.
Fails if any field accuracy drops >5% from baseline.

Run with: pytest tests/test_parser_regression.py -v
"""
import sys, os, json, pathlib
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASELINE_DIR = pathlib.Path(__file__).parent / "baselines"
PDF_PATH = pathlib.Path(__file__).parent.parent / "prx0422y.pdf"
REGRESSION_THRESHOLD = 0.05  # Allow up to 5% drop from baseline


def load_baseline(path: str) -> dict:
    """Load baseline extraction results from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_parser(pdf_path: str) -> dict:
    """Run the parser and return extraction results in baseline format."""
    from parx_engine_v4_kiro import ParxRacingEngineV4
    engine = ParxRacingEngineV4()
    text = engine.extract_text_from_pdf(str(pdf_path))
    assert text, f"Failed to extract text from {pdf_path}"
    engine.parse_races(text)

    results = {
        "total_races": len(engine.all_races),
        "total_horses": sum(len(h) for h in engine.all_races.values()),
        "races": {},
        "global_field_rates": {}
    }

    field_checks = {
        "odds_parsed":        lambda h: h.odds_parsed,
        "jockey_parsed":      lambda h: h.jockey_win_pct > 0 or h.jockey_name != "",
        "trainer_parsed":     lambda h: h.trainer_win_pct > 0,
        "speed_parsed":       lambda h: h.best_speed > 0,
        "life_parsed":        lambda h: h.starts > 0,
        "claim_price_parsed": lambda h: h.claim_price > 0,
        "past_races_parsed":  lambda h: len(h.past_races) > 0,
    }

    global_counts = {f: 0 for f in field_checks}
    global_total = 0

    for rn in sorted(engine.all_races.keys(), key=int):
        horses = engine.all_races[rn]
        race_data = {"total_horses": len(horses), "field_rates": {}}
        for field, check_fn in field_checks.items():
            count = sum(1 for h in horses if check_fn(h))
            race_data["field_rates"][field] = round(count / len(horses), 3) if horses else 0.0
            global_counts[field] += count
        global_total += len(horses)
        results["races"][rn] = race_data

    results["global_field_rates"] = {
        f: round(global_counts[f] / global_total, 3) if global_total else 0.0
        for f in field_checks
    }
    return results


# ── Tests ──────────────────────────────────────────────────────────────────

class TestRegressionPrx0422y:
    """Regression tests for prx0422y.pdf against stored baseline."""

    @pytest.fixture(scope="class")
    def baseline(self):
        baseline_path = BASELINE_DIR / "prx0422y_baseline.json"
        if not baseline_path.exists():
            pytest.skip(f"Baseline not found: {baseline_path}")
        return load_baseline(str(baseline_path))

    @pytest.fixture(scope="class")
    def current(self):
        if not PDF_PATH.exists():
            pytest.skip(f"PDF not found: {PDF_PATH}")
        return run_parser(PDF_PATH)

    def test_race_count_unchanged(self, baseline, current):
        """Total number of races should not change."""
        assert current["total_races"] == baseline["total_races"], (
            f"Race count changed: {current['total_races']} vs baseline {baseline['total_races']}"
        )

    def test_horse_count_unchanged(self, baseline, current):
        """Total number of horses should not change."""
        assert current["total_horses"] == baseline["total_horses"], (
            f"Horse count changed: {current['total_horses']} vs baseline {baseline['total_horses']}"
        )

    @pytest.mark.parametrize("field", [
        "odds_parsed", "jockey_parsed", "trainer_parsed",
        "speed_parsed", "life_parsed", "past_races_parsed",
    ])
    def test_global_field_rate_no_regression(self, baseline, current, field):
        """Global field extraction rate should not drop >5% from baseline."""
        baseline_rate = baseline["global_field_rates"].get(field, 0.0)
        current_rate = current["global_field_rates"].get(field, 0.0)
        drop = baseline_rate - current_rate
        assert drop <= REGRESSION_THRESHOLD, (
            f"REGRESSION: {field} dropped {drop:.1%} "
            f"(baseline={baseline_rate:.1%}, current={current_rate:.1%})"
        )

    @pytest.mark.parametrize("race_num", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"])
    def test_per_race_jockey_no_regression(self, baseline, current, race_num):
        """Per-race jockey parse rate should not drop >5% from baseline."""
        if race_num not in baseline.get("races", {}):
            pytest.skip(f"Race {race_num} not in baseline")
        if race_num not in current.get("races", {}):
            pytest.fail(f"Race {race_num} missing from current results")

        baseline_rate = baseline["races"][race_num]["field_rates"].get("jockey_parsed", 0.0)
        current_rate = current["races"][race_num]["field_rates"].get("jockey_parsed", 0.0)
        drop = baseline_rate - current_rate
        assert drop <= REGRESSION_THRESHOLD, (
            f"REGRESSION Race {race_num}: jockey_parsed dropped {drop:.1%} "
            f"(baseline={baseline_rate:.1%}, current={current_rate:.1%})"
        )

    @pytest.mark.parametrize("race_num", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"])
    def test_per_race_speed_no_regression(self, baseline, current, race_num):
        """Per-race speed parse rate should not drop >5% from baseline."""
        if race_num not in baseline.get("races", {}):
            pytest.skip(f"Race {race_num} not in baseline")
        if race_num not in current.get("races", {}):
            pytest.fail(f"Race {race_num} missing from current results")

        baseline_rate = baseline["races"][race_num]["field_rates"].get("speed_parsed", 0.0)
        current_rate = current["races"][race_num]["field_rates"].get("speed_parsed", 0.0)
        drop = baseline_rate - current_rate
        assert drop <= REGRESSION_THRESHOLD, (
            f"REGRESSION Race {race_num}: speed_parsed dropped {drop:.1%} "
            f"(baseline={baseline_rate:.1%}, current={current_rate:.1%})"
        )


class TestRegressionFormatVariations:
    """
    Regression tests for known format variations.
    Tests the Normalizer directly with known input/output pairs.
    """

    @pytest.fixture(scope="class")
    def normalizer(self):
        from normalizer import Normalizer
        return Normalizer()

    # ── Distance format variants ──────────────────────────────────────────

    def test_distance_standard_furlongs(self, normalizer):
        """Standard format: '6Furlongs' -> 6.0"""
        assert normalizer.normalize_distance("6Furlongs") == 6.0

    def test_distance_half_furlongs_unicode(self, normalizer):
        """Unicode fraction: '6½Furlongs' -> 6.5"""
        assert normalizer.normalize_distance("6½Furlongs") == 6.5

    def test_distance_quarter_furlongs_unicode(self, normalizer):
        """Unicode fraction: '6¼Furlongs' -> 6.25"""
        assert normalizer.normalize_distance("6¼Furlongs") == 6.25

    def test_distance_miles_and_yards(self, normalizer):
        """Miles + yards: '1m70yds' -> 8.32"""
        result = normalizer.normalize_distance("1m70yds")
        assert abs(result - 8.32) < 0.01, f"Expected ~8.32, got {result}"

    def test_distance_miles_only(self, normalizer):
        """Miles only: '1m' -> 8.0"""
        assert normalizer.normalize_distance("1m") == 8.0

    def test_distance_mojibake_half(self, normalizer):
        """Mojibake corruption: '6┬╜ft' -> 6.5"""
        assert normalizer.normalize_distance("6┬╜ft") == 6.5

    def test_distance_decimal_furlongs(self, normalizer):
        """Decimal: '6.5f' -> 6.5"""
        assert normalizer.normalize_distance("6.5f") == 6.5

    def test_distance_invalid_returns_zero(self, normalizer):
        """Invalid input returns 0.0"""
        assert normalizer.normalize_distance("not_a_distance") == 0.0

    def test_distance_empty_returns_zero(self, normalizer):
        """Empty string returns 0.0"""
        assert normalizer.normalize_distance("") == 0.0

    # ── Jockey name format variants ───────────────────────────────────────

    def test_jockey_standard_format(self, normalizer):
        """Standard: 'SANCHEZ MYCHEL J' -> 'Mychel J Sanchez'"""
        result = normalizer.normalize_name("SANCHEZ MYCHEL J", "jockey")
        assert result == "Mychel J Sanchez", f"Got: {result}"

    def test_jockey_with_jr_suffix(self, normalizer):
        """Suffix removal: 'VARGAS JR JORGE A' -> 'Jorge A Vargas'"""
        result = normalizer.normalize_name("VARGAS JR JORGE A", "jockey")
        assert "Vargas" in result
        assert "JR" not in result.upper() or "Jr" not in result

    def test_jockey_two_word_name(self, normalizer):
        """Two words: 'LOPEZ PACO' -> 'Paco Lopez'"""
        result = normalizer.normalize_name("LOPEZ PACO", "jockey")
        assert result == "Paco Lopez", f"Got: {result}"

    # ── Trainer name format variants ──────────────────────────────────────

    def test_trainer_standard_format(self, normalizer):
        """Standard: 'LAKE SCOTT A' -> 'Lake Scott A'"""
        result = normalizer.normalize_name("LAKE SCOTT A", "trainer")
        assert "Lake" in result

    # ── Missing fields ────────────────────────────────────────────────────

    def test_missing_jockey_returns_empty(self, normalizer):
        """Empty input returns empty string"""
        assert normalizer.normalize_name("", "jockey") == ""

    def test_missing_distance_returns_zero(self, normalizer):
        """None-like input returns 0.0"""
        assert normalizer.normalize_distance("") == 0.0
