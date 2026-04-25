"""
Horse Racing Predictive Engine — Interactive Runner
===================================================
Usage:
    python run.py

You will be prompted to:
  1. Paste the path to the race book PDF
  2. Optionally enter actual finish results after the races run

The HTML report opens automatically in your browser.
"""

import sys
import os
import io

# Fix Windows console encoding for Unicode output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Suppress INFO-level logging from components
import logging
logging.disable(logging.INFO)

from horse_racing_engine import HorseRacingEngine


# ── Helpers ───────────────────────────────────────────────────────────────

def prompt(msg: str, default: str = "") -> str:
    """Print a prompt and return stripped input."""
    if default:
        val = input(f"{msg} [{default}]: ").strip()
        return val if val else default
    return input(f"{msg}: ").strip()


def parse_finish_order(raw: str) -> list:
    """
    Parse a comma-separated finish order string into a list of horse names.
    Handles extra whitespace and empty entries.

    Example:
        "Downtown Chalybrown, Yuletide Gallop, Runandscore"
        -> ['Downtown Chalybrown', 'Yuletide Gallop', 'Runandscore']
    """
    return [name.strip() for name in raw.split(',') if name.strip()]


def print_race_summary(engine: HorseRacingEngine) -> None:
    """Print a quick summary of all parsed races."""
    print(f"\n  {'Race':<6} {'Horses':>7}  {'Distance':<12}  {'Purse':>10}  Top Pick")
    print(f"  {'-'*60}")
    for rn in sorted(engine.all_races.keys(), key=int):
        horses = engine.all_races[rn]
        info = engine.race_info.get(rn, {})
        dist = info.get('distance', '?')
        purse = f"${info.get('purse', 0):,}" if 'purse' in info else '—'
        df = engine.predict_race(rn)
        top = df.iloc[0]['Horse'] if df is not None and not df.empty else '?'
        top_prob = df.iloc[0]['Win_Prob'] if df is not None and not df.empty else 0
        print(f"  {rn:<6} {len(horses):>7}  {dist:<12}  {purse:>10}  {top} ({top_prob:.0%})")


# ── Main workflow ─────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  HORSE RACING PREDICTIVE ENGINE v4.0")
    print("=" * 60)

    # ── Step 1: Get PDF path ──────────────────────────────────────────
    print("\nStep 1: Race Book PDF")
    print("  Paste the full path to the PDF file.")
    print("  Example: C:\\Downloads\\prx0422y.pdf\n")

    while True:
        pdf_path = prompt("PDF path").strip('"').strip("'")
        if not pdf_path:
            print("  [!] No path entered. Please try again.")
            continue
        if not os.path.exists(pdf_path):
            print(f"  [!] File not found: {pdf_path}")
            retry = prompt("Try again? (y/n)", "y").lower()
            if retry != 'y':
                print("Exiting.")
                return
            continue
        break

    # ── Step 2: Parse PDF ─────────────────────────────────────────────
    print(f"\nStep 2: Parsing PDF...")
    engine = HorseRacingEngine()
    text = engine.extract_text_from_pdf(pdf_path)
    print(f"[+] Track: {engine.track_name}")

    if not text:
        print("[!] Failed to extract text from PDF. Is it a valid race book?")
        return

    engine.parse_races(text)

    if not engine.all_races:
        print("[!] No races found in PDF. Check the file format.")
        return

    print(f"\n[+] Parsed {len(engine.all_races)} races successfully.")
    print_race_summary(engine)

    # ── Step 3: Optional — enter actual results ───────────────────────
    print("\nStep 3: Actual Results (optional)")
    print("  If the races have already run, you can enter the finish order")
    print("  to see Model vs Actual comparison in the report.")
    print("  Enter horse names separated by commas, 1st place first.")
    print("  Press Enter to skip a race.\n")

    enter_results = prompt("Enter actual results? (y/n)", "n").lower()

    if enter_results == 'y':
        for rn in sorted(engine.all_races.keys(), key=int):
            horses = engine.all_races[rn]
            info = engine.race_info.get(rn, {})
            dist = info.get('distance', '?')
            print(f"\n  Race {rn} ({dist}, {len(horses)} horses):")
            for h in horses:
                print(f"    PP{h.pp_rank}  {h.name}")

            raw = prompt(f"  Finish order for Race {rn} (comma-separated, or Enter to skip)")
            if raw.strip():
                order = parse_finish_order(raw)
                if order:
                    engine.add_results(rn, order)
                    print(f"  [+] Recorded: {', '.join(order[:3])}{'...' if len(order) > 3 else ''}")

    # ── Step 4: Generate HTML report ─────────────────────────────────
    print("\nStep 4: Generating HTML report...")

    # Derive output path from PDF path
    pdf_stem = os.path.splitext(os.path.basename(pdf_path))[0]
    default_out = os.path.join(os.path.dirname(pdf_path), f"{pdf_stem}_predictions.html")
    out_path = prompt("Output HTML path", default_out)

    engine.export_html(output_path=out_path, auto_open=True)

    print("\n" + "=" * 60)
    print("  Done! Report opened in your browser.")
    print(f"  Saved to: {out_path}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
