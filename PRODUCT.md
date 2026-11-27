# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are solo developers and small teams who run AI coding agents against real repositories and need a shared project memory fabric plus an Implement control plane. They are not ops/admin operators or end customers of the agents' output.

## Product Purpose

Loom OS weaves multiple AI coding agents into one shared, Graphify-powered knowledge graph per project. Agents communicate through the filesystem (inbox drops); a Next.js dashboard is the control plane. The Loom Coding Agent surface lets users chat with a graph-grounded agent, accept suggestions, and Implement work in isolated git worktrees with budgets, cancel, and reviewable diffs.

Success: a developer can go from intent → Implement → done worktree diff without leaving the Agent surface, with clear cost and cancel control.

## Positioning

The durable differentiator is the filesystem protocol plus per-project Graphify knowledge graph — agents need no SDK or API client. Neighboring "another chat UI for coding agents" products cannot truthfully claim shared memory woven from inbox findings and multi-agent registration without that fabric.

## Operating Context

- Local daemon on `127.0.0.1:8472` (REST + WebSocket) and dashboard on `:3000`
- Optional macOS DMG wraps the same stack for desktop launch
- Projects are git repos; Implement runs in `loom/task-<id>` worktrees
- BYOK chat models configured in Agent settings (DeepSeek / OpenAI-compatible and similar)
- Pattern families (ReAct, Plan-then-Execute, TDD, Debug, Review-only, …) with optional "Let agent decide"
- Dashboard locales: English (default) and Arabic (RTL)

## Capabilities and Constraints

- Filesystem inbox protocol (`register`, `heartbeat`, findings, decisions, tasks)
- Graph-grounded Loom Agent chat; Accept / Dismiss / Implement flows
- Coding Agent ReAct (and related) tool loop with budgets and cancel
- Pattern selection UX and autonomy settings
- Must preserve: filesystem protocol, graph grounding, worktree isolation, pattern selection / "Let agent decide", BYOK
- Undecided: none recorded beyond existing codebase behavior

## Brand Commitments

- Product name: **Loom OS**; Coding Agent surface / app: **Loom Coding Agent**
- Package/CLI naming: `loom-os` / `loom` (repo historically `agentic-os`)
- Primary Warp Loom icon: `docs/branding/loom-icon-warp-512.png` (and related sizes)

## Evidence on Hand

- Runnable dashboard Agent app (`dashboard/app/[locale]/agent-app`, chat, settings, Implement picker)
- Design/plan docs under `docs/superpowers/` and `coding_agent/README.md`
- Branding assets under `docs/branding/`
- No fabricated testimonials, benchmarks, or customer claims — future work must not invent them

## Product Principles

1. Agents integrate through the filesystem, not proprietary SDKs.
2. Project memory is shared and graph-backed; chat and Implement stay grounded in that graph.
3. Execution is isolated (worktrees), budget-capped, and cancellable.
4. The developer stays in control of accept → implement → review.
5. Local-first control plane: daemon + dashboard, BYOK models.

## Accessibility & Inclusion

Dashboard supports English and Arabic (RTL). No additional product-specific accessibility standard was confirmed beyond existing web practices in the dashboard.
