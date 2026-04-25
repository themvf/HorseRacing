"""
Parx Racing Predictive Engine v2.0
Enhanced engine to extract, model, and visualize horse racing probabilities.
Uses comprehensive past performance data for predictions.
"""

import re
import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pdfplumber
from datetime import datetime


class Horse:
    """Individual horse with comprehensive data."""
    
    def __init__(self, name):
        self.name = name
        self.odds = 0.0
        self.prime_power = 0.0
        self.pp_rank = 0
        self.style = "P"
        self.style_num = 0
        self.claim_price = 0
        self.color_sex = ""
        self.foal_year = 0
        self.sire = ""
        self.dam_sire = ""
        
        # Life stats
        self.starts = 0
        self.wins = 0
        self.places = 0
        self.shows = 0
        self.earnings = 0.0
        self.best_speed = 0
        self.best_speed_surface = ""
        
        # Current form
        self.class_rating = 0
        self.last_speed = 0
        self.best_speed_at_dist = 0
        
        # Trainer/Jockey
        self.trainer_name = ""
        self.trainer_stats = ""  # e.g., "156 43-23-31 28%"
        self.trainer_win_pct = 0.0
        self.jockey_name = ""
        self.jockey_stats = ""
        self.jockey_win_pct = 0.0
        
        # Sire stats
        self.sire_awd = 0.0
        self.sire_mud_sts = 0
        self.sire_mud_spi = 0.0
        self.dam_sire_awd = 0.0
        self.dam_sire_mud_sts = 0
        self.dam_sire_mud_spi = 0.0
        
        # Past performances (list of dicts)
        self.past_races = []
        
        # Workouts (list of times)
        self.workouts = []
        
        # Derived features
        self.recent_form = ""  # e.g., "312"
        self.avg_finish = 0.0
        self.early_speed_pct = 0.0
        self.closer_speed_pct = 0.0
        self.train_wins = 0
        self.jky_wins = 0
        
    def compute_features(self):
        """Compute derived features from parsed data."""
        if not self.past_races:
            return
            
        # Recent form (last 3 finishes)
        finishes = [r.get('finish', 0) for r in self.past_races[:3]]
        self.recent_form = "".join([str(f) if f else "-" for f in finishes])
        
        # Average finish position
        valid_finishes = [r.get('finish', 0) for r in self.past_races if r.get('finish', 0) > 0]
        self.avg_finish = np.mean(valid_finishes) if valid_finishes else 5.0
        
        # Early vs Late speed percentages
        early_spd = [r.get('e1', 0) for r in self.past_races if r.get('e1', 0) > 0]
        late_spd = [r.get('e2', 0) for r in self.past_races if r.get('e2', 0) > 0]
        
        if early_spd:
            self.early_speed_pct = np.mean(early_spd)
        if late_spd:
            self.closer_speed_pct = np.mean(late_spd)


