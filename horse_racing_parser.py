"""PDF extraction and race/horse parsing — mixin for HorseRacingEngine."""

import re
import logging
import pdfplumber

from horse_racing_horse import Horse

# BRIS track-code → display name.  Unknown codes fall back to "<CODE> Racing".
TRACK_NAMES = {
    'prx':  'Parx Racing',
    'lrl':  'Laurel Park',
    'pha':  'Philadelphia Park',
    'pim':  'Pimlico',
    'del':  'Delaware Park',
    'mth':  'Monmouth Park',
    'aqu':  'Aqueduct',
    'bel':  'Belmont Park',
    'sar':  'Saratoga',
    'cd':   'Churchill Downs',
    'kee':  'Keeneland',
    'op':   'Oaklawn Park',
    'tam':  'Tampa Bay Downs',
    'gp':   'Gulfstream Park',
    'sa':   'Santa Anita',
    'dmr':  'Del Mar',
    'cdx':  'Churchill Downs',
    'pen':  'Penn National',
    'pid':  'Pimlico',
    'mnr':  'Mountaineer',
    'tdn':  'Thistledown',
    'ind':  'Indiana Grand',
    'hou':  'Sam Houston Race Park',
    'cby':  'Canterbury Park',
    'tup':  'Turf Paradise',
    'wrd':  'Woodbine',
    'fp':   'Fairmount Park',
}


