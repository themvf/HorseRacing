"""Diagnostic check — parse quality and field coverage."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from horse_racing_engine import HorseRacingEngine

engine = HorseRacingEngine()
text = engine.extract_text_from_pdf('samples/prx0422y.pdf')
engine.parse_races(text)
engine.diagnose_parse_quality()

print("\n=== RACE DISTANCES ===")
for rn in sorted(engine.race_info.keys(), key=int):
    i = engine.race_info[rn]
    print(f"  Race {rn}: {i.get('distance','?')}  dist_f={i.get('distance_f','?')}  clm={i.get('claim_price','?')}")

print("\n=== SAMPLE HORSE FIELDS (Race 1, first 3 horses) ===")
for h in list(engine.all_races.get('1', []))[:3]:
    print(f"\n  {h.name}")
    print(f"    jockey='{h.jockey_name}' win%={h.jockey_win_pct:.1%}")
    print(f"    claim_price={h.claim_price}  best_speed={h.best_speed}  last_speed={h.last_speed}")
    print(f"    avg_finish={h.avg_finish:.2f}  starts={h.starts}  wins={h.wins}")
    print(f"    past_races={len(h.past_races)}  sample={h.past_races[:2]}")
    dist_f = engine.race_info.get('1', {}).get('distance_f', 0)
    bsd = h.best_speed_at_distance(dist_f)
    print(f"    best_speed_at_dist({dist_f}f)={bsd}")
