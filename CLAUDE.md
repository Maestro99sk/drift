# CLAUDE.md - Adaptive Dropshipping Engine ("Drift")

> Working name: **Drift**. Rename freely.
> This file is the source of truth for Claude Code. Read it fully before acting.

---

## 1. Mission

An AI-orchestrated dropshipping engine. It continuously detects trending products
from legitimate signal sources, checks whether they can be sourced reliably and at a
margin, and assembles a go/no-go **dossier** for each candidate. A human owner approves
or edits; on approval the system publishes a niche-styled storefront, launches ads, then
monitors sales + "hotness" and rotates to the next product when one saturates or cools.

One backend, many faces: a visitor from a "kids learning" ad sees a kids-learning shop;
one from a "summer fashion" ad sees a boutique. Same engine, contextual storefronts.

## 2. The one principle that governs every design decision

**The moat is loop velocity and kill discipline, not product discovery.**

By the time a product is visibly hot, competitors are already on it. We do not win by
finding magic products. We win by going signal - live - real spend data fast, and by
killing losers without sentiment. Optimise the codebase for *fast iteration* and
*automated, unemotional sunset decisions*. When in doubt, make the loop faster and the
kill criteria sharper - not the discovery cleverer.

## 3. Architecture (six layers)

1. **Signal** - ingest trends from legitimate sources, normalise into `Candidate` records.
2. **Sourcing** - match a candidate to a real supplier SKU; pull cost, ship time, reliability, stock.
3. **Scoring** - deterministic `hotness` score with a hard IP-safety gate.
4. **Dossier** - Claude generates the selling plan, copy, ad angle, projected unit economics.
5. **Execution** - owner-approved publish (storefront) + ad launch + auto-fulfilment on sale.
6. **Monitoring** - time-series of sales/ROAS/trend; rotation logic triggers sunset + next candidate.

The **only mandatory human gate** sits between Scoring/Dossier and Execution. Nothing
spends money or goes live without explicit owner approval.

## 4. Hard guardrails

- Human-in-the-loop before any spend or publish. No exceptions.
- No TikTok scraping. Official sources only.
- IP gate fails closed.
- Secrets in `.env` only.
- Compliance markers (`# COMPLIANCE TODO`) for shipping disclosure, returns, EU/UK consumer law, VAT/IOSS, EU GPSR.
- Kill discipline is code, not vibes.

## 5. Mock mode

Live is the default. `MOCK_MODE=true` (or per-layer `MOCK_SIGNALS`, `MOCK_SOURCING`,
`MOCK_LLM`, `MOCK_STOREFRONT`, `MOCK_ADS`, `MOCK_FULFILMENT`) swaps in fake adapters.
Every mock record is tagged `is_mock=true` and excluded from real metrics, ROAS, and
scoring calibration. Dashboard shows a banner whenever any layer is mocked.
