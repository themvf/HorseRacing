"""
Validation data models and configuration for the Robust PDF Parsing System.

This module defines the data structures for validation rules, results, and configuration.
It provides serialization/deserialization capabilities for validation configurations.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Callable, Optional
import json


@dataclass
class ValidationRule:
    """
    Defines a validation rule for a field.
    
    Attributes:
        field: Field identifier (e.g., "jockey_win_pct")
        rule_type: Type of validation - "range", "enum", "pattern", "custom"
        constraint: The constraint to check:
            - For "range": tuple of (min, max)
            - For "enum": set of valid values
            - For "pattern": regex pattern string
            - For "custom": callable that takes value and returns bool
        severity: "error" or "warning"
        message: Human-readable description of the rule
    """
    field: str
    rule_type: str  # "range", "enum", "pattern", "custom"
    constraint: Any  # Range tuple, enum set, regex pattern, or callable
    severity: str   # "error", "warning"
    message: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'field': self.field,
            'rule_type': self.rule_type,
            'severity': self.severity,
            'message': self.message
        }
        
        # Handle constraint serialization based on type
        if self.rule_type == "range":
            result['constraint'] = list(self.constraint)
        elif self.rule_type == "enum":
            result['constraint'] = list(self.constraint)
        elif self.rule_type == "pattern":
            result['constraint'] = self.constraint
        elif self.rule_type == "custom":
            # Custom callables cannot be serialized - store as string identifier
            result['constraint'] = getattr(self.constraint, '__name__', str(self.constraint))
        else:
            result['constraint'] = self.constraint
            
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], custom_validators: Optional[Dict[str, Callable]] = None) -> 'ValidationRule':
        """
        Create ValidationRule from dictionary.
        
        Args:
            data: Dictionary with rule data
            custom_validators: Optional dict mapping validator names to callable functions
        """
        constraint = data['constraint']
        rule_type = data['rule_type']
        
        # Convert constraint back to appropriate type
        if rule_type == "range":
            constraint = tuple(constraint)
        elif rule_type == "enum":
            constraint = set(constraint)
        elif rule_type == "custom":
            if custom_validators and constraint in custom_validators:
                constraint = custom_validators[constraint]
            else:
                raise ValueError(f"Custom validator '{constraint}' not found in custom_validators dict")
        
        return cls(
            field=data['field'],
            rule_type=rule_type,
            constraint=constraint,
            severity=data['severity'],
            message=data['message']
        )


@dataclass
class ValidationResult:
    """
    Result of validating a single field value.
    
    Attributes:
        field: Field name that was validated
        value: The value that was validated
        is_valid: Whether the value passed validation
        rule: The ValidationRule that was applied
        message: Human-readable validation message
    """
    field: str
    value: Any
    is_valid: bool
    rule: ValidationRule
    message: str
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        status = "✓ VALID" if self.is_valid else "✗ INVALID"
        return f"{status} | {self.field}={self.value} | {self.message}"


@dataclass
class ValidationConfig:
    """
    Configuration for validation rules.
    
    Attributes:
        version: Configuration version string for tracking
        rules: Dictionary mapping field names to lists of ValidationRule objects
    """
    version: str
    rules: Dict[str, List[ValidationRule]] = field(default_factory=dict)
    
    def to_json(self) -> str:
        """Serialize configuration to JSON string."""
        data = {
            'version': self.version,
            'rules': {}
        }
        
        for field_name, rule_list in self.rules.items():
            data['rules'][field_name] = [rule.to_dict() for rule in rule_list]
        
        return json.dumps(data, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str, custom_validators: Optional[Dict[str, Callable]] = None) -> 'ValidationConfig':
        """
        Deserialize configuration from JSON string.
        
        Args:
            json_str: JSON string containing configuration
            custom_validators: Optional dict mapping validator names to callable functions
            
        Returns:
            ValidationConfig object
            
        Raises:
            ValueError: If JSON is malformed or contains invalid rules
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
        
        if 'version' not in data:
            raise ValueError("Configuration missing required 'version' field")
        
        if 'rules' not in data:
            raise ValueError("Configuration missing required 'rules' field")
        
        config = cls(version=data['version'])
        
        for field_name, rule_list in data['rules'].items():
            if not isinstance(rule_list, list):
                raise ValueError(f"Rules for field '{field_name}' must be a list")
            
            config.rules[field_name] = []
            for rule_data in rule_list:
                try:
                    rule = ValidationRule.from_dict(rule_data, custom_validators)
                    config.rules[field_name].append(rule)
                except Exception as e:
                    raise ValueError(f"Invalid rule for field '{field_name}': {e}")
        
        return config
    
    def add_rule(self, rule: ValidationRule) -> None:
        """Add a validation rule to the configuration."""
        if rule.field not in self.rules:
            self.rules[rule.field] = []
        self.rules[rule.field].append(rule)
    
    def get_rules(self, field: str) -> List[ValidationRule]:
        """Get all validation rules for a specific field."""
        return self.rules.get(field, [])
