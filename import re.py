import re
import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pdfplumber

class ParxRacingEngine:
    """
    Senior Developer Implementation: 
    A modular engine to extract, model, and visualize horse racing probabilities.
    """
    def __init__(self):
        self.all_races = {} # Structure: { '1': DataFrame, '2': DataFrame ... }

    def extract_text_from_pdf(self, pdf_path):
        """
        Extracts raw text from PDF. Handles coordinates by using 
        pdfplumber's flow-reconstruction logic.
        """
        full_text = ""
        print(f"[*] Reading PDF: {pdf_path}...")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
            return full_text if full_text.strip() else None
        except Exception as e:
            print(f"[!] Critical error reading PDF: {e}")
            return None

    def parse_races(self, text):
        """
        Segments the document into races and extracts horse metrics.
        Uses 'Fuzzy Extraction' to find Prime Power even if columns are jumbled.
        """
        # 1. Segment by "Race X"
        race_splits = re.split(r'Race\s+(\d+)', text)
        
        # race_splits[0] is header, then [Num, Content, Num, Content...]
        for i in range(1, len(race_splits), 2):
            race_num = race_splits[i]
            race_content = race_splits[i+1]
            
            # 2. Segment into Horse Blocks
            # Look for a digit at start of line followed by a space and Capital Letter (e.g. "1 Borracho")
            horse_blocks = re.split(r'\n(?=\d\s+[A-Z])', race_content)
            
            race_horses = []
            for block in horse_blocks:
                if not block.strip(): continue
                
                try:
                    # Name extraction: Captures until the first parenthesis or newline
                    name_match = re.search(r'^\d\s+([A-Za-z\s\']+)', block)
                    if not name_match: continue
                    name = name_match.group(1).strip()

                    # FUZZY EXTRACTION for Prime Power:
                    # Look for the phrase, then grab the first decimal number appearing shortly after.
                    pp_val = 0
                    if "Prime Power" in block:
                        pp_search = re.search(r'Prime Power:?\s*.*?([\d.]+)', block)
                        if pp_search:
                            pp_val = float(pp_search.group(1))

                    # ML Odds extraction (matches "5/1", "10/1", etc.)
                    odds_match = re.search(r'(\d+/\d+)', block)
                    if odds_match:
                        num, den = map(int, odds_match.group(1).split('/'))
                        decimal_odds = num / den
                    else:
                        decimal_odds = 10.0 # Default fallback

                    # Style extraction (E, E/P, P, S)
                    style_match = re.search(r'\(([EPS/]{1,2})\s+\d\)', block)
                    style = style_match.group(1) if style_match else 'P'

                    race_horses.append({
                        'Horse': name,
                        'PrimePower': pp_val,
                        'ML_Odds': decimal_odds,
                        'Style': style
                    })
                except Exception:
                    continue
            
            if race_horses:
                self.all_races[race_num] = pd.DataFrame(race_horses)

    def generate_reasoning(self, horse, df):
        """
        Reasoning Engine: Compares individual horse to race averages.
        """
        reasons = []
        avg_pp = df['PrimePower'].mean()
        max_pp = df['PrimePower'].max()
        
        # Logic 1: Prime Power Comparison
        if horse['PrimePower'] == max_pp and max_pp > 0:
            reasons.append("Highest Prime Power in race")
        elif horse['PrimePower'] > avg_pp:
            reasons.append("Above average power rating")
        elif horse['PrimePower'] == 0:
            reasons.append("Limited data (PP=0)")
        
        # Logic 2: Market Value (Model Prob vs Market Prob)
        market_prob = 1 / (horse['ML_Odds'] + 1)
        if horse['Win_Prob'] > (market_prob * 1.3):
            reasons.append("High Value: Model is significantly more bullish than odds")
        elif horse['Win_Prob'] < (market_prob * 0.7):
            reasons.append("Overvalued by market")
        
        # Logic 3: Pace Scenario
        if horse['Style'] == 'E':
            reasons.append("Early speed: can steal the race from the front")
        elif horse['Style'] == 'S':
            reasons.append("Sustained closer: needs fast pace to collapse")

        return " | ".join(reasons) if reasons else "Balanced metrics"

    def predict_race(self, race_num):
        """
        The Mathematical Model.
        Uses a weighted composite score passed through a Softmax function.
        """
        if race_num not in self.all_races:
            return None
        
        df = self.all_races[race_num].copy()
        if df.empty:
            return None
        
        # 1. Implied Probability from Odds
        df['Market_Prob'] = 1 / (df['ML_Odds'].replace(0, np.nan).fillna(20) + 1)
        
        # 2. Normalize Prime Power (0.0 to 1.0 scale)
        max_pp = df['PrimePower'].max()
        df['PP_Score'] = df['PrimePower'] / max_pp if max_pp > 0 else 0
        
        # 3. Weighted Composite (70% Prime Power / 30% Market Sentiment)
        df['Composite_Score'] = (df['PP_Score'] * 0.7) + (df['Market_Prob'] * 0.3)
        
        # 4. Softmax Transformation
        # This converts raw scores into a probability distribution that sums to 100%
        exp_scores = np.exp(df['Composite_Score'] - np.max(df['Composite_Score']))
        df['Win_Prob'] = exp_scores / exp_scores.sum()
        
        # 5. Generate Explanations
        df['Analysis'] = df.apply(lambda row: self.generate_reasoning(row, df), axis=1)
        
        return df.sort_values('Win_Prob', ascending=False)

    def plot_race(self, race_num):
        """
        Professional Visualization Dashboard.
        """
        df = self.predict_race(race_num)
        if df is None: return

        fig = make_subplots(
            rows=1, cols=2, 
            specs=[[{"type": "bar"}, {"type": "indicator"}]],
            subplot_titles=("Win Probability", "Top Contender")
        )
        
        # Sort ascending for horizontal bar chart
        df_sorted = df.sort_values('Win_Prob', ascending=True)
        
        fig.add_trace(
            go.Bar(
                x=df_sorted['Horse'], 
                y=df_sorted['Win_Prob'], 
                orientation='h', 
                marker_color='rgb(55, 83, 109)',
                text=df_sorted['Win_Prob'].apply(lambda x: f"{x:.1%}"),
                textposition='auto'
            ),
            row=1, col=1
        )
        
        # Gauge for the top horse
        top_horse = df.iloc[0]
        fig.add_trace(
            go.Indicator(
                mode="gauge+number",
                value=top_horse['Win_Prob'] * 100,
                title={'text': f"{top_horse['Horse']}"},
                gauge={'axis': {'range': [0, 100]}, 'bar': {'color': "darkblue"}},
                number={'suffix': "%"}
            ),
            row=1, col=2
        )

        fig.update_layout(
            title=f"Race {race_num} Probability Model", 
            template="plotly_dark",
            showlegend=False,
            height=500
        )
        fig.show()

