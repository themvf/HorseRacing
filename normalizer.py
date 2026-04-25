"""
Normalizer component for the Robust PDF Parsing System.

This module implements field normalization logic to convert raw extracted values
to canonical formats (e.g., distance strings to furlongs, names to title case).
"""

import re
import logging
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Normalizer:
    """
    Normalizes extracted field values to canonical formats.
    
    Handles:
    - Distance normalization (various formats → furlongs float)
    - Name normalization (jockey/trainer names → title case)
    - Percentage normalization (string → decimal)
    - Odds normalization (fraction string → decimal)
    """
    
    # Unicode fraction character mappings
    FRACTION_MAP = {
        '½': 0.5,
        '¼': 0.25,
        '¾': 0.75,
        '⅓': 0.333,
        '⅔': 0.667,
        '⅛': 0.125,
        '⅜': 0.375,
        '⅝': 0.625,
        '⅞': 0.875,
    }
    
    # Mojibake patterns that indicate fractional distances
    MOJIBAKE_PATTERNS = {
        '┬╜': 0.5,  # Common corruption of ½
        '┬╝': 0.25, # Common corruption of ¼
        '┬╛': 0.75, # Common corruption of ¾
    }
    
    def normalize_distance(self, raw: str) -> float:
        """
        Convert distance string to furlongs (float, 2 decimal places).
        
        Handles formats:
        - "6½Furlongs" → 6.5
        - "6Furlongs" → 6.0
        - "1m70yds" → 8.318 (1 mile = 8 furlongs, 70 yards = 0.318 furlongs)
        - "1m" → 8.0
        - "6┬╜ft" (mojibake) → 6.5
        - "6.5f" → 6.5
        
        Args:
            raw: Raw distance string from PDF
            
        Returns:
            Distance in furlongs (float with 2 decimal places), or 0.0 if unparseable
        """
        if not raw:
            return 0.0
        
        raw = raw.strip()
        
        try:
            # Pattern 1: Miles + yards (e.g., "1m70yds")
            m = re.search(r'(\d+)m(\d+)yds?', raw, re.IGNORECASE)
            if m:
                miles = int(m.group(1))
                yards = int(m.group(2))
                furlongs = miles * 8 + yards / 220.0
                return round(furlongs, 2)
            
            # Pattern 2: Miles only (e.g., "1m")
            m = re.search(r'(\d+)m\b', raw, re.IGNORECASE)
            if m:
                miles = int(m.group(1))
                return float(miles * 8)

            # Pattern 2b: "Mile" text format — "1Mile", "1ˆMile" (1 1/16), "1„Mile" (1 1/8)
            m = re.search(r'(\d+)\S{0,4}Miles?', raw, re.IGNORECASE)
            if m:
                whole = int(m.group(1))
                segment = raw[:m.end()]
                frac = 0.0
                if 'ˆ' in segment:   # ˆ = 1/16 mile
                    frac = 1/16
                elif '„' in segment:  # „ = 1/8 mile
                    frac = 1/8
                else:
                    for frac_char, frac_val in self.FRACTION_MAP.items():
                        if frac_char in segment:
                            frac = frac_val
                            break
                return round(whole * 8 + frac * 8, 2)

            # Pattern 3: Furlongs with Unicode fraction (e.g., "6½Furlongs")
            for frac_char, frac_val in self.FRACTION_MAP.items():
                if frac_char in raw:
                    # Extract leading digit
                    m = re.search(r'(\d+)', raw)
                    if m:
                        whole = int(m.group(1))
                        return round(whole + frac_val, 2)
            
            # Pattern 4: Furlongs with mojibake (e.g., "6┬╜ft")
            for mojibake, frac_val in self.MOJIBAKE_PATTERNS.items():
                if mojibake in raw:
                    # Extract leading digit
                    m = re.search(r'(\d+)', raw)
                    if m:
                        whole = int(m.group(1))
                        return round(whole + frac_val, 2)
            
            # Pattern 5: Decimal furlongs (e.g., "6.5Furlongs" or "6.5f")
            m = re.search(r'(\d+(?:\.\d+)?)\S{0,6}(?:Furlongs?|f\b)', raw, re.IGNORECASE)
            if m:
                return round(float(m.group(1)), 2)
            
            # Pattern 6: Plain number followed by 'f' (e.g., "6f")
            m = re.search(r'(\d+(?:\.\d+)?)f\b', raw, re.IGNORECASE)
            if m:
                return round(float(m.group(1)), 2)
            
            # Pattern 7: Just a number (assume furlongs)
            m = re.search(r'(\d+(?:\.\d+)?)', raw)
            if m:
                val = float(m.group(1))
                # Sanity check: typical race distances are 3-12 furlongs
                if 3.0 <= val <= 12.0:
                    return round(val, 2)
            
            # Unable to parse
            logger.warning(f"Unable to parse distance: '{raw}'")
            return 0.0
            
        except Exception as e:
            logger.error(f"Error normalizing distance '{raw}': {e}")
            return 0.0
    
    def normalize_name(self, raw: str, name_type: str) -> str:
        """
        Convert name to title case, handle suffixes.
        
        Args:
            raw: Raw name string (typically all caps)
            name_type: "jockey" or "trainer"
            
        Returns:
            Normalized name in title case
            
        For jockey names:
            "LASTNAME FIRSTNAME" → "Firstname Lastname"
            "LASTNAME, JR. FIRSTNAME" → "Firstname Lastname" (suffix removed)
            
        For trainer names:
            "LASTNAME FIRSTNAME" → "Lastname Firstname"
            "LASTNAME, JR. FIRSTNAME" → "Lastname, Jr. Firstname" (suffix preserved)
        """
        if not raw:
            return ""
        
        raw = raw.strip()
        
        # Remove punctuation artifacts, split into words
        words = [w.strip(',.') for w in raw.split() if w.strip(',.')]
        
        # Filter out suffixes
        suffixes = {'JR', 'SR', 'II', 'III', 'IV', 'JR.', 'SR.'}
        
        if name_type == "jockey":
            # Remove suffixes for jockeys
            name_words = [w for w in words if w.upper() not in suffixes]
            
            if len(name_words) >= 2:
                # Convention: last word in all-caps block = last name, rest = first name
                last = name_words[0].capitalize()
                first = ' '.join(w.capitalize() for w in name_words[1:])
                return f"{first} {last}"
            else:
                return raw.title()
        
        elif name_type == "trainer":
            # Preserve suffixes for trainers
            # Check if there's a comma (indicates suffix)
            if ',' in raw:
                # Format: "LASTNAME, SUFFIX FIRSTNAME"
                parts = raw.split(',')
                if len(parts) >= 2:
                    last = parts[0].strip().capitalize()
                    rest = parts[1].strip().split()
                    # Check if first word after comma is a suffix
                    if rest and rest[0].upper() in suffixes:
                        suffix = rest[0].capitalize() + '.'
                        first = ' '.join(w.capitalize() for w in rest[1:])
                        return f"{last}, {suffix} {first}"
            
            # Standard format: "LASTNAME FIRSTNAME"
            if len(words) >= 2:
                last = words[0].capitalize()
                first = ' '.join(w.capitalize() for w in words[1:])
                return f"{last} {first}"
            else:
                return raw.title()
        
        else:
            # Unknown name type - just title case
            return raw.title()
    
    def normalize_percentage(self, raw: str) -> float:
        """
        Convert percentage string to decimal (0.0-1.0).
        
        Args:
            raw: Percentage string (e.g., "25%")
            
        Returns:
            Decimal value (e.g., 0.25)
        """
        if not raw:
            return 0.0
        
        try:
            # Remove % sign and convert
            raw = raw.strip().rstrip('%')
            return float(raw) / 100.0
        except Exception as e:
            logger.error(f"Error normalizing percentage '{raw}': {e}")
            return 0.0
    
    def normalize_odds(self, raw: str) -> float:
        """
        Convert odds string to decimal.
        
        Args:
            raw: Odds string (e.g., "5/2")
            
        Returns:
            Decimal odds (e.g., 2.5)
        """
        if not raw:
            return 10.0  # Default fallback
        
        try:
            if '/' in raw:
                num, den = map(int, raw.split('/'))
                if den == 0:
                    return 10.0
                return num / den
            else:
                return float(raw)
        except Exception as e:
            logger.error(f"Error normalizing odds '{raw}': {e}")
            return 10.0
    
    def normalize_horse_record(self, record) -> None:
        """
        Apply all normalization rules to a horse record in-place.
        
        Args:
            record: Horse object to normalize
        """
        # Normalize jockey name if present
        if hasattr(record, 'jockey_name') and record.jockey_name:
            record.jockey_name = self.normalize_name(record.jockey_name, 'jockey')
        
        # Normalize trainer name if present
        if hasattr(record, 'trainer_name') and record.trainer_name:
            record.trainer_name = self.normalize_name(record.trainer_name, 'trainer')
        
        # Note: Distance normalization happens at race level, not horse level
        # Odds and percentages are already normalized during parsing
