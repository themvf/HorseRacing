"""
Create baseline extraction results from the current parser.
Run this once to capture the current parse rates before making changes.
Stores results in tests/baselines/prx0422y_baseline.json
"""
import sys, os, json, pathlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from horse_racing_engine_v4_kiro import HorseRacingEngine

def create_baseline(pdf_path: str, output_path: str):
    engine = HorseRacingEngine()
    text = engine.extract_text_from_pdf(pdf_path)
    if not text:
        print(f"[!] Failed to extract text from {pdf_path}")
        return

    engine.parse_races(text)

    baseline = {
        "pdf_file": os.path.basename(pdf_path),
        "total_horses": sum(len(h) for h in engine.all_races.values()),
        "total_races": len(engine.all_races),
        "races": {}
    }

    # Per-field counts across all horses
    field_checks = {
        "odds_parsed":        lambda h: h.odds_parsed,
        "jockey_parsed":      lambda h: h.jockey_win_pct > 0 or h.jockey_name != "",
        "trainer_parsed":     lambda h: h.trainer_win_pct > 0,
        "speed_parsed":       lambda h: h.best_speed > 0,
        "life_parsed":        lambda h: h.starts > 0,
        "claim_price_parsed": lambda h: h.claim_price > 0,
        "past_races_parsed":  lambda h: len(h.past_races) > 0,
    }

    global_counts = {f: 0 for f in field_checks}
    global_total = 0

    for rn in sorted(engine.all_races.keys(), key=int):
        horses = engine.all_races[rn]
        race_data = {
            "total_horses": len(horses),
            "field_counts": {},
            "field_rates": {},
            "horses": []
        }

        for field, check_fn in field_checks.items():
            count = sum(1 for h in horses if check_fn(h))
            race_data["field_counts"][field] = count
            race_data["field_rates"][field] = round(count / len(horses), 3) if horses else 0.0
            global_counts[field] += count

        global_total += len(horses)

        for h in horses:
            race_data["horses"].append({
                "name": h.name,
                "odds": h.odds,
                "odds_parsed": h.odds_parsed,
                "jockey_name": h.jockey_name,
                "jockey_win_pct": h.jockey_win_pct,
                "trainer_name": h.trainer_name,
                "trainer_win_pct": h.trainer_win_pct,
                "best_speed": h.best_speed,
                "starts": h.starts,
                "claim_price": h.claim_price,
                "past_races_count": len(h.past_races),
            })

        baseline["races"][rn] = race_data

    # Global fill rates
    baseline["global_field_rates"] = {
        f: round(global_counts[f] / global_total, 3) if global_total else 0.0
        for f in field_checks
    }

    # Race info
    baseline["race_info"] = {
        rn: {
            "distance": engine.race_info[rn].get("distance", ""),
            "distance_f": engine.race_info[rn].get("distance_f", 0.0),
            "claim_price": engine.race_info[rn].get("claim_price", 0),
            "purse": engine.race_info[rn].get("purse", 0),
        }
        for rn in engine.race_info
    }

    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)

    print(f"\n[+] Baseline saved -> {output_path}")
    print(f"    {baseline['total_races']} races, {baseline['total_horses']} horses")
    print("\n  Global fill rates:")
    for field, rate in baseline["global_field_rates"].items():
        flag = "  <-- WARNING" if rate < 0.80 else ""
        print(f"    {field:<25} {rate:.1%}{flag}")


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else "prx0422y.pdf"
    out = sys.argv[2] if len(sys.argv) > 2 else "tests/baselines/prx0422y_baseline.json"
    create_baseline(pdf, out)
