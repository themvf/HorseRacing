"""
Validator component for the Robust PDF Parsing System.

This module implements field validation logic using configurable validation rules.
It supports range checks, enum validation, pattern matching, and custom validators.
"""

import re
import logging
from typing import Any, List, Dict
from validation_models import ValidationRule, ValidationResult, ValidationConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Validator:
    """
    Validates extracted data against configured validation rules.
    
    Supports multiple rule types:
    - range: Check if value is within min/max bounds
    - enum: Check if value is in a set of valid values
    - pattern: Check if value matches a regex pattern
    - custom: Check using a custom callable function
    """
    
    def __init__(self, config: ValidationConfig):
        """
        Initialize validator with validation rule configuration.
        
        Args:
            config: ValidationConfig object containing validation rules
        """
        self.config = config
        logger.info(f"Validator initialized with config version {config.version}")
        logger.info(f"Loaded rules for {len(config.rules)} fields")
    
    def validate_field(self, field: str, value: Any) -> ValidationResult:
        """
        Validate a single field value against configured rules.
        
        Args:
            field: Field name to validate
            value: Value to validate
            
        Returns:
            ValidationResult object with validation outcome
            
        Note:
            If multiple rules exist for a field, only the first rule is applied.
            To validate against all rules, use validate_field_all_rules().
        """
        rules = self.config.get_rules(field)
        
        if not rules:
            # No rules defined for this field - consider it valid
            return ValidationResult(
                field=field,
                value=value,
                is_valid=True,
                rule=ValidationRule(
                    field=field,
                    rule_type="none",
                    constraint=None,
                    severity="info",
                    message="No validation rules defined"
                ),
                message=f"No validation rules defined for {field}"
            )
        
        # Apply first rule (for backward compatibility)
        rule = rules[0]
        return self._apply_rule(field, value, rule)
    
    def validate_field_all_rules(self, field: str, value: Any) -> List[ValidationResult]:
        """
        Validate a single field value against all configured rules.
        
        Args:
            field: Field name to validate
            value: Value to validate
            
        Returns:
            List of ValidationResult objects, one per rule
        """
        rules = self.config.get_rules(field)
        
        if not rules:
            return [ValidationResult(
                field=field,
                value=value,
                is_valid=True,
                rule=ValidationRule(
                    field=field,
                    rule_type="none",
                    constraint=None,
                    severity="info",
                    message="No validation rules defined"
                ),
                message=f"No validation rules defined for {field}"
            )]
        
        results = []
        for rule in rules:
            result = self._apply_rule(field, value, rule)
            results.append(result)
        
        return results
    
    def _apply_rule(self, field: str, value: Any, rule: ValidationRule) -> ValidationResult:
        """
        Apply a single validation rule to a value.
        
        Args:
            field: Field name
            value: Value to validate
            rule: ValidationRule to apply
            
        Returns:
            ValidationResult object
        """
        is_valid = False
        message = rule.message
        
        try:
            if rule.rule_type == "range":
                min_val, max_val = rule.constraint
                is_valid = min_val <= value <= max_val
                if not is_valid:
                    message = f"{rule.message} (got {value}, expected [{min_val}, {max_val}])"
            
            elif rule.rule_type == "enum":
                is_valid = value in rule.constraint
                if not is_valid:
                    message = f"{rule.message} (got {value}, expected one of {rule.constraint})"
            
            elif rule.rule_type == "pattern":
                is_valid = bool(re.match(rule.constraint, str(value)))
                if not is_valid:
                    message = f"{rule.message} (got '{value}', expected pattern '{rule.constraint}')"
            
            elif rule.rule_type == "custom":
                is_valid = rule.constraint(value)
                if not is_valid:
                    message = f"{rule.message} (got {value})"
            
            else:
                logger.warning(f"Unknown rule type '{rule.rule_type}' for field '{field}'")
                message = f"Unknown rule type: {rule.rule_type}"
        
        except Exception as e:
            logger.error(f"Error applying rule to {field}={value}: {e}")
            is_valid = False
            message = f"Validation error: {e}"
        
        # Log validation failures
        if not is_valid:
            log_fn = logger.error if rule.severity == "error" else logger.warning
            log_fn(f"Validation {rule.severity}: {field}={value} - {message}")
        
        return ValidationResult(
            field=field,
            value=value,
            is_valid=is_valid,
            rule=rule,
            message=message
        )
    
    def validate_horse_record(self, record) -> List[ValidationResult]:
        """
        Validate all fields in a horse record.
        
        Args:
            record: Horse object with fields to validate
            
        Returns:
            List of ValidationResult objects for all validated fields
        """
        results = []
        
        # Define fields to validate with their attribute names
        fields_to_validate = [
            'jockey_win_pct',
            'trainer_win_pct',
            'odds',
            'best_speed',
            'claim_price',
        ]
        
        for field in fields_to_validate:
            if hasattr(record, field):
                value = getattr(record, field)
                # Only validate if field was successfully parsed (check parsed flag if available)
                parsed_flag = f"{field}_parsed"
                if hasattr(record, parsed_flag):
                    if not getattr(record, parsed_flag):
                        # Skip validation for unparsed fields
                        continue
                
                field_results = self.validate_field_all_rules(field, value)
                results.extend(field_results)
        
        return results
    
    def validate_race_record(self, horses: List) -> Dict[str, List[ValidationResult]]:
        """
        Validate all horses in a race.
        
        Args:
            horses: List of Horse objects
            
        Returns:
            Dictionary mapping horse name to list of ValidationResult objects
        """
        race_results = {}
        
        for horse in horses:
            horse_name = horse.name if hasattr(horse, 'name') else str(horse)
            results = self.validate_horse_record(horse)
            if results:  # Only include horses with validation results
                race_results[horse_name] = results
        
        return race_results
    
    def generate_validation_report(self, race_results: Dict[str, List[ValidationResult]]) -> str:
        """
        Generate a human-readable validation report for a race.
        
        Args:
            race_results: Dictionary mapping horse names to validation results
            
        Returns:
            Formatted string report
        """
        if not race_results:
            return "No validation results to report."
        
        lines = []
        lines.append("=" * 70)
        lines.append("  VALIDATION REPORT")
        lines.append("=" * 70)
        
        total_validations = sum(len(results) for results in race_results.values())
        total_failures = sum(
            1 for results in race_results.values()
            for result in results
            if not result.is_valid
        )
        
        lines.append(f"  Total validations: {total_validations}")
        lines.append(f"  Failures: {total_failures}")
        lines.append(f"  Success rate: {(total_validations - total_failures) / total_validations * 100:.1f}%")
        lines.append("-" * 70)
        
        # Group failures by field
        field_failures = {}
        for horse_name, results in race_results.items():
            for result in results:
                if not result.is_valid:
                    if result.field not in field_failures:
                        field_failures[result.field] = []
                    field_failures[result.field].append((horse_name, result))
        
        if field_failures:
            lines.append("\n  VALIDATION FAILURES BY FIELD:")
            for field, failures in sorted(field_failures.items()):
                lines.append(f"\n  {field}: {len(failures)} failure(s)")
                for horse_name, result in failures[:3]:  # Show first 3 examples
                    lines.append(f"    - {horse_name}: {result.message}")
                if len(failures) > 3:
                    lines.append(f"    ... and {len(failures) - 3} more")
        else:
            lines.append("\n  ✓ All validations passed!")
        
        lines.append("\n" + "=" * 70)
        return "\n".join(lines)
