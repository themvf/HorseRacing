"""Console output, diagnostics, and HTML report generation — mixin for HorseRacingEngine."""

import json
import webbrowser
import pathlib
from datetime import datetime

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


class ReportingMixin:
    """
    Provides all output methods: console display, Plotly charts, diagnostics,
    and self-contained HTML report export.
    Expects instance attributes from engine __init__ and FeaturesMixin:
        self.all_races, self.race_info, self.actual_results
        self.MODEL_WEIGHTS, self._SCORECARD_META
    """

    # ------------------------------------------------------------------
    # Console helpers
    # ------------------------------------------------------------------

    def _print_horse_scorecard(self, row):
        """
        Print the full component-by-component scorecard for a single horse.
          Prime Power: 123.4 (Rank #1) → Normalized: 1.000 → Contribution: 0.250 (25%)
          ...
          Total Composite Score: 0.858 → Win Probability: 15.7%
        """
        odds_label = f"{row['ML_Odds']:.1f}/1" if row['Odds_Parsed'] else "N/A"
        print(f"\n  {'─'*70}")
        print(f"  Key Components for {row['Horse']} ({odds_label})")
        print(f"  {'─'*70}")

        for norm_col, weight in self.MODEL_WEIGHTS.items():
            label, raw_fn = self._SCORECARD_META[norm_col]
            raw_str   = raw_fn(row)
            norm_val  = row[norm_col]
            contrib   = norm_val * weight
            print(
                f"  {label}: {raw_str}"
                f"\n    -> Normalized: {norm_val:.3f}"
                f"  -> Contribution: {contrib:.3f} ({contrib:.1%})"
            )

        print(f"\n  Total Composite Score: {row['Composite_Score']:.3f}"
              f"  -> Win Probability: {row['Win_Prob']:.1%}"
              f" (after softmax transformation)")
        print(f"  Analysis: {row['Analysis']}")

    def _generate_analysis(self, horse_row, df):
        """Generate analysis text for a horse."""
        reasons = []

        if horse_row['PP_Rank'] == 1:
            reasons.append("PP #1 (benchmark)")
        elif horse_row['PP_Rank'] <= 3:
            reasons.append(f"PP Rank #{int(horse_row['PP_Rank'])}")

        if horse_row['Odds_Parsed']:
            market_prob = horse_row['Market_Prob']
            if horse_row['Win_Prob'] > market_prob * 1.4:
                reasons.append("HIGH VALUE")
            elif horse_row['Win_Prob'] < market_prob * 0.6:
                reasons.append("Overvalued")
        else:
            reasons.append("Odds unavailable")

        if horse_row['Jockey_Win_Pct'] >= 0.25:
            reasons.append("Elite jockey")
        elif horse_row['Jockey_Win_Pct'] >= 0.15:
            reasons.append("Solid jockey")

        if horse_row['Trainer_Win_Pct'] >= 0.25:
            reasons.append("Elite trainer")
        elif horse_row['Trainer_Win_Pct'] >= 0.15:
            reasons.append("Solid trainer")

        if horse_row.get('Class_Delta', 0) > 0.15:
            reasons.append("Dropping in class")
        elif horse_row.get('Class_Delta', 0) < -0.15:
            reasons.append("Rising in class")

        if horse_row.get('Distance_Match', 0) >= 0.95:
            reasons.append("Proven at distance")
        elif horse_row.get('Distance_Match', 0) == 0.5:
            reasons.append("Unproven at distance")

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

    def diagnose_parse_quality(self):
        """
        Print a feature population report for every parsed horse across all races.

        For each feature used in MODEL_WEIGHTS, shows:
          - How many horses have a non-zero / non-default value (parsed successfully)
          - How many are defaulting to 0 (parse failed or field not in PDF)
          - The fill rate as a percentage

        This makes it immediately visible which signals are contributing real data
        vs. collapsing to 0.5 noise in _minmax_scale.
        """
        FEATURE_MAP = {
            'Market_Prob_Norm':    ('odds_parsed',        lambda h: h.odds_parsed),
            'Jockey_WPct_Norm':    ('jockey_win_pct',     lambda h: h.jockey_win_pct > 0),
            'Speed_Norm':          ('best_speed',         lambda h: h.best_speed > 0),
            'Form_Norm':           ('avg_finish',         lambda h: h.starts > 0),
            'Class_Delta_Norm':    ('claim_price',        lambda h: h.claim_price > 0),
            'Distance_Match_Norm': ('best_speed_at_dist', lambda h: len(h.past_races) > 0 and h.best_speed > 0),
            'Surface_Match_Norm':  ('sire_mud_spi',       lambda h: h.sire_mud_spi > 0 or h.dam_sire_mud_spi > 0),
            'Trainer_WPct_Norm':   ('trainer_win_pct',    lambda h: h.trainer_win_pct > 0),
            'Style_Norm':          ('style_num',          lambda h: h.style_num > 0),
            'WinPct_Norm':         ('starts/wins',        lambda h: h.starts > 0),
            'EarlySpeed_Norm':     ('early_speed_pct',    lambda h: h.early_speed_pct > 0),
            'CloserSpeed_Norm':    ('closer_speed_pct',   lambda h: h.closer_speed_pct > 0),
            'Earnings_Norm':       ('earnings',           lambda h: h.earnings > 0),
            'LastSpeed_Norm':      ('last_speed',         lambda h: h.last_speed > 0),
        }

        all_horses = []
        for rn in sorted(self.all_races.keys(), key=int):
            for h in self.all_races[rn]:
                all_horses.append((rn, h))

        total = len(all_horses)
        if total == 0:
            print("[!] No horses parsed yet. Run parse_races() first.")
            return

        print(f"\n{'='*70}")
        print(f"  PARSE QUALITY DIAGNOSTIC  —  {total} horses across {len(self.all_races)} races")
        print(f"{'='*70}")
        print(f"  {'Feature':<22} {'Field':<20} {'Parsed':>8} {'Missing':>8} {'Fill%':>7}  {'Weight':>7}")
        print(f"  {'-'*65}")

        issues = []
        for norm_col, (field_name, check_fn) in FEATURE_MAP.items():
            weight  = self.MODEL_WEIGHTS.get(norm_col, 0)
            parsed  = sum(1 for _, h in all_horses if check_fn(h))
            missing = total - parsed
            pct     = parsed / total * 100
            label   = self._SCORECARD_META.get(norm_col, (norm_col,))[0]
            flag    = "  <-- WARNING" if pct < 50 and weight > 0 else ""
            print(f"  {label:<22} {field_name:<20} {parsed:>8} {missing:>8} {pct:>6.0f}%  {weight:>6.0%}{flag}")
            if pct < 50 and weight > 0:
                issues.append((label, pct, weight))

        print(f"  {'-'*65}")

        if issues:
            print(f"\n  HIGH-IMPACT MISSING FIELDS  (>50% unparsed with weight > 0%)")
            for label, pct, weight in sorted(issues, key=lambda x: -x[2]):
                print(f"    {label}: {pct:.0f}% fill  x  {weight:.0%} weight"
                      f"  ->  contributing noise instead of signal")

        print(f"\n  PER-RACE JOCKEY PARSE RATE  (15% weight — highest unverified signal):")
        print(f"  {'Race':<8} {'Horses':>8} {'Jockey OK':>10} {'Fill%':>7}")
        print(f"  {'-'*36}")
        for rn in sorted(self.all_races.keys(), key=int):
            horses = self.all_races[rn]
            parsed = sum(1 for h in horses if h.jockey_win_pct > 0)
            pct    = parsed / len(horses) * 100 if horses else 0
            flag   = "  <-- WARNING" if pct < 50 else ""
            print(f"  {rn:<8} {len(horses):>8} {parsed:>10} {pct:>6.0f}%{flag}")

        print(f"\n  SAMPLE JOCKEY VALUES  (first 3 horses per race):")
        for rn in sorted(self.all_races.keys(), key=int):
            horses = self.all_races[rn][:3]
            samples = [(h.name, h.jockey_name or 'NOT PARSED', f"{h.jockey_win_pct:.1%}") for h in horses]
            print(f"  Race {rn}: " + "  |  ".join(
                f"{n} -> '{j}' {p}" for n, j, p in samples
            ))

        print(f"\n{'='*70}\n")

    def print_predictions(self, race_num):
        """Print predictions to console."""
        df = self.predict_race(race_num)
        if df is None or df.empty:
            print(f"No data for Race {race_num}")
            return

        print(f"\n{'='*60}")
        print(f"RACE {race_num} PREDICTIONS")
        print(f"{'='*60}")

        for _, row in df.iterrows():
            odds_label = f"{row['ML_Odds']}/1" if row['Odds_Parsed'] else "N/A"
            print(f"\n{row['Horse']} ({odds_label})")
            print(f"  Win Prob: {row['Win_Prob']:.1%}")
            print(f"  Prime Power: {row['PrimePower']:.1f} (Rank #{row['PP_Rank']})")
            print(f"  Analysis: {row['Analysis']}")

    def print_detailed_predictions(self, race_num):
        """
        Print full per-horse scorecards showing every model component:
          raw value → normalized → contribution (weight × normalized)
        followed by composite score and win probability for each horse.
        """
        df = self.predict_race(race_num)
        if df is None or df.empty:
            print(f"No data for Race {race_num}")
            return

        weight_summary = "  |  ".join(
            f"{self._SCORECARD_META[col][0]}={w:.0%}"
            for col, w in self.MODEL_WEIGHTS.items()
        )

        print(f"\n{'='*72}")
        print(f"  RACE {race_num} — FULL COMPOSITE SCORECARD")
        print(f"{'='*72}")
        print(f"  Model weights: {weight_summary}")

        print(f"\n  {'#':<3} {'Horse':<28} {'Odds':<8} {'Score':<8} {'Win Prob'}")
        print(f"  {'─'*60}")
        for rank, (_, row) in enumerate(df.iterrows(), 1):
            odds_label = f"{row['ML_Odds']:.1f}/1" if row['Odds_Parsed'] else "N/A"
            print(
                f"  {rank:<3} {row['Horse']:<28} {odds_label:<8} "
                f"{row['Composite_Score']:.3f}   {row['Win_Prob']:.1%}"
            )

        print(f"\n{'='*72}")
        print(f"  COMPONENT BREAKDOWN BY HORSE")
        print(f"{'='*72}")
        for _, row in df.iterrows():
            self._print_horse_scorecard(row)

        print(f"\n{'='*72}")

    # ------------------------------------------------------------------
    # HTML export
    # ------------------------------------------------------------------

    def export_html(self, output_path="horse_racing_results.html", auto_open=True):
        """
        Build a self-contained HTML report with one tab per race.
        Each tab contains:
          - A ranked summary table (horse, odds, composite score, win prob, analysis)
          - A full component scorecard table (one row per component per horse)
        Opens the file in the default browser when auto_open=True.
        """
        if not self.all_races:
            print("[!] No race data to export. Run parse_races() first.")
            return

        race_nums = sorted(self.all_races.keys(), key=lambda x: int(x))
        race_dfs  = {}
        for rn in race_nums:
            df = self.predict_race(rn)
            if df is not None and not df.empty:
                race_dfs[rn] = df

        if not race_dfs:
            print("[!] predict_race returned no data for any race.")
            return

        # ── helpers ───────────────────────────────────────────────────
        def _ordinal(n):
            return {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")

        def pct_bar(value, color):
            w = max(0, min(100, value * 100))
            return (
                f'<div class="bar-wrap">'
                f'<div class="bar" style="width:{w:.1f}%;background:{color}"></div>'
                f'<span class="bar-label">{value:.1%}</span>'
                f'</div>'
            )

        def rank_color(rank):
            return {1: "#2ecc71", 2: "#3498db", 3: "#9b59b6"}.get(rank, "#95a5a6")

        def summary_rows(df, actual):
            actual_pos = {self._normalize_name(name): i+1 for i, name in enumerate(actual)}
            rows = []
            for pred_rank, (_, r) in enumerate(df.iterrows(), 1):
                odds  = f"{r['ML_Odds']:.1f}/1" if r['Odds_Parsed'] else "N/A"
                color = rank_color(pred_rank)
                bar   = pct_bar(r['Win_Prob'], color)
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(pred_rank, f"#{pred_rank}")
                pp_rank_cell = f"<td class='muted'>#{int(r['PP_Rank'])}</td>"

                apos = actual_pos.get(self._normalize_name(r['Horse']))
                if not actual or apos is None:
                    actual_cell = ""
                else:
                    diff = pred_rank - apos
                    if apos == 1:
                        fin_badge = f"<span class='fin-badge fin-win'>1st ✓</span>"
                    elif apos <= 3:
                        fin_badge = f"<span class='fin-badge fin-place'>{apos}{_ordinal(apos)}</span>"
                    else:
                        fin_badge = f"<span class='fin-badge fin-other'>{apos}{_ordinal(apos)}</span>"

                    if diff == 0:
                        delta = "<span class='delta exact'>= exact</span>"
                    elif diff < 0:
                        delta = f"<span class='delta better'>▲ {abs(diff)} better</span>"
                    else:
                        delta = f"<span class='delta worse'>▼ {diff} worse</span>"
                    actual_cell = f"<td>{fin_badge}</td><td>{delta}</td>"

                rows.append(
                    f"<tr>"
                    f"<td><span class='medal'>{medal}</span></td>"
                    f"<td class='horse-name'>{r['Horse']}</td>"
                    f"<td>{odds}</td>"
                    f"{pp_rank_cell}"
                    f"<td>{r['Composite_Score']:.3f}</td>"
                    f"<td>{bar}</td>"
                    f"{actual_cell}"
                    f"<td class='analysis'>{r['Analysis']}</td>"
                    f"</tr>"
                )
            return "\n".join(rows)

        def scorecard_rows(df):
            cards = []
            for rank, (_, r) in enumerate(df.iterrows(), 1):
                odds  = f"{r['ML_Odds']:.1f}/1" if r['Odds_Parsed'] else "N/A"
                color = rank_color(rank)
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

                comp_rows = []
                for norm_col, weight in self.MODEL_WEIGHTS.items():
                    label, raw_fn = self._SCORECARD_META[norm_col]
                    raw_str  = raw_fn(r)
                    norm_val = r[norm_col]
                    contrib  = norm_val * weight
                    bar_html = (
                        f'<div class="mini-bar-wrap">'
                        f'<div class="mini-bar" style="width:{norm_val*100:.1f}%;'
                        f'background:{color}"></div>'
                        f'</div>'
                    )
                    comp_rows.append(
                        f"<tr>"
                        f"<td>{label}</td>"
                        f"<td class='raw-val'>{raw_str}</td>"
                        f"<td>{bar_html}{norm_val:.3f}</td>"
                        f"<td><strong>{contrib:.3f}</strong> ({contrib:.1%})</td>"
                        f"</tr>"
                    )

                comp_table = (
                    "<table class='comp-table'>"
                    "<thead><tr>"
                    "<th>Component</th><th>Raw Value</th>"
                    "<th>Normalized</th><th>Contribution</th>"
                    "</tr></thead>"
                    "<tbody>" + "\n".join(comp_rows) + "</tbody>"
                    "</table>"
                )

                cards.append(
                    f"<details class='horse-card'>"
                    f"<summary style='border-left:4px solid {color}'>"
                    f"  <span class='medal'>{medal}</span>"
                    f"  <span class='horse-name'>{r['Horse']}</span>"
                    f"  <span class='odds-badge'>{odds}</span>"
                    f"  <span class='score-badge'>Score: {r['Composite_Score']:.3f}</span>"
                    f"  <span class='prob-badge' style='background:{color}'>"
                    f"    {r['Win_Prob']:.1%}"
                    f"  </span>"
                    f"</summary>"
                    f"<div class='card-body'>{comp_table}"
                    f"<p class='analysis-line'>Analysis: {r['Analysis']}</p>"
                    f"</div>"
                    f"</details>"
                )
            return "\n".join(cards)

        def results_section(rn, df, actual):
            if not actual:
                return ""

            actual_pos  = {self._normalize_name(name): i+1 for i, name in enumerate(actual)}
            pred_order  = list(df['Horse'])
            pred_pos    = {self._normalize_name(name): i+1 for i, name in enumerate(pred_order)}

            pp_df    = df.sort_values('PP_Rank')
            pp_order = list(pp_df['Horse'])
            pp_pos   = {self._normalize_name(name): i+1 for i, name in enumerate(pp_order)}

            def _accuracy(order, actual_pos_map):
                wc = (self._normalize_name(order[0]) == self._normalize_name(actual[0])
                      if order and actual else False)
                t3a = {self._normalize_name(h) for h in actual[:3]}
                t3p = {self._normalize_name(h) for h in order[:3]}
                ov  = len(t3a & t3p)
                common = [h for h in actual
                          if self._normalize_name(h) in
                          {self._normalize_name(n) for n in order}]
                if len(common) >= 2:
                    apos_map = {self._normalize_name(h): i+1 for i, h in enumerate(actual)}
                    ppos_map = {self._normalize_name(h): i+1 for i, h in enumerate(order)}
                    d2  = sum((apos_map[self._normalize_name(h)] -
                               ppos_map[self._normalize_name(h)])**2
                              for h in common)
                    nc  = len(common)
                    rho = 1 - (6 * d2) / (nc * (nc**2 - 1))
                else:
                    rho = None
                return wc, ov, rho

            m_wc, m_ov, m_rho = _accuracy(pred_order, actual_pos)
            p_wc, p_ov, p_rho = _accuracy(pp_order,   actual_pos)

            def _badge(wc, ov, rho, label):
                wc_b = (f"<span class='stat-badge stat-good'>{label}: Winner ✓</span>"
                        if wc else
                        f"<span class='stat-badge stat-miss'>{label}: Winner ✗</span>")
                ov_b = (f"<span class='stat-badge "
                        f"{'stat-good' if ov >= 2 else 'stat-warn' if ov == 1 else 'stat-miss'}'>"
                        f"{label}: {ov}/3 top-3</span>")
                rho_b = (f"<span class='stat-badge stat-info'>{label} rank corr: {rho:.2f}</span>"
                         if rho is not None else "")
                return wc_b + " " + ov_b + " " + rho_b

            model_badges = _badge(m_wc, m_ov, m_rho, "Model")
            pp_badges    = _badge(p_wc, p_ov, p_rho, "Prime Power")

            chart_labels  = []
            chart_actual  = []
            chart_model   = []
            chart_pp      = []

            for horse_name in actual:
                short = horse_name.split()[0]
                chart_labels.append(short)
                chart_actual.append(actual_pos.get(self._normalize_name(horse_name), 0))
                chart_model.append(pred_pos.get(self._normalize_name(horse_name), 0))
                chart_pp.append(pp_pos.get(self._normalize_name(horse_name), 0))

            js_labels = json.dumps(chart_labels)
            js_actual = json.dumps(chart_actual)
            js_model  = json.dumps(chart_model)
            js_pp     = json.dumps(chart_pp)
            n_horses  = len(actual)
            chart_id  = f"chart_race{rn}"

            chart_html = f"""
<div class='chart-box'>
  <h3>Rank Comparison Chart — Race {rn}</h3>
  <p class='hint'>Lower bar = better rank. Bars grouped per horse: Actual (gold) · Our Model (blue) · Prime Power (purple).</p>
  <canvas id='{chart_id}' class='rank-chart'></canvas>
</div>
<script>
(function() {{
  var canvas = document.getElementById('{chart_id}');
  var labels  = {js_labels};
  var actual  = {js_actual};
  var model   = {js_model};
  var pp      = {js_pp};
  var n       = labels.length;
  var maxRank = Math.max(...actual, ...model, ...pp, 1);

  var BAR_W   = 18, GAP = 6, GROUP_PAD = 20, PAD_L = 36, PAD_T = 16, PAD_B = 56, PAD_R = 16;
  var groupW  = 3 * BAR_W + 2 * GAP;
  var totalW  = PAD_L + n * (groupW + GROUP_PAD) - GROUP_PAD + PAD_R;
  var totalH  = 260;
  var chartH  = totalH - PAD_T - PAD_B;

  canvas.width  = totalW;
  canvas.height = totalH;
  var ctx = canvas.getContext('2d');

  ctx.fillStyle = '#1a1d27';
  ctx.fillRect(0, 0, totalW, totalH);

  ctx.strokeStyle = '#2e3250';
  ctx.fillStyle   = '#8892b0';
  ctx.font        = '11px Segoe UI, sans-serif';
  ctx.textAlign   = 'right';
  for (var rank = 1; rank <= maxRank; rank++) {{
    var y = PAD_T + chartH - ((rank / maxRank) * chartH);
    ctx.beginPath();
    ctx.moveTo(PAD_L - 4, y);
    ctx.lineTo(totalW - PAD_R, y);
    ctx.stroke();
    ctx.fillText(rank, PAD_L - 6, y + 4);
  }}

  var COLORS = {{ actual: '#f1c40f', model: '#3498db', pp: '#9b59b6' }};
  var datasets = [
    {{ data: actual, color: COLORS.actual,  label: 'Actual' }},
    {{ data: model,  color: COLORS.model,   label: 'Model'  }},
    {{ data: pp,     color: COLORS.pp,      label: 'PP'     }},
  ];

  for (var gi = 0; gi < n; gi++) {{
    var gx = PAD_L + gi * (groupW + GROUP_PAD);
    for (var di = 0; di < datasets.length; di++) {{
      var val  = datasets[di].data[gi];
      if (!val) continue;
      var barH = (val / maxRank) * chartH;
      var bx   = gx + di * (BAR_W + GAP);
      var by   = PAD_T + chartH - barH;

      ctx.fillStyle = datasets[di].color;
      ctx.fillRect(bx, by, BAR_W, barH);

      ctx.fillStyle   = '#e8eaf6';
      ctx.font        = 'bold 10px Segoe UI, sans-serif';
      ctx.textAlign   = 'center';
      ctx.fillText('#' + val, bx + BAR_W / 2, by - 3);
    }}

    ctx.fillStyle = '#8892b0';
    ctx.font      = '10px Segoe UI, sans-serif';
    ctx.textAlign = 'center';
    var labelX = gx + groupW / 2;
    ctx.fillText(labels[gi], labelX, totalH - PAD_B + 14);
  }}

  var legendX = PAD_L;
  var legendY = totalH - 14;
  datasets.forEach(function(ds, i) {{
    ctx.fillStyle = ds.color;
    ctx.fillRect(legendX, legendY - 9, 12, 10);
    ctx.fillStyle   = '#8892b0';
    ctx.font        = '11px Segoe UI, sans-serif';
    ctx.textAlign   = 'left';
    ctx.fillText(ds.label, legendX + 15, legendY);
    legendX += 80;
  }});
}})();
</script>"""

            rows = []
            for fin_pos, horse_name in enumerate(actual, 1):
                m_ppos = pred_pos.get(self._normalize_name(horse_name))
                p_ppos = pp_pos.get(self._normalize_name(horse_name))

                def _delta_cell(ppos, fin_pos):
                    if ppos is None:
                        return "<span class='muted'>—</span>"
                    diff = ppos - fin_pos
                    if diff == 0:
                        return f"#{ppos} <span class='delta exact'>= exact</span>"
                    elif diff < 0:
                        return f"#{ppos} <span class='delta better'>▲ {abs(diff)}</span>"
                    else:
                        return f"#{ppos} <span class='delta worse'>▼ {diff}</span>"

                fin_label = {1: "🥇 1st", 2: "🥈 2nd", 3: "🥉 3rd"}.get(fin_pos, f"#{fin_pos}")
                row_class = "res-win" if fin_pos == 1 else "res-place" if fin_pos <= 3 else ""
                rows.append(
                    f"<tr class='{row_class}'>"
                    f"<td><strong>{fin_label}</strong></td>"
                    f"<td class='horse-name'>{horse_name}</td>"
                    f"<td>{_delta_cell(m_ppos, fin_pos)}</td>"
                    f"<td>{_delta_cell(p_ppos, fin_pos)}</td>"
                    f"</tr>"
                )

            return (
                f"<div class='results-box'>"
                f"<h3>Predicted vs Actual — Model vs Prime Power Benchmark</h3>"
                f"<div class='stat-badges'>{model_badges}</div>"
                f"<div class='stat-badges'>{pp_badges}</div>"
                f"{chart_html}"
                f"<table class='results-table'>"
                f"<thead><tr>"
                f"<th>Actual Finish</th><th>Horse</th>"
                f"<th>Our Model</th><th>Prime Power</th>"
                f"</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody>"
                f"</table>"
                f"</div>"
            )

        # ── tab buttons & panels ───────────────────────────────────────
        tab_buttons = []
        tab_panels  = []

        for rn, df in race_dfs.items():
            info      = self.race_info.get(rn, {})
            dist      = info.get('distance', '—')
            purse     = f"${info.get('purse', 0):,}" if 'purse' in info else '—'
            top_horse = df.iloc[0]['Horse']
            top_prob  = df.iloc[0]['Win_Prob']
            actual    = self.actual_results.get(rn, [])

            tab_buttons.append(
                f"<button class='tab-btn' onclick=\"showTab('race{rn}')\" "
                f"id='btn-race{rn}'>"
                f"Race {rn}"
                f"<span class='tab-sub'>{top_horse} {top_prob:.0%}</span>"
                f"</button>"
            )

            weight_pills = " ".join(
                f"<span class='pill'>{self._SCORECARD_META[col][0]}: "
                f"{w:.0%}</span>"
                for col, w in self.MODEL_WEIGHTS.items()
            )

            actual_headers = (
                "<th>Actual Finish</th><th>vs Predicted</th>"
                if actual else ""
            )

            tab_panels.append(
                f"<div class='tab-panel' id='race{rn}'>"
                f"<div class='race-header'>"
                f"  <h2>Race {rn}</h2>"
                f"  <div class='race-meta'>"
                f"    <span>📏 {dist}</span>"
                f"    <span>💰 Purse {purse}</span>"
                f"    <span>🐎 {len(df)} horses</span>"
                f"  </div>"
                f"  <div class='weight-pills'>{weight_pills}</div>"
                f"</div>"
                f"{results_section(rn, df, actual)}"
                f"<h3>Rankings</h3>"
                f"<p class='hint'>PP Rank column is the Prime Power benchmark — independent of our model.</p>"
                f"<table class='summary-table'>"
                f"<thead><tr>"
                f"<th>Model #</th><th>Horse</th><th>Odds</th>"
                f"<th>PP Rank ⚖</th><th>Composite Score</th>"
                f"<th>Win Probability</th>"
                f"{actual_headers}"
                f"<th>Analysis</th>"
                f"</tr></thead>"
                f"<tbody>{summary_rows(df, actual)}</tbody>"
                f"</table>"
                f"<h3>Component Scorecards</h3>"
                f"<p class='hint'>Click a horse to expand its full breakdown.</p>"
                f"{scorecard_rows(df)}"
                f"</div>"
            )

        first_race = f"race{race_nums[0]}"

        # ── full HTML document ─────────────────────────────────────────
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{self.track_name} — Predictions</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --border: #2e3250; --text: #e8eaf6; --muted: #8892b0;
    --green: #2ecc71; --blue: #3498db; --purple: #9b59b6;
    --gold: #f1c40f; --radius: 8px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; }}

  /* ── header ── */
  .page-header {{ background: linear-gradient(135deg, #1a1d27 0%, #0f1117 100%);
    border-bottom: 1px solid var(--border); padding: 24px 32px; }}
  .page-header h1 {{ font-size: 1.6rem; color: var(--green); letter-spacing: 1px; }}
  .page-header p  {{ color: var(--muted); margin-top: 4px; font-size: 0.85rem; }}

  /* ── tab bar ── */
  .tab-bar {{ display: flex; flex-wrap: wrap; gap: 6px;
    padding: 16px 32px; background: var(--surface); border-bottom: 1px solid var(--border); }}
  .tab-btn {{ background: var(--surface2); border: 1px solid var(--border); color: var(--muted);
    border-radius: var(--radius); padding: 8px 16px; cursor: pointer;
    display: flex; flex-direction: column; align-items: center; gap: 2px;
    transition: all .15s; font-size: 0.85rem; font-weight: 600; }}
  .tab-btn:hover  {{ border-color: var(--blue); color: var(--text); }}
  .tab-btn.active {{ background: var(--blue); border-color: var(--blue); color: #fff; }}
  .tab-sub {{ font-size: 0.7rem; font-weight: 400; opacity: .85; }}

  /* ── panels ── */
  .tab-panel {{ display: none; padding: 28px 32px; max-width: 1200px; margin: 0 auto; }}
  .tab-panel.active {{ display: block; }}

  .race-header {{ margin-bottom: 20px; }}
  .race-header h2 {{ font-size: 1.3rem; color: var(--green); margin-bottom: 8px; }}
  .race-meta {{ display: flex; gap: 20px; color: var(--muted); font-size: 0.85rem; margin-bottom: 10px; }}
  .weight-pills {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .pill {{ background: var(--surface2); border: 1px solid var(--border);
    border-radius: 20px; padding: 2px 10px; font-size: 0.75rem; color: var(--muted); }}

  h3 {{ font-size: 1rem; color: var(--muted); text-transform: uppercase;
    letter-spacing: 1px; margin: 24px 0 12px; }}
  .hint {{ color: var(--muted); font-size: 0.8rem; margin-bottom: 12px; }}

  /* ── summary table ── */
  .summary-table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
  .summary-table th {{ background: var(--surface2); color: var(--muted);
    text-align: left; padding: 10px 12px; font-size: 0.75rem;
    text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid var(--border); }}
  .summary-table td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  .summary-table tr:hover td {{ background: var(--surface2); }}
  .horse-name {{ font-weight: 600; color: var(--text); }}
  .analysis   {{ color: var(--muted); font-size: 0.8rem; max-width: 260px; }}
  .medal      {{ font-size: 1.1rem; }}

  /* ── win prob bar ── */
  .bar-wrap {{ display: flex; align-items: center; gap: 8px; min-width: 160px; }}
  .bar      {{ height: 8px; border-radius: 4px; min-width: 2px; transition: width .3s; }}
  .bar-label {{ font-size: 0.8rem; color: var(--text); white-space: nowrap; }}

  /* ── horse accordion cards ── */
  .horse-card {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); margin-bottom: 10px; overflow: hidden; }}
  .horse-card summary {{ display: flex; align-items: center; gap: 12px;
    padding: 14px 18px; cursor: pointer; list-style: none;
    border-left: 4px solid transparent; }}
  .horse-card summary::-webkit-details-marker {{ display: none; }}
  .horse-card summary:hover {{ background: var(--surface2); }}
  .odds-badge  {{ margin-left: auto; color: var(--muted); font-size: 0.8rem; }}
  .score-badge {{ background: var(--surface2); border: 1px solid var(--border);
    border-radius: 4px; padding: 2px 8px; font-size: 0.8rem; color: var(--muted); }}
  .prob-badge  {{ border-radius: 4px; padding: 3px 10px;
    font-size: 0.85rem; font-weight: 700; color: #fff; }}

  .card-body {{ padding: 0 18px 18px; }}

  /* ── component table ── */
  .comp-table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  .comp-table th {{ background: var(--surface2); color: var(--muted);
    text-align: left; padding: 8px 12px; font-size: 0.72rem;
    text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid var(--border); }}
  .comp-table td {{ padding: 9px 12px; border-bottom: 1px solid var(--border);
    vertical-align: middle; font-size: 0.82rem; }}
  .comp-table tr:last-child td {{ border-bottom: none; }}
  .raw-val {{ color: var(--muted); max-width: 240px; }}

  .mini-bar-wrap {{ display: inline-block; width: 80px; height: 6px;
    background: var(--surface2); border-radius: 3px; margin-right: 8px;
    vertical-align: middle; }}
  .mini-bar {{ height: 6px; border-radius: 3px; }}

  .analysis-line {{ color: var(--muted); font-size: 0.8rem;
    margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }}

  /* ── rank comparison chart ── */
  .chart-box {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px 24px; margin: 16px 0; overflow-x: auto; }}
  .rank-chart {{ display: block; border-radius: 4px; }}

  /* ── results comparison ── */
  .results-box {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px 24px; margin-bottom: 24px; }}
  .stat-badges {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 16px; }}
  .stat-badge {{ border-radius: 20px; padding: 3px 12px; font-size: 0.78rem; font-weight: 600; }}
  .stat-good {{ background: #1a3a2a; color: var(--green); border: 1px solid var(--green); }}
  .stat-miss {{ background: #3a1a1a; color: #e74c3c;    border: 1px solid #e74c3c; }}
  .stat-warn {{ background: #3a2e1a; color: var(--gold); border: 1px solid var(--gold); }}
  .stat-info {{ background: var(--surface2); color: var(--blue); border: 1px solid var(--blue); }}

  .results-table {{ width: 100%; border-collapse: collapse; }}
  .results-table th {{ background: var(--surface2); color: var(--muted);
    text-align: left; padding: 8px 12px; font-size: 0.72rem;
    text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid var(--border); }}
  .results-table td {{ padding: 9px 12px; border-bottom: 1px solid var(--border); font-size: 0.85rem; }}
  .results-table tr.res-win  td {{ background: #0d2b1a; }}
  .results-table tr.res-place td {{ background: #0d1a2b; }}

  .delta       {{ font-size: 0.75rem; margin-left: 8px; font-weight: 600; }}
  .delta.exact  {{ color: var(--green); }}
  .delta.better {{ color: var(--blue); }}
  .delta.worse  {{ color: #e74c3c; }}
  .fin-badge   {{ border-radius: 4px; padding: 2px 8px; font-size: 0.78rem; font-weight: 600; }}
  .fin-win     {{ background: #1a3a2a; color: var(--green); }}
  .fin-place   {{ background: #0d1a2b; color: var(--blue); }}
  .fin-other   {{ background: var(--surface2); color: var(--muted); }}
  .muted       {{ color: var(--muted); }}

  /* ── footer ── */
  .page-footer {{ text-align: center; padding: 24px; color: var(--muted);
    font-size: 0.75rem; border-top: 1px solid var(--border); margin-top: 40px; }}
</style>
</head>
<body>

<div class="page-header">
  <h1>🏇 {self.track_name} — Predictive Engine v4.0</h1>
  <p>Generated {datetime.now().strftime("%B %d, %Y at %I:%M %p")} &nbsp;·&nbsp;
     {len(race_dfs)} races &nbsp;·&nbsp;
     {sum(len(df) for df in race_dfs.values())} horses total</p>
</div>

<div class="tab-bar">
  {''.join(tab_buttons)}
</div>

{''.join(tab_panels)}

<div class="page-footer">
  {self.track_name} Predictive Engine v4.0 (Kiro) &nbsp;·&nbsp;
  Model weights: {' | '.join(f"{self._SCORECARD_META[c][0]} {w:.0%}" for c, w in self.MODEL_WEIGHTS.items())}
</div>

<script>
  function showTab(id) {{
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    document.getElementById('btn-' + id).classList.add('active');
  }}
  showTab('{first_race}');
</script>
</body>
</html>"""

        out = pathlib.Path(output_path)
        out.write_text(html, encoding="utf-8")
        print(f"[+] HTML report saved -> {out.resolve()}")

        if auto_open:
            webbrowser.open(out.resolve().as_uri())
            print("[*] Opened in browser.")

        return str(out.resolve())
