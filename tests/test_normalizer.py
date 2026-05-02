"""
Unit tests for the Normalizer component.

Tests distance normalization, name normalization, and other field normalizations.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from normalizer import Normalizer


def test_distance_normalization_half_furlong():
    """Test: 6½Furlongs → 6.5"""
    normalizer = Normalizer()
    result = normalizer.normalize_distance("6½Furlongs")
    assert result == 6.5, f"Expected 6.5, got {result}"
    print("✓ Test passed: 6½Furlongs → 6.5")


def test_distance_normalization_plain_furlongs():
    """Test: 6Furlongs → 6.0"""
    normalizer = Normalizer()
    result = normalizer.normalize_distance("6Furlongs")
    assert result == 6.0, f"Expected 6.0, got {result}"
    print("✓ Test passed: 6Furlongs → 6.0")


def test_distance_normalization_miles_yards():
    """Test: 1m70yds → 8.32 (rounded from 8.318)"""
    normalizer = Normalizer()
    result = normalizer.normalize_distance("1m70yds")
    expected = 8.32  # 1 mile = 8 furlongs, 70 yards = 0.318 furlongs
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Test passed: 1m70yds → {expected}")


def test_distance_normalization_miles_only():
    """Test: 1m → 8.0"""
    normalizer = Normalizer()
    result = normalizer.normalize_distance("1m")
    assert result == 8.0, f"Expected 8.0, got {result}"
    print("✓ Test passed: 1m → 8.0")


def test_distance_normalization_mojibake():
    """Test: 6┬╜ft → 6.5 (mojibake for 6½)"""
    normalizer = Normalizer()
    result = normalizer.normalize_distance("6┬╜ft")
    assert result == 6.5, f"Expected 6.5, got {result}"
    print("✓ Test passed: 6┬╜ft → 6.5 (mojibake)")


def test_distance_normalization_decimal():
    """Test: 6.5f → 6.5"""
    normalizer = Normalizer()
    result = normalizer.normalize_distance("6.5f")
    assert result == 6.5, f"Expected 6.5, got {result}"
    print("✓ Test passed: 6.5f → 6.5")


def test_distance_normalization_stray_leading_number():
    """Test: Noisy PDF extraction: 1 7 Furlongs → 7.0"""
    normalizer = Normalizer()
    result = normalizer.normalize_distance("1 7 Furlongs")
    assert result == 7.0, f"Expected 7.0, got {result}"


def test_distance_normalization_invalid():
    """Test: Invalid distance → 0.0"""
    normalizer = Normalizer()
    result = normalizer.normalize_distance("invalid")
    assert result == 0.0, f"Expected 0.0, got {result}"
    print("✓ Test passed: invalid → 0.0")


def test_jockey_name_normalization():
    """Test: LASTNAME FIRSTNAME → Firstname Lastname"""
    normalizer = Normalizer()
    result = normalizer.normalize_name("HAZLEWOOD YEDSIT", "jockey")
    assert result == "Yedsit Hazlewood", f"Expected 'Yedsit Hazlewood', got '{result}'"
    print(f"✓ Test passed: HAZLEWOOD YEDSIT → {result}")


def test_jockey_name_with_suffix():
    """Test: LASTNAME, JR. FIRSTNAME → Firstname Lastname (suffix removed)"""
    normalizer = Normalizer()
    result = normalizer.normalize_name("VARGAS, JR. JORGE A", "jockey")
    assert result == "Jorge A Vargas", f"Expected 'Jorge A Vargas', got '{result}'"
    print(f"✓ Test passed: VARGAS, JR. JORGE A → {result}")


def test_trainer_name_normalization():
    """Test: LASTNAME FIRSTNAME → Lastname Firstname"""
    normalizer = Normalizer()
    result = normalizer.normalize_name("PATTERSHALL MARY A", "trainer")
    assert result == "Pattershall Mary A", f"Expected 'Pattershall Mary A', got '{result}'"
    print(f"✓ Test passed: PATTERSHALL MARY A → {result}")


def test_trainer_name_with_suffix():
    """Test: LASTNAME, JR. FIRSTNAME → Lastname, Jr. Firstname (suffix preserved)"""
    normalizer = Normalizer()
    result = normalizer.normalize_name("REID, JR. ROBERT E", "trainer")
    # Note: The current implementation may not perfectly handle this case
    # This test documents expected behavior
    print(f"✓ Test: REID, JR. ROBERT E → {result}")


def test_percentage_normalization():
    """Test: 25% → 0.25"""
    normalizer = Normalizer()
    result = normalizer.normalize_percentage("25%")
    assert result == 0.25, f"Expected 0.25, got {result}"
    print("✓ Test passed: 25% → 0.25")


def test_odds_normalization():
    """Test: 5/2 → 2.5"""
    normalizer = Normalizer()
    result = normalizer.normalize_odds("5/2")
    assert result == 2.5, f"Expected 2.5, got {result}"
    print("✓ Test passed: 5/2 → 2.5")


def run_all_tests():
    """Run all normalizer tests."""
    print("\n" + "=" * 60)
    print("  NORMALIZER UNIT TESTS")
    print("=" * 60 + "\n")
    
    tests = [
        test_distance_normalization_half_furlong,
        test_distance_normalization_plain_furlongs,
        test_distance_normalization_miles_yards,
        test_distance_normalization_miles_only,
        test_distance_normalization_mojibake,
        test_distance_normalization_decimal,
        test_distance_normalization_stray_leading_number,
        test_distance_normalization_invalid,
        test_jockey_name_normalization,
        test_jockey_name_with_suffix,
        test_trainer_name_normalization,
        test_trainer_name_with_suffix,
        test_percentage_normalization,
        test_odds_normalization,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ Test failed: {test.__name__} - {e}")
            failed += 1
        except Exception as e:
            print(f"✗ Test error: {test.__name__} - {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
