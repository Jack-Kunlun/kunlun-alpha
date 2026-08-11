# Kunlun Alpha AGENTS.md Design

## Purpose

Create a repository-root `AGENTS.md` that gives Codex, WorkBuddy, and other coding agents a concise, durable operating contract for Kunlun Alpha. The file must be self-contained enough to guide routine work while linking to the approved detailed plan instead of duplicating all 94 development nodes.

## Scope and precedence

- The root file applies to the entire repository.
- Future directory-level `AGENTS.md` or `AGENTS.override.md` files may add stricter local rules.
- Explicit user instructions take priority, followed by the closest applicable agent instructions, approved project documents, and established code conventions.
- No lower-level file may weaken the live-trading safety rules.

## Required content

The root `AGENTS.md` will contain:

1. Project identity, mission, current stage, and non-goals.
2. Authoritative documents agents must read before implementation.
3. WorkBuddy implementation and Codex review responsibilities.
4. One-node-at-a-time task boundaries.
5. Inspect, plan, TDD, implement, verify, document, report workflow.
6. Definition of Done and required evidence packet.
7. Monorepo boundaries and dependency direction.
8. TypeScript, Python, API, data, time, precision, and versioning rules.
9. React and shadcn/ui requirements.
10. UTF-8, LF, EditorConfig, Git attributes, and three-platform compatibility.
11. Testing, commits, dependency upgrades, migrations, and documentation rules.
12. Secrets, privacy, external data, LLM output, and supply-chain security.
13. Phase 0–6 real-trading prohibition.
14. Phase 7 QMT, risk, reconciliation, approval, and fail-closed requirements.
15. Stop-and-ask conditions.
16. Repository-wide code-review rules.

## Agent workflow

For each task, an agent must:

1. Identify the requested node and its exact boundary.
2. Read the approved plan, direct dependencies, and affected code.
3. Inspect the worktree and preserve user changes.
4. State a focused implementation plan.
5. Write and run a failing test or validation fixture.
6. Implement the smallest change that satisfies the node.
7. Run formatting, static analysis, narrow tests, affected tests, and build checks.
8. Review security, cross-platform, architecture, and documentation impacts.
9. Return a complete evidence packet and stop for review.

If no node ID is provided, the agent should map the request to the smallest matching node. It asks only when the mapping or authority would materially change the outcome.

## Hard safety constraints

- Phase 0–6 must have no callable path that places a real broker order.
- Phase 7 defaults to simulation. Real-account access requires explicit, separate approval and all documented gates.
- Strategies produce `Signal` or `OrderIntent`; they never call a broker.
- Risk failures are fail-closed. Reconnect requires reconciliation before order flow resumes.
- Agents must stop on discovered credential exposure, irreversible data risk, unexplained reconciliation differences, or live-trading bypasses.

## File format and platform constraints

- Text files use UTF-8 and LF except explicit Windows `.bat`/`.cmd` files.
- Root `.editorconfig` and `.gitattributes` are mandatory and enforced.
- Code and scripts support Windows, macOS, and Linux.
- Platform paths, drive letters, home directories, `/tmp`, and shell-specific assumptions are not hard-coded.

## Review model

WorkBuddy implements one node and returns evidence. Codex reviews requirement coverage, architecture, types, data correctness, testing, security, cross-platform behavior, UI quality, operations, and scope discipline. A node may proceed only after blocking findings are resolved.

## Size and maintainability

- Target size is approximately 8–12 KB and must remain below Codex's default combined project-instruction limit.
- Detailed node cards stay in the approved implementation handbook.
- Future specialized rules belong near the code they govern.
- Formatting preferences already enforced by automated tooling are referenced briefly rather than repeated verbosely.

## Acceptance criteria

- Root `AGENTS.md` exists and is readable as UTF-8 with LF endings.
- It links the approved Markdown design, Markdown implementation plan, and Word handbook.
- It contains no placeholders or contradictory instructions.
- It states the single-node workflow, evidence contract, shadcn/ui requirement, three-platform policy, and live-trading red lines.
- Its size stays below 32 KiB.
