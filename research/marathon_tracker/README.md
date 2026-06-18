# Marathon Tracker

Marathon Tracker is a research project for monitoring marathon race dates and
registration deadlines around the world. It combines a curated list of official
race pages with scripts that can fetch those pages, ask an LLM to extract key
dates, and publish the latest results as a static GitHub Pages site.

## What it tracks

For each race, the tracker stores:

- race name
- city, country, and region
- official race URL
- event date
- registration open date
- registration deadline
- lottery deadline
- qualification deadline
- source URL and extraction timestamp
- confidence level and notes

The seed race list is in `config/races.json`. Add or remove races there.

## Run locally

```bash
cd research/marathon_tracker
python3 -m marathon_tracker.update --no-network
```

That command renders the current seed data to:

- `docs/marathons.json`
- `docs/index.html`

To fetch current official pages:

```bash
python3 -m marathon_tracker.update
```

## Optional LLM extraction

The updater works without an LLM, but extraction is better when one is
configured. It uses an OpenAI-compatible chat completions endpoint.

```bash
export LLM_API_KEY="..."
export LLM_MODEL="gpt-4.1-mini"
python3 -m marathon_tracker.update
```

Optional variables:

- `LLM_API_BASE`, default `https://api.openai.com/v1`
- `LLM_MODEL`, default `gpt-4.1-mini`
- `LLM_TIMEOUT_SECONDS`, default `45`

If no `LLM_API_KEY` is present, the script uses a conservative regex-based
fallback and marks those fields with lower confidence.

## Publish with GitHub Pages

The workflow in `.github/workflows/marathon-tracker.yml` runs weekly and on
manual dispatch. It updates `research/marathon_tracker/docs`, commits changed
results back to the repository, and uploads the folder as a GitHub Pages
artifact.

Repository setup required in GitHub:

1. Enable GitHub Pages.
2. Select "GitHub Actions" as the Pages source.
3. Add `LLM_API_KEY` as a repository secret if LLM extraction should run in CI.

Without the secret, the workflow still refreshes pages using deterministic
fallback extraction.

