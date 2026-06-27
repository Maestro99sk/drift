# Drift - Adaptive Dropshipping Engine

> **The moat is loop velocity and kill discipline, not product discovery.**

Drift continuously detects trending products, checks whether they can be sourced reliably
and at a margin, assembles a Claude-generated dossier, lets a human approve, and then
publishes a niche-styled storefront, launches ads, monitors ROAS, and rotates to the
next candidate when one cools.

See [CLAUDE.md](./CLAUDE.md) for the full design contract.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env       # fill in what you have; missing keys disable their layer
python -m drift.cli init   # create DB
python -m drift.cli loop   # run one tick of the orchestrator
python -m drift.cli dashboard   # streamlit review UI on :8501
```

Run mock mode end to end (no keys needed):

```bash
MOCK_MODE=true python -m drift.cli loop
MOCK_MODE=true python -m drift.cli dashboard
```

## Which env var unlocks which layer

| Layer | Env var(s) | Without it |
|------|-----------|-----------|
| Signals (live) | `SERPAPI_KEY` *or* pytrends (free) | Falls back to mock if `MOCK_SIGNALS=true` |
| Sourcing | `CJ_API_KEY` | Layer dormant unless mocked |
| LLM dossier | `ANTHROPIC_API_KEY` | Layer dormant unless mocked |
| Storefront | `SHOPIFY_ADMIN_TOKEN`, `SHOPIFY_STORE_DOMAIN` | Dormant |
| Ads (Meta) | `META_MARKETING_TOKEN`, `META_AD_ACCOUNT_ID` | Dormant |
| Ads (TikTok) | `TIKTOK_MARKETING_TOKEN`, `TIKTOK_ADVERTISER_ID` | Dormant |
| Fulfilment | `CJ_API_KEY` + ad sale event | Dormant |

Each layer is gated by a feature-flag + credential check (section 8 of CLAUDE.md). The instant
a credential lands, that layer wakes up - no code change.

## Tests

```bash
pytest -q
ruff check .
black --check .
mypy drift
```
