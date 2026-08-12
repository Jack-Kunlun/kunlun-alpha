# Precious-Metals Funds Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exchange-listed precious-metals ETFs/funds to every authoritative Kunlun Alpha planning artifact while keeping spot, futures, margin, rollover, and delivery out of scope.

**Architecture:** Extend the existing exchange-listed `Instrument` and fund model rather than creating a parallel commodity-trading architecture. Add four small development nodes for contracts, ingestion, research/backtesting, and terminal presentation, then regenerate and structurally verify the Word handbook.

**Tech Stack:** Markdown, Python, python-docx, UTF-8, LF.

## Global Constraints

- Include exchange-listed gold and provider-identifiable silver-related ETFs/funds.
- Do not include physical bullion, OTC/spot trading, commodity futures, margin, rollover, or delivery.
- Preserve Phase 0–6 real-order prohibition and Phase 7 approval gates.
- Add `P1-N13`, `P1-N14`, `P5-N14`, and `P6-N13` without renumbering existing nodes.
- Update the master total from 94 to 98 nodes.
- Preserve UTF-8 and LF in all text files.

---

### Task 1: Synchronize Markdown planning and agent instructions

**Files:**

- Modify: `docs/superpowers/specs/2026-08-11-kunlun-alpha-master-plan-design.md`
- Modify: `docs/superpowers/plans/2026-08-11-kunlun-alpha-master-implementation-plan.md`
- Modify: `AGENTS.md`

**Interfaces:**

- Consumes: `docs/superpowers/specs/2026-08-11-precious-metals-funds-design.md`.
- Produces: consistent product scope, domain semantics, safety boundary, and agent instructions.

- [ ] Add the precious-metals funds scope and explicit exclusions to the master design.
- [ ] Add the four node summaries and 98-node total to the master implementation plan.
- [ ] Add supported asset scope and future-expansion stop conditions to `AGENTS.md`.
- [ ] Verify required terms, LF encoding, and absence of placeholders.

### Task 2: Extend Word handbook source and node cards

**Files:**

- Modify: `work/build_kunlun_handbook.py`
- Modify: `work/audit_kunlun_handbook.py`
- Regenerate: `outputs/昆仑智策项目总体规划与分阶段实施手册.docx`

**Interfaces:**

- Consumes: the approved precious-metals design and existing 94-node handbook model.
- Produces: a 98-node handbook with updated phase counts and precious-metals sections.

- [ ] Add the four exact node cards and their file areas, deliverables, acceptance criteria, and review risks.
- [ ] Add precious-metals scope, model fields, data validation, research features, terminal behavior, and exclusions to the narrative chapters.
- [ ] Update the structural audit to expect 98 nodes and phase counts `{0:15,1:14,2:10,3:10,4:10,5:14,6:13,7:12}`.
- [ ] Rebuild the DOCX using the bundled Python runtime.
- [ ] Run ZIP integrity, required-content, unique-node, phase-count, table-geometry, and accessibility audits.
- [ ] Attempt the standard render workflow; if no renderer is installed, report that visual QA remains unavailable.