class ParxRacingEngineV2:
    """
    Enhanced Parx Racing Engine.
    Extracts comprehensive data and builds predictive models.
    """
    
    def __init__(self):
        self.all_races = {}  # Structure: { '1': [Horse, Horse, ...], '2': [...] }
        self.race_info = {}     # Race metadata
        
    def extract_text_from_pdf(self, pdf_path):
        """Extract raw text from PDF."""
        full_text = ""
        print(f"[*] Reading PDF: {pdf_path}...")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                print(f"[*] Total pages: {total_pages}")
                
                # Read all pages
                max_pages = total_pages
                for i, page in enumerate(pdf.pages[:max_pages]):
                    print(f"[*] Reading page {i+1}/{max_pages}...", end='\r')
                    text = page.extract_text()
                    if text:
                        full_text += f"\n--- PAGE {i+1} ---\n" + text + "\n"
                print(f"\n[*] Extracted {len(full_text)} characters")
            return full_text if full_text.strip() else None
        except Exception as e:
            print(f"[!] Critical error reading PDF: {e}")
            return None
    
    def parse_races(self, text):
        """Parse races from extracted text."""
        # Find all race headers with context verification
        race_markers = list(re.finditer(r'Race\s+(\d+)\s*\n#\s+Speed', text))
        
        for idx, match in enumerate(race_markers):
            race_num = match.group(1)
            start_pos = match.start()
            
            # End position is next race marker or end of text
            end_pos = race_markers[idx + 1].start() if idx + 1 < len(race_markers) else len(text)
            
            race_content = text[start_pos:end_pos]
            
            print(f"[*] Processing Race {race_num} ({len(race_content)} chars)")
            
            # Parse race metadata
            self._parse_race_info(race_num, race_content)
            
            # Parse horses
            horses = self._parse_horses(race_content)
            if horses:
                self.all_races[race_num] = horses
                print(f"[+] Race {race_num}: {len(horses)} horses parsed")
            else:
                print(f"[!] No horses found in Race {race_num}")
                
    def _parse_race_info(self, race_num, text):
        """Parse race metadata (distance, purse, conditions)."""
        info = {'race_num': race_num}
        
        # Extract distance
        dist_match = re.search(r'(\d+[\½\/\.]?Furlongs?|\d+[½\.]?f)', text, re.IGNORECASE)
        if dist_match:
            info['distance'] = dist_match.group(1)
            
        # Extract claiming price
        clm_match = re.search(r'Clm\s*(\d+)', text, re.IGNORECASE)
        if clm_match:
            info['claim_price'] = int(clm_match.group(1))
            
        # Extract purse
        purse_match = re.search(r'Purse\s*\$?([\d,]+)', text, re.IGNORECASE)
        if purse_match:
            info['purse'] = int(purse_match.group(1).replace(',', ''))
            
        self.race_info[race_num] = info
        
    def _parse_horses(self, text):
        """Parse all horses in a race."""
        horses = []
        
        # Find all horse blocks - pattern: number at start followed by capital letter name
        # e.g., "1 Three Captains" or "2 Borracho"
        horse_pattern = r'(\d+)\s+([A-Z][a-zA-Z\s\'\-\.]+?)\s*\(([A-Z/]+)\s*(\d+)\)'
        matches = list(re.finditer(horse_pattern, text))
        
        for idx, match in enumerate(matches):
            horse_num = match.group(1)
            horse_name = match.group(2).strip()
            style_str = match.group(3)
            style_num = match.group(4)
            
            # Get block content (from this horse to next)
            start_pos = match.start()
            end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            block = text[start_pos:end_pos]
            
            horse = self._parse_horse_block(block, horse_name, style_str, style_num)
            if horse and horse.name:
                horses.append(horse)
                
        return horses
    
    def _parse_horse_block(self, block, name, style_str, style_num):
        """Parse a single horse's data block."""
        horse = Horse(name)
        
        # Running style
        horse.style = style_str.split()[0] if style_str else "P"
        try:
            horse.style_num = int(style_num) if style_num else 0
        except:
            horse.style_num = 0
            
        # Extract ML Odds from block
        odds_match = re.search(r'(\d+/\d+)\s+[O]', block)
        if odds_match:
            try:
                num, den = map(int, odds_match.group(1).split('/'))
                horse.odds = num / den
            except:
                horse.odds = 10.0
        else:
            horse.odds = 10.0
            
        # Extract claim price
        clm_match = re.search(r'\$(\d{4,6})', block)
        if clm_match:
            horse.claim_price = int(clm_match.group(1))
            
        # Prime Power
        pp_match = re.search(r'Prime Power:\s*([\d.]+)\s*\((\d+)(?:st|nd|rd|th)\)', block)
        if pp_match:
            horse.prime_power = float(pp_match.group(1))
            horse.pp_rank = int(pp_match.group(2))
            
        # Life stats
        life_match = re.search(r'Life:\s*(\d+)\s+(\d+)\s*-?\s*(\d+)\s*-?\s*(\d+)\s*\$?([\d,]+)', block)
        if life_match:
            horse.starts = int(life_match.group(1))
            horse.wins = int(life_match.group(2))
            horse.places = int(life_match.group(3))
            horse.shows = int(life_match.group(4))
            try:
                horse.earnings = float(life_match.group(5).replace(',', ''))
            except:
                horse.earnings = 0
                
        # Best speed (Fst)
        speed_match = re.search(r'Fst\((\d+)\)', block)
        if speed_match:
            horse.best_speed = int(speed_match.group(1))
            
        # Class Rating
        cr_match = re.search(r'(\d+)\s+Fst', block)
        if cr_match:
            horse.class_rating = int(cr_match.group(1))
            
        # Last race speed
        last_spd_match = re.search(r'(\d+)\s+\d+/\s*\d+\s+\d+\s+-\s*\d+', block)
        if last_spd_match:
            horse.last_speed = int(last_spd_match.group(1))
            
        # Trainer
        trnr_match = re.search(r'Trnr:\s+([A-Za-z\s\-\'\.]+?)\s+\(([\d]+)\s+([\d]+)-([\d]+)-([\d]+)\s+(\d+)%\)', block)
        if trnr_match:
            horse.trainer_name = trnr_match.group(1).strip()
            horse.trainer_win_pct = float(trnr_match.group(6)) / 100
            
        # Jockey
        jky_match = re.search(r'([A-Z][a-z]+)\s+([A-Z][a-z\-\'\.]+?)\s+\(([\d]+)\s+([\d]+)-([\d]+)-([\d]+)\s+(\d+)%\)', block)
        if jky_match:
            horse.jockey_name = jky_match.group(2).strip()
            horse.jockey_win_pct = float(jky_match.group(7)) / 100
            
        # Sire stats
        sire_match = re.search(r'Sire Stats:\s+AWD\s*([\d.]+)\s+(\d+)%\s+.*Mud\s*(\d+)MudSts\s*([\d.]+)spi', block)
        if sire_match:
            horse.sire_awd = float(sire_match.group(1))
            horse.sire_mud_sts = int(sire_match.group(3))
            horse.sire_mud_spi = float(sire_match.group(4))
            
        # Dam's Sire stats
        dam_match = re.search(r"Dam'sSire:\s+AWD\s*([\d.]+)\s+(\d+)%.*Mud\s*(\d+)MudSts\s*([\d.]+)spi", block)
        if dam_match:
            horse.dam_sire_awd = float(dam_match.group(1))
            horse.dam_sire_mud_sts = int(dam_match.group(3))
            horse.dam_sire_mud_spi = float(dam_match.group(4))
            
        # Compute derived features
        horse.compute_features()
        
        return horse
    
    def _parse_horse_line(self, horse, line):
        """Parse additional horse info from a line."""
        # Prime Power
        if "Prime Power:" in line:
            pp_match = re.search(r'Prime Power:\s*([\d.]+)\s*\((\d+)(?:st|nd|rd|th)\)', line)
            if pp_match:
                horse.prime_power = float(pp_match.group(1))
                horse.pp_rank = int(pp_match.group(2))
                
        # Life stats
        if "Life:" in line:
            life_match = re.search(r'Life:\s*(\d+)\s+(\d+)\s+-\s+(\d+)\s+-\s+(\d+)\s+\$?([\d,]+)', line)
            if life_match:
                horse.starts = int(life_match.group(1))
                horse.wins = int(life_match.group(2))
                horse.places = int(life_match.group(3))
                horse.shows = int(life_match.group(4))
                horse.earnings = float(life_match.group(5).replace(',', ''))
                
        # Best speed
        if "Fst(" in line:
            speed_match = re.search(r'Fst\((\d+)\)', line)
            if speed_match:
                horse.best_speed = int(speed_match.group(1))
                
        # Trainer
        if "Trnr:" in line:
            trnr_match = re.search(r'Trnr:\s+([A-Za-z\s\-\'\.]+)\s+\((\d+)\s+(\d+)-(\d+)-(\d+)\s+(\d+)%\)', line)
            if trnr_match:
                horse.trainer_name = trnr_match.group(1).strip()
                horse.trainer_win_pct = float(trnr_match.group(6)) / 100
                
        # Jockey
        if "JKYw/" not in line and any(name in line for name in ["AZ", "AW", "L ", "Lb", "Lbf"]):
            # Skip jockey lines for now
            pass
            
    def predict_race(self, race_num, model_type="enhanced"):
        """
        Predict race outcomes using multiple features.
        
        model_type: "simple" (PP only), "enhanced" (multiple features)
        """
        if race_num not in self.all_races:
            return None
            
        horses = self.all_races[race_num]
        if not horses:
            return None
            
        # Build feature matrix
        n = len(horses)
        features = []
        
        for horse in horses:
            f = {
                'Horse': horse.name,
                'PrimePower': horse.prime_power,
                'PP_Rank': horse.pp_rank,
                'ML_Odds': horse.odds,
                'Market_Prob': 1 / (horse.odds + 1) if horse.odds > 0 else 0.1,
                'Starts': horse.starts,
                'Wins': horse.wins,
                'Win_Pct': horse.wins / horse.starts if horse.starts > 0 else 0,
                'Earnings': horse.earnings,
                'Best_Speed': horse.best_speed,
                'Last_Speed': horse.last_speed,
                'Class_Rating': horse.class_rating,
                'Best_Speed_Dist': horse.best_speed_at_dist,
                'Trainer_Win_Pct': horse.trainer_win_pct,
                'Jockey_Win_Pct': horse.jockey_win_pct,
                'Style_Num': horse.style_num,
                'Avg_Finish': horse.avg_finish,
                'Early_Speed': horse.early_speed_pct,
                'Closer_Speed': horse.closer_speed_pct,
            }
            features.append(f)
            
        df = pd.DataFrame(features)
        
        # Normalize scores
        df = self._normalize_features(df)
        
        # Compute composite scores based on model type
        if model_type == "simple":
            df['Composite_Score'] = df['PP_Score_Norm']
        else:
            # Enhanced model weights
            df['Composite_Score'] = (
                df['PP_Score_Norm'] * 0.25 +
                df['Market_Prob_Norm'] * 0.15 +
                df['Trainer_WPct_Norm'] * 0.10 +
                df['Speed_Norm'] * 0.20 +
                df['Form_Norm'] * 0.15 +
                df['Style_Norm'] * 0.10 +
                df['WinPct_Norm'] * 0.05
            )
            
        # Softmax transformation
        exp_scores = np.exp(df['Composite_Score'] - np.max(df['Composite_Score']))
        df['Win_Prob'] = exp_scores / exp_scores.sum()
        
        # Generate analysis
        df['Analysis'] = df.apply(lambda row: self._generate_analysis(row, df), axis=1)
        
        return df.sort_values('Win_Prob', ascending=False)
    
    def _normalize_features(self, df):
        """Normalize features to 0-1 scale."""
        # Prime Power
        if df['PrimePower'].max() > 0:
            df['PP_Score_Norm'] = df['PrimePower'] / df['PrimePower'].max()
        else:
            df['PP_Score_Norm'] = 0.5
            
        # Market probability (inverted - lower odds = higher probability)
        df['Market_Prob_Norm'] = df['Market_Prob'] / df['Market_Prob'].max() if df['Market_Prob'].max() > 0 else 0.5
        
        # Trainer win percentage
        df['Trainer_WPct_Norm'] = df['Trainer_Win_Pct'] / df['Trainer_Win_Pct'].max() if df['Trainer_Win_Pct'].max() > 0 else 0.5
        
        # Best speed
        if df['Best_Speed'].max() > 0:
            df['Speed_Norm'] = df['Best_Speed'] / df['Best_Speed'].max()
        else:
            df['Speed_Norm'] = 0.5
            
        # Form (inverse of average finish)
        max_finish = df['Avg_Finish'].max()
        df['Form_Norm'] = 1 - (df['Avg_Finish'] / max_finish) if max_finish > 0 else 0.5
        
        # Running style
        df['Style_Norm'] = df['Style_Num'] / df['Style_Num'].max() if df['Style_Num'].max() > 0 else 0.5
        
        # Win percentage
        df['WinPct_Norm'] = df['Win_Pct'] / df['Win_Pct'].max() if df['Win_Pct'].max() > 0 else 0.5
        
        return df
    
    def _generate_analysis(self, horse_row, df):
        """Generate analysis text for a horse."""
        reasons = []
        
        # Prime Power
        if horse_row['PP_Rank'] == 1:
            reasons.append("Top Prime Power")
        elif horse_row['PP_Rank'] <= 3:
            reasons.append(f"Prime Power Rank #{int(horse_row['PP_Rank'])}")
            
        # Value
        market_prob = horse_row['Market_Prob']
        if horse_row['Win_Prob'] > market_prob * 1.4:
            reasons.append("HIGH VALUE")
        elif horse_row['Win_Prob'] < market_prob * 0.6:
            reasons.append("Overvalued")
            
        # Trainer
        if horse_row['Trainer_Win_Pct'] >= 0.25:
            reasons.append("Elite trainer")
        elif horse_row['Trainer_Win_Pct'] >= 0.15:
            reasons.append("Solid trainer")
            
        # Form
        if horse_row['Avg_Finish'] <= 3:
            reasons.append("Excellent recent form")
        elif horse_row['Avg_Finish'] >= 5:
            reasons.append("Needs improvement")
            
        return " | ".join(reasons) if reasons else "Mixed metrics"
    
    def plot_race(self, race_num):
        """Visualize race predictions."""
        df = self.predict_race(race_num)
        if df is None or df.empty:
            print("No data to plot")
            return
            
        fig = make_subplots(
            rows=1, cols=2,
            specs=[[{"type": "bar"}, {"type": "indicator"}]],
            subplot_titles=("Win Probability", "Top Contender")
        )
        
        df_sorted = df.sort_values('Win_Prob', ascending=True)
        
        # Bar chart
        colors = ['green' if x > 0.25 else 'blue' if x > 0.15 else 'gray' 
                 for x in df_sorted['Win_Prob']]
        
        fig.add_trace(
            go.Bar(
                x=df_sorted['Win_Prob'],
                y=df_sorted['Horse'],
                orientation='h',
                marker_color=colors,
                text=df_sorted['Win_Prob'].apply(lambda x: f"{x:.1%}"),
                textposition='auto'
            ),
            row=1, col=1
        )
        
        # Gauge for top horse
        top = df.iloc[0]
        fig.add_trace(
            go.Indicator(
                mode="gauge+number",
                value=top['Win_Prob'] * 100,
                title={'text': top['Horse']},
                gauge={'axis': {'range': [0, 100]}, 'bar': {'color': 'darkgreen'}},
                number={'suffix': "%"}
            ),
            row=1, col=2
        )
        
        fig.update_layout(
            title=f"Race {race_num} Prediction Model",
            template="plotly_dark",
            showlegend=False,
            height=500
        )
        fig.show()
        
    def print_predictions(self, race_num):
        """Print predictions to console."""
        df = self.predict_race(race_num)
        if df is None or df.empty:
            print(f"No data for Race {race_num}")
            return
            
        print(f"\n{'='*60}")
        print(f"RACE {race_num} PREDICTIONS")
        print(f"{'='*60}")
        
        for i, row in df.iterrows():
            print(f"\n{row['Horse']} ({row['ML_Odds']}/1)")
            print(f"  Win Prob: {row['Win_Prob']:.1%}")
            print(f"  Prime Power: {row['PrimePower']:.1f} (Rank #{row['PP_Rank']})")
            print(f"  Analysis: {row['Analysis']}")
            
    def print_detailed_predictions(self, race_num):
        """Print detailed predictions showing all model components."""
        df = self.predict_race(race_num)
        if df is None or df.empty:
            print(f"No data for Race {race_num}")
            return
            
        # Show the feature breakdown
        feature_cols = ['Horse', 'ML_Odds', 'Market_Prob', 'Win_Prob',
                       'PP_Score_Norm', 'Market_Prob_Norm', 'Trainer_WPct_Norm',
                       'Speed_Norm', 'Form_Norm', 'Style_Norm', 'WinPct_Norm',
                       'Composite_Score']
        
        # Only show columns that exist
        available_cols = [col for col in feature_cols if col in df.columns]
        detail_df = df[available_cols].copy()
        
        print(f"\n{'='*80}")
        print(f"RACE {race_num} DETAILED MODEL BREAKDOWN")
        print(f"{'='*80}")
        print("Weights: PP=25%, Market=15%, Trainer=10%, Speed=20%, Form=15%, Style=10%, WinPct=5%")
        print("-" * 80)
        
        # Format for display
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.float_format', lambda x: f'{x:.3f}')
        
        print(detail_df.to_string(index=False))
        print("-" * 80)
        
        # Show top horse explanation
        top = df.iloc[0]
        print(f"\nTOP HORSE: {top['Horse']}")
        print(f"  Win Probability: {top['Win_Prob']:.1%}")
        print(f"  Composite Score: {top['Composite_Score']:.3f}")
        print("  Component Contributions:")
        print(f"    Prime Power: {top['PP_Score_Norm']:.3f} × 0.25 = {top['PP_Score_Norm']*0.25:.3f}")
        print(f"    Market Odds: {top['Market_Prob_Norm']:.3f} × 0.15 = {top['Market_Prob_Norm']*0.15:.3f}")
        print(f"    Trainer: {top['Trainer_WPct_Norm']:.3f} × 0.10 = {top['Trainer_WPct_Norm']*0.10:.3f}")
        print(f"    Speed: {top['Speed_Norm']:.3f} × 0.20 = {top['Speed_Norm']*0.20:.3f}")
        print(f"    Form: {top['Form_Norm']:.3f} × 0.15 = {top['Form_Norm']*0.15:.3f}")
        print(f"    Style: {top['Style_Norm']:.3f} × 0.10 = {top['Style_Norm']*0.10:.3f}")
        print(f"    Win Pct: {top['WinPct_Norm']:.3f} × 0.05 = {top['WinPct_Norm']*0.05:.3f}")
        print(f"  Analysis: {top['Analysis']}")


