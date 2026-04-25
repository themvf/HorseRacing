# Requirements Document: Robust PDF Parsing System

## Introduction

This document specifies requirements for a robust, repeatable horse racing PDF parsing system. The system extracts structured data from horse racing past performance PDFs with high accuracy, validates extracted fields against expected patterns, handles format variations gracefully, and provides clear diagnostics when parsing fails.

The current parser (parx_engine_v4_kiro.py) achieves 82% overall jockey parsing accuracy but drops to 43% in some races, has distance format normalization issues (6½ → 6.0), and lacks systematic validation or regression testing. This system will establish a repeatable process that works reliably across different PDF formats.

## Glossary

- **Parser**: The component that extracts structured data from PDF text
- **Validator**: The component that verifies extracted data against expected patterns
- **Normalizer**: The component that converts extracted values to canonical formats
- **Diagnostic_Reporter**: The component that generates detailed error reports
- **Field**: A single data element extracted from the PDF (e.g., jockey name, distance, odds)
- **Horse_Record**: A complete set of fields for one horse in one race
- **Race_Record**: A complete set of Horse_Records for one race
- **PDF_Document**: The input horse racing past performance PDF file
- **Extraction_Pattern**: A regular expression or parsing rule used to extract a field
- **Validation_Rule**: A constraint that defines valid values for a field
- **Format_Variant**: A different representation of the same data (e.g., "6½Furlongs" vs "6.0f")
- **Parse_Quality_Report**: A diagnostic output showing field extraction success rates
- **Regression_Test_Suite**: A collection of tests ensuring parser changes don't break existing functionality
- **Mojibake**: Character encoding corruption (e.g., "6½" → "6┬╜")

## Requirements

### Requirement 1: High-Accuracy Field Extraction

**User Story:** As a data analyst, I want the parser to extract all critical fields with >95% accuracy, so that I can rely on the data for predictive modeling.

#### Acceptance Criteria

1. WHEN a valid horse racing PDF is provided, THE Parser SHALL extract jockey names with >95% accuracy across all races
2. WHEN a valid horse racing PDF is provided, THE Parser SHALL extract trainer names with >95% accuracy across all races
3. WHEN a valid horse racing PDF is provided, THE Parser SHALL extract morning line odds with >95% accuracy across all races
4. WHEN a valid horse racing PDF is provided, THE Parser SHALL extract distance values with >95% accuracy across all races
5. WHEN a valid horse racing PDF is provided, THE Parser SHALL extract speed figures with >95% accuracy across all races
6. WHEN a valid horse racing PDF is provided, THE Parser SHALL extract claim prices with >95% accuracy across all races
7. WHEN a valid horse racing PDF is provided, THE Parser SHALL extract past performance data (E1, E2, speed, distance) with >90% accuracy across all races
8. THE Parser SHALL generate a Parse_Quality_Report showing per-field extraction success rates for each race

### Requirement 2: Distance Format Normalization

**User Story:** As a data analyst, I want distance values normalized to a consistent format, so that I can perform accurate distance-based comparisons.

#### Acceptance Criteria

1. WHEN the Parser extracts "6½Furlongs", THE Normalizer SHALL convert it to 6.5 furlongs
2. WHEN the Parser extracts "6Furlongs", THE Normalizer SHALL convert it to 6.0 furlongs
3. WHEN the Parser extracts "1m70yds", THE Normalizer SHALL convert it to 8.318 furlongs (1 mile = 8 furlongs, 70 yards = 0.318 furlongs)
4. WHEN the Parser extracts "1m", THE Normalizer SHALL convert it to 8.0 furlongs
5. WHEN the Parser extracts distance with mojibake characters (e.g., "6┬╜ft"), THE Normalizer SHALL extract the numeric portion and convert to furlongs
6. THE Normalizer SHALL store normalized distance values as floating-point numbers with 2 decimal places
7. WHEN the Normalizer cannot parse a distance value, THE Normalizer SHALL log the raw text and set distance to 0.0

### Requirement 3: Jockey Name Parsing

**User Story:** As a data analyst, I want jockey names parsed consistently across all races, so that I can track jockey performance accurately.

#### Acceptance Criteria

1. WHEN the Parser encounters "LASTNAME FIRSTNAME (stats)", THE Parser SHALL extract "Firstname Lastname" in title case
2. WHEN the Parser encounters "LASTNAME, JR. FIRSTNAME (stats)", THE Parser SHALL extract "Firstname Lastname" and exclude suffix "JR."
3. WHEN the Parser encounters "LASTNAME, SR. FIRSTNAME (stats)", THE Parser SHALL extract "Firstname Lastname" and exclude suffix "SR."
4. WHEN the Parser encounters jockey stats format "(starts wins-places-shows win%)", THE Parser SHALL extract win percentage as a decimal value
5. WHEN the Parser encounters a line with multiple uppercase words followed by stats, THE Parser SHALL use line-by-line matching to avoid catastrophic backtracking
6. WHEN the Parser cannot extract a jockey name, THE Parser SHALL set jockey_name to empty string and jockey_win_pct to 0.0
7. THE Parser SHALL skip lines containing keywords "Trnr:", "Life:", "Sire", "Dam", "JKYw", "PRX", "Trf" when searching for jockey names

