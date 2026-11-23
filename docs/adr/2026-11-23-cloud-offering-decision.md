# ADR: Cloud / Hosted Offering (Feature #6)

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** Project owner (via Loomo recommendation; owner deferred)
- **Related:** [Next Moat roadmap](../plans/2026-07-01-loom-next-moat-roadmap-implementation.md) Feature #6 / #7

## Context

Phase 3 gates on an explicit cloud decision. Competitors with large followings often ship a hosted memory product. Loom’s stated moat is local-first: single-process daemon, filesystem inbox, optional team auth, no required Docker/Neo4j/cloud. Parallel product work (Coding Agent loop, Tauri desktop shell) reinforces on-device use.

## Decision

**Option B — self-hosted-by-design.**

- Loom OS does **not** ship a managed/multi-tenant cloud offering in this phase.
- Default path stays `pip install loom-os` / `loom start` / local dashboard (and future desktop shell).
- No required Docker, Postgres, or hosted control plane.
- Positioning: agent memory and project graphs stay on the user’s machine unless they deliberately export or self-host.

## Consequences

### Positive

- Moat language stays honest and consistent with Desktop + inbox protocol.
- Avoids ops, tenancy, and compliance surface before the local product is the focus.
- Unblocks Feature #7 (MCP ecosystem tools) without waiting on cloud infra.

### Negative / accepted risk

- No “one-click hosted” parity with Mem0 / Zep / Cognee-style offerings.
- Teams that want a shared remote daemon must self-operate (existing `LOOM_AUTH_TOKEN` / remote dashboard env vars only).

### Explicit non-goals (this ADR)

- Managed SaaS, billing, or multi-tenant hosted graphs.
- Making Docker or Postgres the default install.
- Replacing the filesystem inbox with a required cloud API.

## Follow-ons

1. **Feature #7 (next):** expand MCP read-only tools (`discover_agents`, `query_temporal_facts`, `search_patterns`), tests, and MCP Registry metadata — separate implementation plan.
2. **Revisit cloud** only with a new ADR if Desktop + Coding Agent demand a team-hosted path; a future **Option A-lite** (optional Dockerfile/compose, still not default) would need its own decision.

## Alternatives considered

| Option | Summary | Why not now |
|--------|---------|-------------|
| A — ship managed | Docker/compose + optional Postgres, team-mode tenancy | Heavy vs current local roadmap; risks diluting “no Docker required” |
| A-lite — optional compose only | Deploy artifact, no SaaS | Useful later; not required to close the Phase 3 gate |
| B — self-hosted-by-design | Position paper / ADR, zero cloud code | **Chosen** |
