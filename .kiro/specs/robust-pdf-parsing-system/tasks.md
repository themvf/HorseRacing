# Implementation Plan: Robust PDF Parsing System

## Overview

This implementation plan transforms the existing parx_engine_v4_kiro.py parser into a robust, maintainable system with systematic validation, configuration-driven patterns, and comprehensive testing. The plan follows a 5-phase migration path that incrementally adds capabilities while maintaining backward compatibility.

**Current State**: parx_engine_v4_kiro.py achieves 82% overall jockey parsing accuracy but drops to 43% in some races, has distance format normalization issues (6½ → 6.0), and lacks systematic validation or regression testing.

**Target State**: >95% extraction accuracy for critical fields, configuration-driven patterns, comprehensive validation framework, and property-based testing preventing future regressions.

## Tasks

- [ ] 1. Phase 1: Validation Framework
  - [x] 1.1 Create validation data models and configuration structure
    - Create `ValidationRule` dataclass with fields: field, rule_type, constraint, severity, message
    - Create `ValidationResult` dataclass with fields: field, value, is_valid, rule, message
    - Create `ValidationConfig` dataclass with fields: version, rules (Dict[str, List[ValidationRule]])
    - Implement `ValidationConfig.to_json()` and `ValidationConfig.from_json()` methods
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 11.1, 11.4_

  - [x] 1.2 Implement Validator component with rule evaluation
    - Create `Validator` class with `__init__(config: ValidationConfig)` method
    - Implement `validate_field(field: str, value: Any) -> ValidationResult` method
    - Implement `validate_horse_record(record: Horse) -> List[ValidationResult]` method
    - Implement `validate_race_record(record: List[Horse]) -> Dict[str, List[ValidationResult]]` method
    - Support rule types: "range", "enum", "pattern", "custom" (callable)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 1.3 Create validation configuration file with rules for all critical fields
    - Create `config/validation.json` with validation rules for: jockey_win_pct, trainer_win_pct, odds, distance, best_speed, claim_price
    - Define range constraints: jockey_win_pct [0.0, 1.0], trainer_win_pct [0.0, 1.0], distance [3.0, 12.0], best_speed [0, 150]
    - Define custom constraint for claim_price: 0 or >= 2500
    - Set appropriate severity levels (error vs warning)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 1.4 Integrate validation into existing parser pipeline
    - Add `validation_results: List[ValidationResult]` field to Horse class
    - Call `validator.validate_horse_record()` after `horse.compute_features()` in `_parse_horse_block()`
    - Store validation results in horse.validation_results
    - Log validation failures with field name, value, and constraint
    - _Requirements: 6.7, 6.8_

  - [ ]* 1.5 Write unit tests for Validator component
    - Test range validation for all percentage fields
    - Test range validation for distance and speed figures
    - Test custom validation for claim_price
    - Test validation result structure and messages
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [ ] 2. Phase 2: Configuration-Driven Patterns
  - [x] 2.1 Create pattern configuration data models
    - Create `FieldPattern` dataclass with fields: name, patterns (List[str]), default_value, pre_filter, exclude_keywords
    - Create `PatternConfig` dataclass with fields: version, fields (Dict[str, FieldPattern])
    - Implement `PatternConfig.to_json()` and `PatternConfig.from_json()` methods
    - Add error handling for malformed configuration with descriptive error messages
    - _Requirements: 10.1, 10.2, 11.1, 11.2, 11.4_

  - [x] 2.2 Extract existing patterns to configuration file
    - Create `config/patterns.json` with extraction patterns for: jockey_name, trainer_name, odds, distance, claim_price, best_speed, past_performance
    - Define multiple patterns per field with priority order (attempt sequentially until success)
    - Include pre_filter strings for performance optimization
    - Include exclude_keywords for jockey parsing (skip lines with "Trnr:", "Life:", "Sire", "Dam", "JKYw", "PRX", "Trf")
    - _Requirements: 3.7, 8.2, 10.1, 10.4, 10.5, 10.6_

  - [x] 2.3 Refactor Parser to load patterns from configuration
    - Modify `ParxRacingEngineV4.__init__()` to accept `PatternConfig` parameter
    - Load pattern configuration from file path or use default configuration
    - Compile all regex patterns once at initialization for performance
    - Store compiled patterns in instance variable for reuse
    - _Requirements: 10.1, 10.4, 12.3, 12.4_

  - [x] 2.4 Implement pattern priority logic in field extraction
    - Modify field extraction methods to iterate through patterns in priority order
    - Attempt each pattern sequentially until one succeeds
    - Log which pattern successfully matched for each field
    - Set `{field}_parsed` flag to True only on successful extraction
    - _Requirements: 10.4, 10.5, 10.6_

  - [ ]* 2.5 Write unit tests for pattern configuration loading
    - Test PatternConfig.from_json() with valid configuration
    - Test PatternConfig.from_json() with invalid configuration (malformed patterns)
    - Test pattern priority logic (first pattern succeeds, fallback to second pattern)
    - Test pre_filter optimization (skip pattern if pre_filter not in text)
    - _Requirements: 11.1, 11.2, 10.4_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Phase 3: Regression Testing Framework
  - [x] 4.1 Create baseline extraction results from existing parser
    - Run parx_engine_v4_kiro.py on 3-5 representative PDF files
    - Store extraction results in `tests/baselines/{pdf_name}_baseline.json` format
    - Include per-race field extraction counts (jockey_parsed_count, trainer_parsed_count, etc.)
    - Include per-field success rates across all races
    - _Requirements: 9.1, 9.6_

  - [x] 4.2 Implement regression test suite
    - Create `tests/test_parser_regression.py` with regression test functions
    - Implement `load_baseline(path: str) -> dict` helper function
    - Implement regression test for each baseline PDF file
    - Compare current extraction results against baseline results
    - Flag regressions when field accuracy drops >5% from baseline
    - _Requirements: 9.4, 9.5, 9.7_

  - [x] 4.3 Add regression tests for known format variations
    - Add test case for standard format (baseline)
    - Add test case for mojibake corruption (encoding issues)
    - Add test case for missing fields (incomplete data)
    - Add test case for format variants (different stat layouts)
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ]* 4.4 Write integration tests with ground truth data
    - Create `tests/data/{pdf_name}_ground_truth.json` with manually verified extraction results
    - Implement integration test comparing parser output against ground truth
    - Test all critical fields: jockey_name, jockey_win_pct, trainer_name, trainer_win_pct, odds, distance, best_speed
    - Assert extraction accuracy >95% for critical fields
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [ ] 5. Phase 4: Fix Specific Issues
  - [x] 5.1 Fix jockey parsing failures (Race 8 format)
    - Add diagnostic logging to capture raw text blocks for failed jockey extractions
    - Analyze Race 8 text blocks to identify format variant
    - Add new jockey pattern to configuration with priority order
    - Test jockey parsing on Race 8 to verify >95% accuracy
    - _Requirements: 1.1, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 5.2 Implement Normalizer component for distance formats
    - Create `Normalizer` class with distance normalization methods
    - Implement `normalize_distance(raw: str) -> float` method
    - Add Unicode fraction character mapping: {'½': 0.5, '¼': 0.25, '¾': 0.75}
    - Add mojibake pattern detection: extract leading digit and infer fraction from context
    - Handle formats: "6½Furlongs" → 6.5, "1m70yds" → 8.318, "1m" → 8.0, "6┬╜ft" → 6.5
    - Return 0.0 for unparseable distances and log raw text
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 5.3 Implement name normalization methods
    - Implement `normalize_name(raw: str, name_type: str) -> str` method
    - Handle jockey names: "LASTNAME FIRSTNAME" → "Firstname Lastname", remove suffixes (JR, SR, II, III, IV)
    - Handle trainer names: "LASTNAME FIRSTNAME" → "Lastname Firstname", preserve suffixes
    - Handle punctuation variations (comma, period, apostrophe)
    - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 8.3_

  - [x] 5.4 Implement additional normalization methods
    - Implement `normalize_percentage(raw: str) -> float` method ("25%" → 0.25)
    - Implement `normalize_odds(raw: str) -> float` method ("5/2" → 2.5)
    - Implement `normalize_horse_record(record: Horse) -> Horse` method applying all normalization rules
    - _Requirements: 3.4, 4.3, 8.2_

  - [x] 5.5 Integrate Normalizer into parser pipeline
    - Call `normalizer.normalize_horse_record()` after field extraction in `_parse_horse_block()`
    - Replace inline normalization logic with Normalizer method calls
    - Maintain backward compatibility with existing Horse class structure
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 5.6 Fix E1/E2 parsing ambiguity
    - Add two E1/E2 patterns with priority: spaced pattern first ("82 78/"), jammed pattern as fallback ("95104/")
    - Jammed pattern: extract first 2 digits as class rating, next 2-3 as E1
    - Update past performance parsing in `_parse_horse_block()` to use both patterns
    - Add diagnostic logging to track which pattern matched
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 5.7 Fix distance parsing in past performance lines
    - Extract distance from past performance lines using leading digit patterns
    - Handle mile races: "1m" or mojibake "├á1╦åfm" → extract leading digit and convert to furlongs
    - Normalize distance to furlongs using Normalizer.normalize_distance()
    - Store normalized distance in past_races dictionary
    - _Requirements: 5.4, 5.5, 5.6_

  - [ ]* 5.8 Write unit tests for Normalizer component
    - Test distance normalization for all format variants (6½Furlongs, 1m70yds, 1m, mojibake)
    - Test name normalization for jockey and trainer formats
    - Test percentage and odds normalization
    - Test error handling for unparseable values
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3, 4.1, 4.2_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Phase 5: Property-Based Testing
  - [x] 7.1 Set up property-based testing framework
    - Install `hypothesis` library for property-based testing
    - Create `tests/property/` directory for property tests
    - Configure hypothesis with minimum 100 iterations per property test
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 11.4_

  - [ ]* 7.2 Write property test for distance normalization (Property 1)
    - **Property 1: Distance Normalization Produces Valid Furlongs**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**
    - Generate random distance strings in all supported formats
    - Assert normalized distance is in range [3.0, 12.0] with 2 decimal places
    - Test with 100+ random inputs

  - [ ]* 7.3 Write property test for invalid distance normalization (Property 2)
    - **Property 2: Invalid Distance Normalization Returns Zero**
    - **Validates: Requirement 2.7**
    - Generate random invalid distance strings
    - Assert normalized distance is 0.0 and raw text is logged

  - [ ]* 7.4 Write property test for jockey name normalization (Property 3)
    - **Property 3: Jockey Name Normalization Produces Title Case**
    - **Validates: Requirements 3.1, 3.2, 3.3**
    - Generate random jockey names in all supported formats
    - Assert normalized name is in title case with suffixes removed

  - [ ]* 7.5 Write property test for trainer name normalization (Property 4)
    - **Property 4: Trainer Name Normalization Preserves Suffixes**
    - **Validates: Requirements 4.1, 4.2**
    - Generate random trainer names in all supported formats
    - Assert normalized name is in title case with suffixes preserved

  - [ ]* 7.6 Write property test for stats parsing (Property 5)
    - **Property 5: Stats Parsing Extracts Valid Win Percentage**
    - **Validates: Requirements 3.4, 4.3**
    - Generate random stats strings in format "(starts wins-places-shows win%)"
    - Assert extracted win percentage is in range [0.0, 1.0]

  - [ ]* 7.7 Write property test for keyword line skipping (Property 6)
    - **Property 6: Keyword Lines Are Skipped**
    - **Validates: Requirement 3.7**
    - Generate random text lines containing keywords
    - Assert parser skips those lines when searching for jockey names

  - [ ]* 7.8 Write property test for invalid jockey blocks (Property 7)
    - **Property 7: Invalid Jockey Blocks Return Defaults**
    - **Validates: Requirement 3.6**
    - Generate random invalid jockey text blocks
    - Assert parser returns empty string for jockey_name and 0.0 for jockey_win_pct

  - [ ]* 7.9 Write property test for past performance parsing (Property 8)
    - **Property 8: Past Performance Parsing Extracts Valid Values**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.6**
    - Generate random past performance lines in valid format
    - Assert extracted E1, E2, and speed values are valid (E1 > 0, E2 > 0, speed in [0, 150])

  - [ ]* 7.10 Write property test for percentage validation (Property 9)
    - **Property 9: Percentage Validation Identifies Valid Range**
    - **Validates: Requirements 6.1, 6.2**
    - Generate random percentage values across full range
    - Assert validator correctly identifies values in [0.0, 1.0] as valid

  - [ ]* 7.11 Write property test for odds validation (Property 10)
    - **Property 10: Odds Validation Identifies Positive Values**
    - **Validates: Requirement 6.3**
    - Generate random odds values including negative and zero
    - Assert validator correctly identifies positive values as valid

  - [ ]* 7.12 Write property test for distance validation (Property 11)
    - **Property 11: Distance Validation Identifies Typical Range**
    - **Validates: Requirement 6.4**
    - Generate random distance values across full range
    - Assert validator correctly identifies values in [3.0, 12.0] as valid

  - [ ]* 7.13 Write property test for speed figure validation (Property 12)
    - **Property 12: Speed Figure Validation Identifies Valid Range**
    - **Validates: Requirement 6.5**
    - Generate random speed figure values across full range
    - Assert validator correctly identifies values in [0, 150] as valid

  - [ ]* 7.14 Write property test for claim price validation (Property 13)
    - **Property 13: Claim Price Validation Identifies Valid Values**
    - **Validates: Requirement 6.6**
    - Generate random claim price values
    - Assert validator correctly identifies 0 or >= 2500 as valid

  - [ ]* 7.15 Write property test for invalid field validation logging (Property 14)
    - **Property 14: Invalid Field Validation Logs Details**
    - **Validates: Requirement 6.7**
    - Generate random invalid field values
    - Assert validator logs message containing field name, value, and constraint

  - [ ]* 7.16 Write property test for configuration round-trip (Property 15)
    - **Property 15: Configuration Round-Trip Preserves Semantics**
    - **Validates: Requirement 11.4**
    - Generate random valid PatternConfig and ValidationConfig objects
    - Assert serialize → deserialize produces equivalent configuration

  - [ ]* 7.17 Write property test for invalid configuration error messages (Property 16)
    - **Property 16: Invalid Configuration Returns Descriptive Error**
    - **Validates: Requirement 11.2**
    - Generate random invalid configuration JSON strings
    - Assert parser returns error message identifying malformed pattern/rule