# Main execution - Auto mode
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--pdf', default='prx0422y.pdf', help='PDF file path')
    parser.add_argument('--race', default='1', help='Race number to analyze')
    parser.add_argument('--plot', action='store_true', help='Show plot')
    parser.add_argument('--detail', action='store_true', help='Show detailed model breakdown')
    parser.add_argument('--auto', action='store_true', help='Auto mode (analyze and exit)')
    args = parser.parse_args()
    
    engine = ParxRacingEngineV2()
    
    print("\n" + "="*50)
    print(" PARX RACING PREDICTIVE ENGINE v2.0")
    print("="*50)
    
    if os.path.exists(args.pdf):
        text = engine.extract_text_from_pdf(args.pdf)
        
        if text:
            engine.parse_races(text)
            
            print(f"\n[+] Found races: {list(engine.all_races.keys())}")
            
            for race_num in engine.all_races.keys():
                horses = engine.all_races[race_num]
                print(f"\n  Race {race_num}: {len(horses)} horses")
                for h in horses:
                    print(f"    - {h.name} (PP: {h.prime_power:.1f}, Odds: {h.odds}/1)")
                    
            if args.race in engine.all_races:
                if args.detail:
                    engine.print_detailed_predictions(args.race)
                else:
                    engine.print_predictions(args.race)
                if args.plot:
                    engine.plot_race(args.race)
            else:
                print(f"\nRace {args.race} not found")
    else:
        print(f"[X] File not found: {args.pdf}")