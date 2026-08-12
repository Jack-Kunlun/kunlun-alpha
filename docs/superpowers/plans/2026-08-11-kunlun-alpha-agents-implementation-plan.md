# Kunlun Alpha AGENTS.md Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a repository-root `AGENTS.md` that consistently directs Codex, WorkBuddy, and other coding agents working on Kunlun Alpha.

**Architecture:** Keep universal, safety-critical instructions in the root file and link to the approved detailed planning artifacts. Allow future directory-level files to add stricter local rules without weakening repository-wide safety constraints.

**Tech Stack:** Markdown, UTF-8, LF, Git project instructions.

## Global Constraints

- The file applies to the entire repository.
- It must remain below 32 KiB and use UTF-8 with LF endings.
- It must cover the single-node workflow, TDD, evidence, shadcn/ui, three-platform support, and live-trading red lines.
- It must not duplicate all 94 node cards or contain placeholders.
- No local override may weaken real-trading safety requirements.

---

### Task 1: Create and verify root agent instructions

**Files:**

- Create: `AGENTS.md`
- Read: `docs/superpowers/specs/2026-08-11-kunlun-alpha-agents-design.md`
- Read: `docs/superpowers/plans/2026-08-11-kunlun-alpha-master-implementation-plan.md`
- Reference: `outputs/昆仑智策项目总体规划与分阶段实施手册.docx`

**Interfaces:**

- Consumes: approved project design, master implementation plan, and handbook.
- Produces: repository-wide persistent instructions loaded by compatible coding agents.

- [ ] **Step 1: Verify the file does not already exist**

Run: `Test-Path AGENTS.md`

Expected: `False`. If it exists, preserve its content and merge instead of overwriting.

- [ ] **Step 2: Create the root instruction file**

Write the approved sections: project identity, authoritative sources, roles, workflow, architecture, coding standards, testing, frontend, cross-platform rules, security, live-trading gates, evidence packet, stop conditions, and code-review rules.

- [ ] **Step 3: Verify required instructions**

Run a content check for `WorkBuddy`, `Codex`, `shadcn/ui`, `end_of_line`, `Windows`, `macOS`, `Linux`, `Phase 0`, `Phase 7`, `QMT`, `Kill Switch`, and `Code Review Rules`.

Expected: every term exists.

- [ ] **Step 4: Verify encoding, line endings, size, and placeholders**

Run a byte-level check.

Expected: valid UTF-8, at least one LF, zero CRLF sequences, file size below 32768 bytes, and no `TBD`, `TODO`, or incomplete markers.

- [ ] **Step 5: Review instruction consistency**

Confirm explicit user requests have precedence, local files can only add stricter rules, and no instruction allows Phase 0–6 real trading or Phase 7 live access without separate approval.

- [ ] **Step 6: Commit when a Git repository exists**

```powershell
git add -- AGENTS.md docs/superpowers/specs/2026-08-11-kunlun-alpha-agents-design.md docs/superpowers/plans/2026-08-11-kunlun-alpha-agents-implementation-plan.md
git commit -m "docs: add Kunlun Alpha agent instructions"
```

If the directory is not a Git repository, report that the commit step was skipped.