- [ ] 8. Diagnostic Reporter Component
  - [x] 8.1 Create diagnostic data models
    - Create `FieldStats` dataclass with fields: field_name, total_attempts, successful, failed, success_rate, sample_failures
    - Create `RaceStats` dataclass with fields: race_num, total_horses, field_stats, overall_success_rate
    - _Requirements: 7.4, 7.5_

  - [x] 8.2 Implement DiagnosticReporter component
    - Create `DiagnosticReporter` class
    - Implement `generate_field_report(races: List[RaceRecord]) -> Dict[str, FieldStats]` method
    - Implement `generate_race_report(races: List[RaceRecord]) -> Dict[str, RaceStats]` method
    - Implement `generate_quality_report(races, validation_results) -> str` method
    - Implement `flag_low_quality_races(races, threshold=0.8) -> List[str]` method
    - _Requirements: 1.8, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [x] 8.3 Integrate DiagnosticReporter into parser pipeline
    - Call `reporter.generate_quality_report()` after parsing all races
    - Print quality report to console or save to file
    - Flag races with <80% success rate for any weighted field
    - Include sample raw text for failed extractions
    - _Requirements: 7.1, 7.2, 7.3, 7.6, 7.7_

  - [ ]* 8.4 Write unit tests for DiagnosticReporter component
    - Test field report generation with sample extraction results
    - Test race report generation with sample extraction results
    - Test quality report formatting and content
    - Test low quality race flagging with threshold
    - _Requirements: 7.4, 7.5, 7.6_