### Requirement 4: Trainer Name Parsing

**User Story:** As a data analyst, I want trainer names parsed consistently, so that I can track trainer performance accurately.

#### Acceptance Criteria

1. WHEN the Parser encounters "Trnr: LASTNAME FIRSTNAME (stats)", THE Parser SHALL extract "Lastname Firstname" in title case
2. WHEN the Parser encounters "Trnr: LASTNAME, JR. FIRSTNAME (stats)", THE Parser SHALL extract "Lastname, Jr. Firstname" preserving the suffix
3. WHEN the Parser encounters trainer stats format "(starts wins-places-shows win%)", THE Parser SHALL extract win percentage as a decimal value
4. WHEN the Parser cannot extract a trainer name, THE Parser SHALL set trainer_name to empty string and trainer_win_pct to 0.0

### Requirement 5: Past Performance Data Extraction

**User Story:** As a data analyst, I want past performance lines parsed accurately, so that I can analyze historical race data.

#### Acceptance Criteria

1. WHEN the Parser encounters a past performance line with format "DDMmmYY dist E1 E2/ CR +/- +/- SPD", THE Parser SHALL extract E1, E2, and speed figure
2. WHEN the Parser encounters spaced E1/E2 format "82 78/ 80 +1 +5 90", THE Parser SHALL extract E1=82, E2=78, SPD=90
3. WHEN the Parser encounters jammed E1/E2 format "95104/ 80 +1 +5 90", THE Parser SHALL extract E1=104, SPD=90 (recognizing 95 as class rating)
4. WHEN the Parser encounters distance in past performance line, THE Parser SHALL extract and normalize distance to furlongs
5. WHEN the Parser encounters mile races "1m" or mojibake "├á1╦åfm", THE Parser SHALL extract leading digit and convert to furlongs
6. THE Parser SHALL store each past performance as a dictionary with keys: dist, e1, e2, speed, finish

### Requirement 6: Field Validation

**User Story:** As a data analyst, I want extracted data validated against expected patterns, so that I can identify parsing errors immediately.

#### Acceptance Criteria

1. WHEN the Validator receives a Horse_Record, THE Validator SHALL verify jockey_win_pct is between 0.0 and 1.0
2. WHEN the Validator receives a Horse_Record, THE Validator SHALL verify trainer_win_pct is between 0.0 and 1.0
3. WHEN the Validator receives a Horse_Record, THE Validator SHALL verify odds is a positive number
4. WHEN the Validator receives a Horse_Record, THE Validator SHALL verify distance is between 3.0 and 12.0 furlongs for typical races
5. WHEN the Validator receives a Horse_Record, THE Validator SHALL verify speed figures are between 0 and 150
6. WHEN the Validator receives a Horse_Record, THE Validator SHALL verify claim_price is 0 or >= 2500
7. WHEN the Validator detects an invalid field value, THE Validator SHALL log the field name, invalid value, and expected range
8. THE Validator SHALL generate a validation report showing all failed validations per race

### Requirement 7: Diagnostic Error Reporting

**User Story:** As a developer, I want detailed diagnostics when parsing fails, so that I can quickly identify and fix parsing issues.

#### Acceptance Criteria

1. WHEN the Parser fails to extract a field, THE Diagnostic_Reporter SHALL log the field name, horse name, and race number
2. WHEN the Parser fails to extract a field, THE Diagnostic_Reporter SHALL log the raw text block where extraction was attempted
3. WHEN the Parser fails to extract a field, THE Diagnostic_Reporter SHALL log the extraction pattern that was used
4. THE Diagnostic_Reporter SHALL generate a per-race field extraction report showing success/failure counts
5. THE Diagnostic_Reporter SHALL generate a per-field extraction report showing which races had low success rates
6. WHEN a race has <80% success rate for any weighted field, THE Diagnostic_Reporter SHALL flag it as a warning
7. THE Diagnostic_Reporter SHALL provide sample raw text for failed extractions to aid debugging

### Requirement 8: Format Variation Handling

**User Story:** As a data analyst, I want the parser to handle format variations gracefully, so that it works across different PDF sources.

#### Acceptance Criteria

1. WHEN the Parser encounters mojibake characters in distance fields, THE Parser SHALL extract numeric portions using leading digit patterns
2. WHEN the Parser encounters spacing variations in stats format, THE Parser SHALL use flexible whitespace matching
3. WHEN the Parser encounters punctuation variations (comma, period, apostrophe), THE Parser SHALL normalize names by removing punctuation
4. WHEN the Parser encounters different date formats in past performances, THE Parser SHALL recognize format "DDMmmYY" (e.g., "15Apr24")
5. WHEN the Parser encounters missing fields, THE Parser SHALL set default values (0.0 for numeric, empty string for text)
6. THE Parser SHALL track which fields were successfully parsed vs defaulted using a parsed flag (e.g., odds_parsed)

