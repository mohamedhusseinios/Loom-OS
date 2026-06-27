# Dashboard Guide

Built with Next.js 16 (App Router, React 19), Shadcn UI, Tailwind v4, and a dark theme. Routes are locale-segmented under `/[locale]/` (English default, Arabic with RTL).

## Pages

| Route | Screen | What it shows |
|-------|--------|---------------|
| `/[locale]` | Project Overview | Cards for all tracked projects with node/edge/community counts and active-agent badges; add/remove projects |
| `/[locale]/projects/[id]` | Project Detail | Graph stats, agent list with status dots, live activity feed |
| `/[locale]/projects/[id]/graph` | Graph Explorer | Interactive Cytoscape graph (topology, community filter, flow highlighting, node detail) + natural language query |
| `/[locale]/projects/[id]/agents` | Agent Management | Agent wiring, task dispatch, and dispatch history |
| `/[locale]/projects/[id]/tasks` | Task Board | Kanban board (Todo · Ready · Running · Blocked · Done) with drag-and-drop |

## Tech Stack

- **Framework:** Next.js 16 App Router, React 19
- **UI:** Shadcn v4 (components in `components/ui/`), Tailwind v4, `@base-ui/react`
- **Icons:** `lucide-react`
- **Graph:** `cytoscape` + `cytoscape-cose-bilkent` layout
- **i18n:** `next-intl` 4 (locales: `en`, `ar`; RTL for Arabic)

## Internationalization

next-intl drives localization. Locales (`en`, `ar`) live in the URL path; the locale-negotiation middleware is `proxy.ts` (renamed from `middleware.ts` in Next 16). Translation bundles are `messages/en.json` and `messages/ar.json` — add UI strings to both. Arabic renders right-to-left with an Arabic-capable font.

## Live Updates

A single shared `WebSocketProvider` (`lib/use-websocket.tsx`) opens one `ws://localhost:8472/ws` connection for the whole app and fans events out to subscribers keyed by event type (e.g. `agent:dispatched`) or `project:<id>`. Never open sockets per-component — call `useWebSocket()` and `subscribe(...)`.

## Component Map

```
components/
├── ui/                          # shadcn primitives (button, card, badge, dialog, select, …)
├── graph-canvas.tsx             # Cytoscape graph renderer
├── graph-canvas-reagraph.tsx    # Alternative Reagraph renderer
├── graph-controls.tsx           # Graph filter/zoom controls
├── node-detail.tsx              # Node detail panel
├── agent-card.tsx               # Agent card component
├── agent-wiring.tsx             # Agent wiring UI
├── dispatch-modal.tsx           # Task dispatch modal
├── dispatch-history.tsx         # Dispatch history list
├── project-card.tsx             # Project overview card
├── task-card.tsx                # Task card for Kanban board
├── task-detail.tsx              # Task detail drawer
├── task-board.tsx               # Kanban board layout
└── discover-dialog.tsx          # Filesystem project discovery dialog
```

## Development

```bash
cd dashboard
npm install
npm run dev      # hot-reload dev server (localhost:3000)
npm run build    # production build
npm run lint     # eslint
```

> **Next.js 16 / React 19:** this is newer than most training data. `dashboard/AGENTS.md` instructs reading the relevant guide in `dashboard/node_modules/next/dist/docs/` before writing dashboard code — APIs and file conventions (e.g. `middleware.ts` → `proxy.ts`) have changed.

## Styling

- **Theme:** Dark by default
- **Colors:** Ink `#141414` · Paper `#FFFFFF` · greys `#6F6F6F`, `#E5E5E5`
- **Typography:** Space Grotesk 600 for the wordmark, tracking −3.5%
- **Branding:** See [`docs/branding/README.md`](branding/README.md) for full logo kit and usage specs
