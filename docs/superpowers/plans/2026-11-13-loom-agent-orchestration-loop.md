# Loom Agent + Jev Orchestration Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a dashboard Loom agent with DeepSeek (BYOK) + Jev orchestration over project graph memory: chat, suggest next steps for Accept/Dismiss, Implement via existing worker.

**Architecture:** Daemon owns `orchestrator` (graph → Jev filter → LLM → Jev choice), `agent_runtime` (chat/suggest/implement), and SQLite tables for settings/chats/suggestions. Dashboard chats and shows suggestion chips. Implement assigns `loom-agent` and uses `loom worker` worktrees.

**Tech Stack:** FastAPI, aiosqlite, httpx/urllib for TypeSafe + DeepSeek, Next.js dashboard, pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-loom-agent-orchestration-loop-design.md`

## Global Constraints

- Human-in-the-loop: no side effects until Accept / Implement
- Jev is System One only (`POST /v1/systemone`); never used as chat
- Graph context via `hybrid_query`; empty graph must not invent facts
- Keys stay on daemon; GET settings masks API keys
- Default main model: `deepseek-chat` at `https://api.deepseek.com`
- i18n: add strings to both `en` and `ar`

## Review Focus

- Missing API key → clear 400, not a 500
- Jev 429/timeout → degrade with `jev_skipped`, chat still works
- Stale Accept after status change → 409
- Second auto-suggest while pending → no duplicate pending rows
- Uncited LLM candidates → dropped from catalog

---

### Task 1: Registry tables + models

**Files:**
- Modify: `daemon/models.py`, `daemon/registry.py`
- Test: `tests/test_agent_orchestrator_registry.py`

- [ ] Add Pydantic models for settings, chat, message, suggestion
- [ ] Create tables in `initialize()` + CRUD helpers
- [ ] Tests for settings mask, single pending suggestion, chat messages

### Task 2: Jev + LLM clients

**Files:**
- Create: `daemon/jev_client.py`, `daemon/llm_client.py`
- Test: `tests/test_jev_llm_clients.py`

- [ ] `JevClient.ask(state, questions, model="jev-latest") -> answers`
- [ ] `LlmClient.chat(messages, model, api_key, base_url) -> str`
- [ ] Mocked HTTP unit tests

### Task 3: Orchestrator

**Files:**
- Create: `daemon/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] `run_suggest_cycle(...)` implements graph → filter → LLM → choice
- [ ] Empty graph + catalog merge + jev_skipped paths tested

### Task 4: Agent runtime + API

**Files:**
- Create: `daemon/agent_runtime.py`
- Modify: `daemon/api.py`
- Test: `tests/test_agent_api.py`

- [ ] Chat / suggest / accept / dismiss / implement / settings routes
- [ ] WS events `agent:message`, `task:suggestion`
- [ ] Auto-suggest hook on status transitions with cooldown

### Task 5: loom-agent registration + runner

**Files:**
- Modify: `daemon/known_agents.py`, `daemon/runners.py`
- Create: `daemon/agent_run.py` (worktree execution entry)
- Test: `tests/test_loom_agent_runner.py`

### Task 6: Dashboard UI

**Files:**
- Create: `dashboard/components/loom-agent-chat.tsx`, `suggestion-chip.tsx`, `agent-settings-panel.tsx`
- Modify: tasks page, `lib/api.ts`, `messages/en.json`, `messages/ar.json`

### Task 7: Verify

- [ ] `pytest tests/test_agent_orchestrator_registry.py tests/test_jev_llm_clients.py tests/test_orchestrator.py tests/test_agent_api.py tests/test_loom_agent_runner.py -v`
- [ ] Full suite smoke + `cd dashboard && npm run lint`
