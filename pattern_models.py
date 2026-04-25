"""
Pattern configuration data models for the Robust PDF Parsing System.

This module defines the data structures for extraction patterns and configuration.
It provides serialization/deserialization capabilities for pattern configurations.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import json
import re


@dataclass
class FieldPattern:
    """
    Defines extraction patterns for a single field.
    
    Attributes:
        name: Field identifier (e.g., "jockey_name")
        patterns: List of regex patterns in priority order (attempt sequentially)
        default_value: Fallback value if all patterns fail
        pre_filter: Optional quick string check before regex (performance optimization)
        exclude_keywords: List of keywords - skip lines containing these when searching
    """
    name: str
    patterns: List[str]
    default_value: Any
    pre_filter: Optional[str] = None
    exclude_keywords: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'name': self.name,
            'patterns': self.patterns,
            'default_value': self.default_value,
            'pre_filter': self.pre_filter,
            'exclude_keywords': self.exclude_keywords
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FieldPattern':
        """Create FieldPattern from dictionary."""
        return cls(
            name=data['name'],
            patterns=data['patterns'],
            default_value=data['default_value'],
            pre_filter=data.get('pre_filter'),
            exclude_keywords=data.get('exclude_keywords', [])
        )
    
    def compile_patterns(self) -> List[re.Pattern]:
        """
        Compile all regex patterns for performance.
        
        Returns:
            List of compiled regex Pattern objects
            
        Raises:
            re.error: If any pattern is malformed
        """
        compiled = []
        for i, pattern in enumerate(self.patterns):
            try:
                compiled.append(re.compile(pattern))
            except re.error as e:
                raise re.error(f"Invalid regex pattern #{i+1} for field '{self.name}': {e}")
        return compiled


@dataclass
class PatternConfig:
    """
    Configuration for extraction patterns.
    
    Attributes:
        version: Configuration version string for tracking
        fields: Dictionary mapping field names to FieldPattern objects
    """
    version: str
    fields: Dict[str, FieldPattern] = field(default_factory=dict)
    
    def to_json(self) -> str:
        """Serialize configuration to JSON string."""
        data = {
            'version': self.version,
            'fields': {}
        }
        
        for field_name, field_pattern in self.fields.items():
            data['fields'][field_name] = field_pattern.to_dict()
        
        return json.dumps(data, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'PatternConfig':
        """
        Deserialize configuration from JSON string.
        
        Args:
            json_str: JSON string containing configuration
            
        Returns:
            PatternConfig object
            
        Raises:
            ValueError: If JSON is malformed or contains invalid patterns
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
        
        if 'version' not in data:
            raise ValueError("Configuration missing required 'version' field")
        
        if 'fields' not in data:
            raise ValueError("Configuration missing required 'fields' field")
        
        config = cls(version=data['version'])
        
        for field_name, field_data in data['fields'].items():
            try:
                # Ensure name matches key
                field_data['name'] = field_name
                field_pattern = FieldPattern.from_dict(field_data)
                
                # Validate patterns by attempting to compile them
                field_pattern.compile_patterns()
                
                config.fields[field_name] = field_pattern
            except Exception as e:
                raise ValueError(f"Invalid pattern for field '{field_name}': {e}")
        
        return config
    
    def add_field(self, field_pattern: FieldPattern) -> None:
        """Add a field pattern to the configuration."""
        self.fields[field_pattern.name] = field_pattern
    
    def get_field(self, name: str) -> Optional[FieldPattern]:
        """Get field pattern by name."""
        return self.fields.get(name)
    
    def compile_all_patterns(self) -> Dict[str, List[re.Pattern]]:
        """
        Compile all regex patterns for all fields.
        
        Returns:
            Dictionary mapping field names to lists of compiled patterns
        """
        compiled = {}
        for field_name, field_pattern in self.fields.items():
            compiled[field_name] = field_pattern.compile_patterns()
        return compiled
