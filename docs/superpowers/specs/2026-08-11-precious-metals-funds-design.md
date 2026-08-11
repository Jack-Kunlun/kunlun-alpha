# Kunlun Alpha Precious-Metals Funds Extension Design

## Decision

Kunlun Alpha will include exchange-listed precious-metals ETFs and funds in the first platform scope. The initial design supports gold products and any silver-related exchange-listed products that can be identified and supplied by an approved market-data provider.

The extension does not include physical bullion, OTC spot contracts, Shanghai Gold Exchange member trading, commodity futures, margin trading, contract rollover, or physical delivery. Those are separate future asset-class projects.

## Product scope

Supported capabilities:

- instrument discovery and classification;
- exchange trading calendar and trading-status handling;
- OHLCV and amount data;
- fund NAV/iNAV when available from an approved provider;
- premium/discount, tracking difference, liquidity, turnover, and spread-oriented features;
- event and hotspot mapping for gold, silver, precious metals, inflation, rates, currency, and risk-off themes;
- research, backtesting, ranking, watchlists, alerts, and paper portfolios;
- QMT execution only in Phase 7 under the existing live-trading gates.

Explicitly excluded:

- direct spot gold or silver orders;
- leveraged or margined commodity positions unless separately designed and approved;
- futures contract chains, continuous contracts, dominant-contract switching, and rollover;
- delivery, warehouse receipt, purity, assay, storage, and logistics processes;
- automatic currency or macro hedging.

## Domain model

Keep the existing `Instrument` abstraction and add fund-specific classification rather than creating a parallel precious-metals instrument hierarchy.

Required semantics:

- `assetType`: existing exchange-listed fund/ETF value;
- `fundAssetClass`: `PRECIOUS_METALS`;
- `underlyingCommodity`: `GOLD`, `SILVER`, or `OTHER`;
- `tradingCurrency` and `navCurrency`;
- `benchmarkOrTrackingIndex`;
- `managementFeeRate` and other available recurring fees;
- `nav`, `iNav`, `premiumDiscountRate`, and their source/availability time;
- `lotSize`, price-limit rule, listing status, and trading status inherited from the exchange instrument model;
- effective dates and source provenance for every classification field.

Unknown or provider-unsupported fields remain explicitly unavailable. They must not be guessed from product names.

## Data flow

Precious-metals funds use the existing Provider pipeline:

`Provider -> raw object -> normalization -> validation -> deduplication -> storage -> features -> terminal`.

Add provider capabilities for fund metadata, NAV/iNAV, benchmark metadata, and fee information. Preserve raw payloads and capture `publish_time`, `ingest_time`, and `available_time` so research never uses a NAV or classification revision before it was available.

Validation includes:

- legal exchange symbol and lot size;
- non-negative NAV/iNAV and fees;
- currency consistency;
- premium/discount formula checks;
- stale NAV/iNAV detection;
- missing benchmark and commodity classification warnings;
- duplicate or conflicting provider records.

## Research and backtesting

Add versioned precious-metals fund features:

- return and volatility windows;
- turnover and liquidity;
- NAV premium/discount and persistence;
- tracking difference/error when the necessary benchmark series is available;
- spread proxy when reliable bid/ask data exists;
- sensitivity to gold/silver benchmark, RMB exchange rate, rates, inflation, and risk-off events only when point-in-time source data exists.

Backtesting continues to use exchange-listed fund trading rules. It must not simulate futures margin, rollover, delivery, or spot settlement. NAV and iNAV are research/reference data, not assumed executable prices.

## Intelligence and terminal

Extend topic mapping and entity resolution with precious-metals concepts, commodity aliases, fund names, and benchmark identifiers.

The terminal adds a precious-metals funds view with:

- product list and classification;
- price, turnover, liquidity, NAV/iNAV freshness, and premium/discount;
- gold/silver and macro-event timeline;
- related fund ranking and comparison;
- explicit missing-data and stale-data states;
- evidence, data timestamp, provider, and feature version.

The UI uses existing shadcn/ui primitives and the shared chart adapter.

## Development-node changes

Add four nodes without renumbering existing nodes:

- `P1-N13`: define precious-metals fund classification and contracts;
- `P1-N14`: ingest, validate, store, and monitor metadata and NAV/iNAV;
- `P5-N14`: implement point-in-time precious-metals fund features and backtest fixtures;
- `P6-N13`: build the precious-metals funds terminal view and alerts.

The master plan increases from 94 to 98 nodes. Phase counts become:

- Phase 0: 15
- Phase 1: 14
- Phase 2: 10
- Phase 3: 10
- Phase 4: 10
- Phase 5: 14
- Phase 6: 13
- Phase 7: 12

## Safety and future expansion

Phase 0–6 remains simulation and research only. Phase 7 may route exchange-listed fund orders through QMT only after all existing risk, reconciliation, approval, and small-capital gates pass.

Adding physical bullion, spot contracts, futures, margin, rollover, or delivery requires a separate approved design, implementation plan, asset-specific risk engine changes, and broker/exchange capability review.

## Acceptance criteria

- All authoritative planning artifacts explicitly include exchange-listed precious-metals ETFs/funds.
- Spot, futures, margin, rollover, and delivery remain explicitly out of scope.
- The four new node cards have unique IDs, focused scope, tests, acceptance criteria, and review risks.
- The Word handbook reports 98 unique nodes and the updated per-phase counts.
- `AGENTS.md` states the supported precious-metals fund scope and future-expansion boundary.
- The regenerated DOCX passes structural integrity, node-count, required-content, and table-geometry checks.