### Requirement 9: Regression Testing Framework

**User Story:** As a developer, I want a regression test suite, so that I can ensure parser changes don't break existing functionality.

#### Acceptance Criteria

1. THE Regression_Test_Suite SHALL include test cases for all known PDF format variations
2. THE Regression_Test_Suite SHALL include test cases for all known mojibake patterns
3. THE Regression_Test_Suite SHALL include test cases for edge cases (missing fields, malformed data)
4. WHEN the Regression_Test_Suite runs, THE Regression_Test_Suite SHALL compare current extraction results against baseline results
5. WHEN the Regression_Test_Suite detects a regression, THE Regression_Test_Suite SHALL report which fields regressed and by how much
6. THE Regression_Test_Suite SHALL store baseline extraction results for at least 3 different PDF files
7. THE Regression_Test_Suite SHALL be executable via a single command (e.g., "pytest tests/test_parser_regression.py")

### Requirement 10: Parser Configuration and Extensibility

**User Story:** As a developer, I want the parser to be easily configurable and extensible, so that I can add new fields or adjust patterns without rewriting core logic.

#### Acceptance Criteria

1. THE Parser SHALL define extraction patterns in a configuration structure separate from parsing logic
2. THE Parser SHALL define validation rules in a configuration structure separate from validation logic
3. WHEN a developer adds a new field, THE Parser SHALL allow adding the field by defining a new extraction pattern and validation rule
4. THE Parser SHALL support multiple extraction patterns per field with fallback priority
5. THE Parser SHALL log which extraction pattern successfully matched for each field
6. WHERE a field has multiple format variants, THE Parser SHALL attempt patterns in priority order until one succeeds

### Requirement 11: Parse Configuration Files

**User Story:** As a developer, I want to define extraction patterns in a configuration file, so that I can adjust parsing rules without modifying code.

#### Acceptance Criteria

1. WHEN a valid configuration file is provided, THE Parser SHALL load extraction patterns from the configuration file
2. WHEN an invalid configuration file is provided, THE Parser SHALL return a descriptive error indicating which pattern is malformed
3. THE Configuration_Formatter SHALL format extraction pattern configurations into a human-readable configuration file
4. FOR ALL valid extraction pattern configurations, parsing the configuration file then formatting it then parsing it again SHALL produce an equivalent configuration object (round-trip property)

### Requirement 12: Performance and Efficiency

**User Story:** As a data analyst, I want the parser to process PDFs efficiently, so that I can analyze large batches of race data quickly.

#### Acceptance Criteria

1. WHEN the Parser processes a 10-page PDF, THE Parser SHALL complete extraction in less than 5 seconds
2. THE Parser SHALL use O(n) text extraction (list + join) instead of O(n²) string concatenation
3. THE Parser SHALL use compiled regular expressions for repeated pattern matching
4. WHEN the Parser processes multiple PDFs, THE Parser SHALL reuse compiled patterns across documents
5. THE Parser SHALL avoid catastrophic backtracking by using line-by-line matching for complex patterns

## Notes

### Parser and Serializer Requirements

This specification includes parser requirements (Requirement 11) with explicit round-trip testing requirements. The configuration file parser is essential for maintainability and extensibility of the extraction system.

### Property-Based Testing Opportunities

Several requirements are well-suited for property-based testing:

- **Requirement 2 (Distance Normalization)**: Test that all distance format variants normalize to valid furlong values (3.0-12.0 range)
- **Requirement 6 (Field Validation)**: Test that validation rules correctly identify invalid values across wide input ranges
- **Requirement 11 (Configuration Round-Trip)**: Test that parse → format → parse preserves configuration semantics

### Integration Testing Requirements

Some requirements require integration testing with representative examples rather than property-based testing:

- **Requirement 1 (Field Extraction Accuracy)**: Test with 3-5 representative PDF files covering format variations
- **Requirement 7 (Diagnostic Reporting)**: Test with known failure cases to verify diagnostic output
- **Requirement 9 (Regression Testing)**: Test with baseline PDF files to detect regressions

### Current State Analysis

Based on analysis of parx_engine_v4_kiro.py:

**Strengths:**
- Comprehensive field extraction logic
- O(n) text extraction (Fix 5 already implemented)
- Line-by-line jockey matching to avoid backtracking
- Parse quality diagnostic method (diagnose_parse_quality)

**Gaps:**
- No systematic validation framework (Requirement 6)
- No regression test suite (Requirement 9)
- Distance normalization incomplete (6½ → 6.0 issue)
- Jockey parsing still has low success rates in some races (43% in Race 8)
- No configuration-based pattern management (Requirement 10, 11)
- Validation rules hardcoded in parsing logic

**Priority Implementation Order:**
1. Field validation framework (Requirement 6) - enables detection of current issues
2. Distance normalization fixes (Requirement 2) - addresses known bug
3. Jockey parsing improvements (Requirement 3) - addresses 43% failure rate
4. Regression test suite (Requirement 9) - prevents future regressions
5. Configuration-based patterns (Requirement 10, 11) - enables maintainability
