# Long-Term Plan

## Recommendation

Use **Vercel + Neon** as the main direction.

Streamlit is excellent for a quick private Python dashboard, but the long-term goal is bigger than displaying parser output. The project needs to test features, compare model versions, store predictions and actual results, evaluate edge, and eventually make better decisions from historical data. That points toward a real app plus database.

Build a **Next.js app on Vercel**, backed by **Neon Postgres**, while keeping the current Python engine as the scoring and parser layer for now.

## Why Vercel + Neon

- Vercel is already available through a paid account.
- Neon is already available and is a good fit for relational racing data.
- Vercel gives preview deployments, app UI, API routes, cron jobs, auth options, and a path to production.
- Neon fits the core data model: races, horses, entries, features, predictions, results, odds snapshots, and model runs.
- Vercel Marketplace supports Neon and can inject environment variables into projects automatically.
- Vercel supports Python Functions, but the Python runtime is still a less certain choice for heavy PDF parsing and model work, so keep that workload separate at first.

## When Streamlit Still Helps

Use Streamlit only as a short-term internal lab if the goal is to explore ideas quickly in Python.

Streamlit is useful for:

- Rapid feature exploration.
- Quick model diagnostics.
- Internal charts and backtest views.
- One-off experiments before building polished product UI.

Do not make Streamlit the long-term product surface unless the project stays a private analyst tool.

## Database Choice

Use **Neon Postgres**.

Start with these core tables:

- `race_cards`: source PDF, track, date, race count.
- `races`: race metadata, distance, purse, surface, conditions.
- `horses`: normalized horse identity.
- `entries`: one horse in one race, odds, jockey, trainer, post position.
- `features`: frozen feature values used by a model run.
- `model_runs`: model version, weights, timestamp, notes.
- `predictions`: win probability, rank, score, value flags.
- `results`: actual finish order, payouts if available.
- `odds_snapshots`: morning line, live odds, closing odds if collected.

Do not store PDFs or generated HTML in Postgres. Store files in Vercel Blob, S3, or local sample storage, and put only file URLs and metadata in Neon.

## Build Plan

1. Keep the current Python parser and model working.
2. Add a small CLI or API path that writes parsed races, features, predictions, and results into Neon.
3. Build a Vercel dashboard for uploading or selecting PDFs.
4. Add parsed race views with editable corrections.
5. Add model comparison views for feature weights, versions, and prediction outputs.
6. Add actual result entry and automated backtesting.
7. Track ROI, hit rate, top-three accuracy, value-bet performance, and closing-line value.
8. Later, decide whether Python remains a worker service or whether scoring moves into the web app.

## First Milestone

The first useful milestone is not a public app. It is an internal research dashboard that answers:

- Which features are consistently populated from the PDFs?
- Which features correlate with actual results?
- Which model versions outperform the baseline?
- Which predictions would have produced positive expected value?
- Where does the parser fail often enough to distort the model?

Once those questions are measurable, the product direction becomes much clearer.