- [ ] 9. Final Integration and Wiring
  - [x] 9.1 Wire all components together in main parser class
    - Update `ParxRacingEngineV4.__init__()` to initialize Parser, Normalizer, Validator, DiagnosticReporter
    - Update `parse_races()` to call Normalizer and Validator after extraction
    - Update `parse_races()` to call DiagnosticReporter after all races parsed
    - Maintain backward compatibility with existing API
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 9.2 Add performance optimizations
    - Use O(n) text extraction with list + join (already implemented in v4)
    - Compile all regex patterns once at initialization
    - Use line-by-line matching for complex patterns to avoid catastrophic backtracking
    - Implement lazy validation (only validate successfully parsed fields)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 9.3 Update documentation and usage examples
    - Add docstrings to all new classes and methods
    - Create usage examples for configuration files
    - Document migration path from v4 to new system
    - Add README with setup instructions and examples
    - _Requirements: 10.1, 10.2, 10.3, 11.1_

  - [ ]* 9.4 Write end-to-end integration tests
    - Test complete pipeline: PDF → Parser → Normalizer → Validator → DiagnosticReporter
    - Test with 3-5 representative PDF files
    - Assert >95% extraction accuracy for critical fields
    - Assert validation reports are generated correctly
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (Properties 1-16 from design document)
- Unit tests validate specific examples and edge cases
- Integration tests validate end-to-end parsing with representative PDF files
- Regression tests prevent future breakage by comparing against baseline results

## Migration Strategy

This plan maintains backward compatibility with parx_engine_v4_kiro.py throughout the migration:

1. **Phase 1** adds validation as a new capability without modifying existing parsing logic
2. **Phase 2** refactors patterns to configuration while maintaining identical parsing behavior
3. **Phase 3** establishes regression testing baseline from current parser before making changes
4. **Phase 4** fixes specific issues (jockey parsing, distance normalization, E1/E2) with regression tests ensuring no breakage
5. **Phase 5** adds property-based testing as a comprehensive correctness guarantee

Each phase can be deployed independently, allowing incremental rollout and validation.