# ==========================================
# MAIN EXECUTION LOOP
# ==========================================
if __name__ == "__main__":
    engine = ParxRacingEngine()
    
    print("\n" + "="*40)
    print(" PARX RACING PREDICTIVE ENGINE")
    print("="*40)
    
    user_input = input("Please enter the full path to your PDF file: ")
    user_path = user_input.strip().strip('"').strip("'")
    
    if os.path.exists(user_path):
        extracted_text = engine.extract_text_from_pdf(user_path)
        
        if extracted_text:
            engine.parse_races(extracted_text)
            
            available_races = list(engine.all_races.keys())
            if not available_races:
                print("\n[!] No race data found. This PDF may be a 'scanned image' (OCR required).")
            else:
                print(f"\n[+] Successfully identified races: {available_races}")
                
                while True:
                    race_id = input("\nEnter Race Number to analyze (or 'q' to quit): ")
                    if race_id.lower() == 'q': break
                    
                    if race_id in available_races:
                        results = engine.predict_race(race_id)
                        print(f"\n--- DETAILED PREDICTIONS FOR RACE {race_id} ---")
                        # Print formatted table with the "Why" analysis
                        print(results[['Horse', 'Win_Prob', 'Analysis']].to_string(index=False))
                        engine.plot_race(race_id)
                    else:
                        print("Race number not found. Please try again.")
        else:
            print("[X] Could not extract text from PDF.")
    else:
        print(f"[X] File not found at: {user_path}")