class ParserMixin:
    """
    Provides PDF text extraction and all race/horse parsing methods.
    Expects the following instance attributes (set by engine __init__):
        self.pattern_config   — PatternConfig | None
        self.compiled_patterns — dict
        self.normalizer        — Normalizer | None
        self.validator         — Validator | None
        self.reporter          — DiagnosticReporter | None
        self.all_races         — dict
        self.race_info         — dict
    """

    def _extract_field_with_patterns(self, field_name: str, text: str, context: str = "") -> tuple:
        """
        Extract a field value using pattern priority logic from configuration.

        Returns:
            Tuple of (match_or_default, pattern_index). pattern_index is -1 on no match.
        """
        if not self.pattern_config or field_name not in self.compiled_patterns:
            return (None, -1)

        field_pattern = self.pattern_config.get_field(field_name)
        compiled_patterns = self.compiled_patterns[field_name]

        # Apply pre-filter optimization if specified
        if field_pattern.pre_filter and field_pattern.pre_filter not in text:
            return (field_pattern.default_value, -1)

        for pattern_idx, compiled_pattern in enumerate(compiled_patterns):
            if field_pattern.exclude_keywords:
                for line in text.split('\n'):
                    line_stripped = line.strip()
                    if any(kw in line_stripped for kw in field_pattern.exclude_keywords):
                        continue
                    match = compiled_pattern.search(line_stripped)
                    if match:
                        logging.info(f"[Pattern Match] {field_name} (pattern #{pattern_idx+1}){' for ' + context if context else ''}")
                        return (match, pattern_idx)
            else:
                match = compiled_pattern.search(text)
                if match:
                    logging.info(f"[Pattern Match] {field_name} (pattern #{pattern_idx+1}){' for ' + context if context else ''}")
                    return (match, pattern_idx)

        return (field_pattern.default_value, -1)

    @staticmethod
    def _normalize_name(name: str) -> str:
        """
        Normalize a horse name for fuzzy matching.
        Lowercases and removes spaces and common punctuation so that
        'Downtown Chalybrown' == 'Downtownchalybrown'.
        """
        return re.sub(r"[\s\'\-\.\,]", "", name).lower()

    def extract_text_from_pdf(self, pdf_path):
        """Extract raw text from PDF."""
        stem = re.match(r'([a-z]+)', str(pdf_path).split('\\')[-1].split('/')[-1].lower())
        code = stem.group(1) if stem else ''
        self.track_name = TRACK_NAMES.get(code, f"{code.upper()} Racing" if code else "Racing")
        print(f"[*] Reading PDF: {pdf_path}...")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                print(f"[*] Total pages: {total_pages}")

                # Fix 5: collect into a list and join once — O(n) instead of the
                # O(n²) string concatenation that += produces in a loop.
                pages = []
                for i, page in enumerate(pdf.pages):
                    print(f"[*] Reading page {i+1}/{total_pages}...", end='\r')
                    text = page.extract_text()
                    if text:
                        pages.append(f"\n--- PAGE {i+1} ---\n{text}\n")

                full_text = "".join(pages)
                print(f"\n[*] Extracted {len(full_text)} characters")
            return full_text if full_text.strip() else None
        except Exception as e:
            print(f"[!] Critical error reading PDF: {e}")
            return None

    def parse_races(self, text):
        """Parse races from extracted text."""
        # Churchill/Ultimate PP format: initial race pages put the race
        # number at the end of the title line, then wagering options below.
        # Continuation pages keep "Race N E1 E2 / Late SPD" on one line and
        # are intentionally excluded. Check this first because later summary
        # sections can contain older-looking "Race N\n# Speed" snippets.
        race_markers = list(re.finditer(
            r"^Ultimate PP's[^\n]*Race\s+(\d+)\s*$\n\s*(?:Daily Double|Exacta|Race Daily Double)",
            text,
            re.IGNORECASE | re.MULTILINE,
        ))

        # Parx format: "Race N\n# Speed"
        if not race_markers:
            race_markers = list(re.finditer(r'Race\s+(\d+)\s*\n#\s+Speed', text))

        if not race_markers:
            # LRL/BRIS format: "Race N" at end of track-header line, followed by
            # bet-type line (EXACTA / TRIFECTA / DAILY DOUBLE).
            # Page continuation headers look like "Race N E1 E2 / Late SPD" (same
            # line) and do NOT match this pattern, so they're safely excluded.
            race_markers = list(re.finditer(r'Race\s+(\d+)\s*\nEXACTA', text, re.IGNORECASE))

        if not race_markers:
            print("[!] No race markers found — unrecognized PDF format.")
            return

        for idx, match in enumerate(race_markers):
            race_num = match.group(1)
            start_pos = match.start()
            end_pos = race_markers[idx + 1].start() if idx + 1 < len(race_markers) else len(text)
            race_content = text[start_pos:end_pos]

            print(f"[*] Processing Race {race_num} ({len(race_content)} chars)")

            self._parse_race_info(race_num, race_content)

            horses = self._parse_horses(race_content)
            if horses:
                self.all_races[race_num] = horses
                print(f"[+] Race {race_num}: {len(horses)} horses parsed")
            else:
                print(f"[!] No horses found in Race {race_num}")

        if self.reporter and self.all_races:
            flagged = self.reporter.flag_low_quality_races(self.all_races)
            if flagged:
                print(f"[!] Low parse quality in races: {', '.join(flagged)} — run --diagnose for details")

    def _parse_race_info(self, race_num, text):
        """Parse race metadata (distance, purse, conditions)."""
        info = {'race_num': race_num}

        # Distance — use Normalizer if available for full format support
        # (handles Unicode fractions like ½, mojibake, miles+yards, etc.)
        dist_f = 0.0
        dist_str = ''
        for line in text.split('\n'):
            s = line.strip()
            if 'Purse' not in s and 'Furlongs' not in s and 'Mile' not in s and 'yds' not in s:
                continue
            m = re.search(r'(\d+m\d+yds?)', s, re.IGNORECASE)
            if m:
                dist_str = m.group(1)
                if self.normalizer:
                    dist_f = self.normalizer.normalize_distance(dist_str)
                else:
                    mm = re.search(r'(\d+)m(\d+)yds?', dist_str, re.IGNORECASE)
                    dist_f = int(mm.group(1)) * 8 + int(mm.group(2)) / 220 if mm else 0.0
                if dist_f > 0:
                    break
            m = re.search(r'(\S{0,6}Furlongs?)', s, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 4)
                raw_token = s[start:m.end()].strip()
                dist_str = raw_token
                if self.normalizer:
                    dist_f = self.normalizer.normalize_distance(raw_token)
                else:
                    mm = re.search(r'(\d+(?:\.\d+)?)\S{0,6}Furlongs?', raw_token, re.IGNORECASE)
                    dist_f = float(mm.group(1)) if mm else 0.0
                if dist_f > 0:
                    break
            # Mile text format — "1Mile" (8f), "1ˆMile" (1 1/16mi = 8.5f), "1„Mile" (1 1/8mi = 9f)
            purse_pos = s.lower().find('purse')
            mile_m = re.search(r'(\d+\S{0,4}Miles?)', s, re.IGNORECASE)
            if mile_m and (purse_pos == -1 or mile_m.start() < purse_pos):
                raw_token = mile_m.group(1)
                dist_str = raw_token
                if self.normalizer:
                    dist_f = self.normalizer.normalize_distance(raw_token)
                else:
                    whole_m = re.search(r'(\d+)', raw_token)
                    whole = int(whole_m.group(1)) if whole_m else 1
                    frac = 1/16 if 'ˆ' in raw_token else 1/8 if '„' in raw_token else 0.0
                    dist_f = whole * 8 + frac * 8
                if dist_f > 0:
                    break

        if dist_f > 0:
            info['distance']   = dist_str
            info['distance_f'] = round(dist_f, 2)

        clm_match = re.search(r'Clm\s*(\d+)', text, re.IGNORECASE)
        if clm_match:
            info['claim_price'] = int(clm_match.group(1))

        purse_match = re.search(r'Purse\s*\$?([\d,]+)', text, re.IGNORECASE)
        if purse_match:
            info['purse'] = int(purse_match.group(1).replace(',', ''))

        self.race_info[race_num] = info

    def _parse_horses(self, text):
        """Parse all horses in a race."""
        horses = []
        horse_pattern = r'(\d+)\s+([A-Z][a-zA-Z\s\'\-\.]+?)\s*\(([A-Z/]+)\s*(\d+)\)'
        matches = list(re.finditer(horse_pattern, text))

        for idx, match in enumerate(matches):
            post_pos   = int(match.group(1))
            horse_name = match.group(2).strip()
            style_str  = match.group(3)
            style_num  = match.group(4)

            start_pos = match.start()
            end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            block = text[start_pos:end_pos]

            horse = self._parse_horse_block(block, horse_name, style_str, style_num)
            if horse and horse.name:
                horse.post_position = post_pos
                horses.append(horse)

        return horses

    def _parse_horse_block(self, block, name, style_str, style_num):
        """Parse a single horse's data block."""
        horse = Horse(name)

        horse.style = style_str.split()[0] if style_str else "P"

        try:
            horse.style_num = int(style_num) if style_num else 0
        except ValueError as e:
            print(f"[!] Warning: could not parse style_num '{style_num}' for {name}: {e}")
            horse.style_num = 0

        # ML Odds
        # Fix 4: set odds_parsed=True only on a successful parse so downstream
        # analysis can distinguish real market data from the 10.0 fallback.
        if self.pattern_config:
            odds_match, pattern_idx = self._extract_field_with_patterns('odds', block, name)
            if odds_match and pattern_idx >= 0:
                try:
                    num, den = map(int, odds_match.group(1).split('/'))
                    horse.odds = num / den
                    horse.odds_parsed = True
                except (ValueError, ZeroDivisionError) as e:
                    print(f"[!] Warning: could not parse odds '{odds_match.group(1)}' for {name}: {e}")
                    horse.odds = 10.0
                    horse.odds_parsed = False
            else:
                horse.odds = 10.0
                horse.odds_parsed = False
        else:
            odds_match = re.search(r'(\d+/\d+)\s+[O]', block)
            if odds_match:
                try:
                    num, den = map(int, odds_match.group(1).split('/'))
                    horse.odds = num / den
                    horse.odds_parsed = True
                except (ValueError, ZeroDivisionError) as e:
                    print(f"[!] Warning: could not parse odds '{odds_match.group(1)}' for {name}: {e}")
                    horse.odds = 10.0
                    horse.odds_parsed = False
            else:
                horse.odds = 10.0
                horse.odds_parsed = False

        # Claim price — format: $16,000 or $7500
        if self.pattern_config:
            clm_match, pattern_idx = self._extract_field_with_patterns('claim_price', block, name)
            if clm_match and pattern_idx >= 0:
                horse.claim_price = int(clm_match.group(1).replace(',', ''))
        else:
            clm_match = re.search(r'\$(\d{1,3}(?:,\d{3})+|\d{4,6})(?!\s*[kK])', block)
            if clm_match:
                horse.claim_price = int(clm_match.group(1).replace(',', ''))

        # Prime Power
        if self.pattern_config:
            pp_match, pattern_idx = self._extract_field_with_patterns('prime_power', block, name)
            if pp_match and pattern_idx >= 0:
                horse.prime_power = float(pp_match.group(1))
                horse.pp_rank = int(pp_match.group(2))
        else:
            pp_match = re.search(r'Prime Power:\s*([\d.]+)\s*\((\d+)(?:st|nd|rd|th)\)', block)
            if pp_match:
                horse.prime_power = float(pp_match.group(1))
                horse.pp_rank = int(pp_match.group(2))

        # Life stats
        if self.pattern_config:
            life_match, pattern_idx = self._extract_field_with_patterns('life_stats', block, name)
            if life_match and pattern_idx >= 0:
                horse.starts = int(life_match.group(1))
                horse.wins = int(life_match.group(2))
                horse.places = int(life_match.group(3))
                horse.shows = int(life_match.group(4))
                try:
                    horse.earnings = float(life_match.group(5).replace(',', ''))
                except ValueError as e:
                    print(f"[!] Warning: could not parse earnings '{life_match.group(5)}' for {name}: {e}")
                    horse.earnings = 0.0
        else:
            life_match = re.search(r'Life:\s*(\d+)\s+(\d+)\s*-?\s*(\d+)\s*-?\s*(\d+)\s*\$?([\d,]+)', block)
            if life_match:
                horse.starts = int(life_match.group(1))
                horse.wins = int(life_match.group(2))
                horse.places = int(life_match.group(3))
                horse.shows = int(life_match.group(4))
                try:
                    horse.earnings = float(life_match.group(5).replace(',', ''))
                except ValueError as e:
                    print(f"[!] Warning: could not parse earnings '{life_match.group(5)}' for {name}: {e}")
                    horse.earnings = 0.0

        # Best speed (Fst)
        if self.pattern_config:
            speed_match, pattern_idx = self._extract_field_with_patterns('best_speed', block, name)
            if speed_match and pattern_idx >= 0:
                horse.best_speed = int(speed_match.group(1))
        else:
            speed_match = re.search(r'Fst\((\d+)[^)]*\)', block)
            if speed_match:
                horse.best_speed = int(speed_match.group(1))

        # Class Rating
        if self.pattern_config:
            cr_match, pattern_idx = self._extract_field_with_patterns('class_rating', block, name)
            if cr_match and pattern_idx >= 0:
                horse.class_rating = int(cr_match.group(1))
        else:
            cr_match = re.search(r'(\d+)\s+Fst', block)
            if cr_match:
                horse.class_rating = int(cr_match.group(1))

        # Last race speed
        last_spd_match = re.search(r'(\d+)\s+\d+/\s*\d+\s+\d+\s+-\s*\d+', block)
        if last_spd_match:
            horse.last_speed = int(last_spd_match.group(1))

        # Trainer
        if self.pattern_config:
            trnr_match, pattern_idx = self._extract_field_with_patterns('trainer_name', block, name)
            if trnr_match and pattern_idx >= 0:
                horse.trainer_name = trnr_match.group(1).strip()
                try:
                    horse.trainer_win_pct = float(trnr_match.group(6)) / 100
                except (ValueError, IndexError) as e:
                    print(f"[!] Warning: could not parse trainer win pct for {name}: {e}")
                    horse.trainer_win_pct = 0.0
        else:
            trnr_match = re.search(
                r'Trnr:\s+([A-Za-z\s\-\'\.]+?)\s+\(([\d]+)\s+([\d]+)-([\d]+)-([\d]+)\s+(\d+)%\)', block
            )
            if not trnr_match:
                trnr_match = re.search(
                    r'Trnr:\s+([A-Za-z\s\-\'\.,]+?)\s+\(([\d]+)\s+([\d]+)-([\d]+)-([\d]+)\s+(\d+)%\)', block
                )
            if trnr_match:
                horse.trainer_name = trnr_match.group(1).strip()
                try:
                    horse.trainer_win_pct = float(trnr_match.group(6)) / 100
                except ValueError as e:
                    print(f"[!] Warning: could not parse trainer win pct for {name}: {e}")
                    horse.trainer_win_pct = 0.0

        # Jockey — PDF format: "LASTNAME FIRSTNAME (starts wins-places-shows win%)"
        # Variants seen:
        #   HAZLEWOOD YEDSIT (178 44-35-23 25%)
        #   SANCHEZ MYCHEL J (203 59-27-30 29%)
        #   VARGAS, JR. JORGE A (63 12-12-6 19%)
        # Strategy: line-by-line match to avoid catastrophic backtracking.
        if self.pattern_config:
            jky_match, pattern_idx = self._extract_field_with_patterns('jockey_name', block, name)
            if jky_match and pattern_idx >= 0:
                raw = jky_match.group(1).strip()
                words = [w.strip(',.') for w in raw.split() if w.strip(',.')]
                suffixes = {'JR', 'SR', 'II', 'III', 'IV', 'JR.', 'SR.'}
                name_words = [w for w in words if w.upper() not in suffixes]
                if len(name_words) >= 2:
                    last  = name_words[0].capitalize()
                    first = ' '.join(w.capitalize() for w in name_words[1:])
                    horse.jockey_name = f"{first} {last}"
                else:
                    horse.jockey_name = raw.title()
                try:
                    horse.jockey_win_pct = float(jky_match.group(3)) / 100
                except (ValueError, IndexError) as e:
                    print(f"[!] Warning: could not parse jockey win pct for {name}: {e}")
                    horse.jockey_win_pct = 0.0
        else:
            jky_match = None
            for _line in block.split('\n'):
                _s = _line.strip()
                if len(_s) < 8 or not _s[0].isupper() or '(' not in _s or '%' not in _s:
                    continue
                _first_word = _s.split()[0].rstrip(',.')
                if not _first_word.isupper() or len(_first_word) < 2:
                    continue
                if any(kw in _s for kw in ('Trnr:', 'Life:', 'Sire', 'Dam', 'JKYw', 'PRX', 'Trf')):
                    continue
                _m = re.match(
                    r'([A-Z][A-Z,\.\s]+?)\s+\((\d+)\s+\d+-\d+-\d+\s+(\d+)%\)',
                    _s
                )
                if _m:
                    jky_match = _m
                    break
            if jky_match:
                raw = jky_match.group(1).strip()
                words = [w.strip(',.') for w in raw.split() if w.strip(',.')]
                suffixes = {'JR', 'SR', 'II', 'III', 'IV', 'JR.', 'SR.'}
                name_words = [w for w in words if w.upper() not in suffixes]
                if len(name_words) >= 2:
                    last  = name_words[0].capitalize()
                    first = ' '.join(w.capitalize() for w in name_words[1:])
                    horse.jockey_name = f"{first} {last}"
                else:
                    horse.jockey_name = raw.title()
                try:
                    horse.jockey_win_pct = float(jky_match.group(3)) / 100
                except ValueError as e:
                    print(f"[!] Warning: could not parse jockey win pct for {name}: {e}")
                    horse.jockey_win_pct = 0.0

        # Past performance lines — extract E1, E2, speed figure, and distance.
        # Key format issues found in PDF:
        #   1. Distance: "6┬╜ft" (mojibake for 6½) — grab leading digit(s) before 'f'
        #   2. E1/E2: sometimes "95104/" (CR jammed onto E1, no space) vs "82 78/"
        #   3. Mile races: "1m" or "├á1╦åfm" — extract leading digit only
        pp_date_re  = re.compile(r'^\d{2}[A-Za-z]{3}\d{2}')
        # E1/E2: two separate patterns to avoid the \s* ambiguity that caused 95104 -> 951+4.
        # Pattern A (spaced):  "82 78/ 80 +1 +5 90"  -> E1=82, E2=78, SPD=90
        # Pattern B (jammed):  "95104/ 80 +1 +5 90"  -> CR=95 (2 digits), E1=104, SPD=90
        pp_speed_spaced = re.compile(r'(\d{2,3})\s+(\d{2,3})/\s*\d{2,3}\s+[+-]?\d+\s+[+-]?\d+\s+(\d{2,3})')
        pp_speed_jammed = re.compile(r'\d{2}(\d{2,3})/\s*\d{2,3}\s+[+-]?\d+\s+[+-]?\d+\s+(\d{2,3})')

        for line in block.split('\n'):
            line = line.strip()
            if not pp_date_re.match(line):
                continue
            sm = pp_speed_spaced.search(line)
            if sm:
                e1, e2, spd = int(sm.group(1)), int(sm.group(2)), int(sm.group(3))
            else:
                sm = pp_speed_jammed.search(line)
                if not sm:
                    continue
                e1 = int(sm.group(1))
                e2 = e1
                spd = int(sm.group(2))
            try:
                tokens = line.split()
                dist_f = 0.0
                for tok in tokens[1:5]:
                    dm = re.match(r'^(\d+(?:\.\d+)?)', tok)
                    if dm and ('f' in tok.lower() or tok.lower().endswith('m')):
                        raw_dist = float(dm.group(1))
                        if tok.lower().endswith('m') and 'f' not in tok.lower():
                            raw_dist *= 8
                        dist_f = raw_dist
                        break

                if 0 < e1 <= 150 and 0 < e2 <= 150 and 0 < spd <= 150:
                    horse.past_races.append({
                        'dist':   dist_f,
                        'e1':     e1,
                        'e2':     e2,
                        'speed':  spd,
                        'finish': 0,
                    })
            except (ValueError, IndexError):
                pass

        # Sire stats
        sire_match = re.search(
            r'Sire Stats:\s+AWD\s*([\d.]+)\s+(\d+)%\s+.*Mud\s*(\d+)MudSts\s*([\d.]+)spi', block
        )
        if sire_match:
            horse.sire_awd = float(sire_match.group(1))
            horse.sire_mud_sts = int(sire_match.group(3))
            horse.sire_mud_spi = float(sire_match.group(4))

        # Dam's Sire stats
        dam_match = re.search(
            r"Dam'sSire:\s+AWD\s*([\d.]+)\s+(\d+)%.*Mud\s*(\d+)MudSts\s*([\d.]+)spi", block
        )
        if dam_match:
            horse.dam_sire_awd = float(dam_match.group(1))
            horse.dam_sire_mud_sts = int(dam_match.group(3))
            horse.dam_sire_mud_spi = float(dam_match.group(4))

        horse.compute_features()

        if self.normalizer:
            self.normalizer.normalize_horse_record(horse)

        if self.validator:
            validation_results = self.validator.validate_horse_record(horse)
            horse.validation_results = validation_results
            failures = [r for r in validation_results if not r.is_valid]
            if failures:
                for result in failures:
                    print(f"[!] Validation {result.rule.severity}: {horse.name} - {result.message}")

        return horse
