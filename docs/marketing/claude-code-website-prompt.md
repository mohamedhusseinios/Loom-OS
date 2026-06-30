# Claude Code prompt — wire mabdulrahman.com into the Loom OS funnel

> Run this inside your **website repo** (not the Loom repo). Optionally copy `loom-landing.html`
> into the repo first so Claude Code can use it as a visual/content reference for the /loom page.

---

You are working in the repository for my personal site **mabdulrahman.com**. Goal: turn the site into the marketing + lead-gen funnel for my product **Loom OS** (a local-first, multi-agent memory fabric for developers). I sell it as done-for-you services; the site must drive visitors to **book a 30-minute teardown call**.

## Step 0 — Explore before you change anything
First, read the repo and report back briefly what you find, then proceed:
- Framework + router (Next.js App or Pages?), styling system (Tailwind / CSS modules / styled-components?), and how pages/components are organized.
- How the **blog** works (MDX files? a CMS? frontmatter shape?) and how existing pages set metadata/OG tags.
- Existing design tokens, fonts, header/nav, and reusable UI components.
Match all of these conventions exactly. Do **not** introduce a new styling system or break existing pages (Home, Blog, Broadcast, AI News). Work on a new branch `feat/loom-funnel`. At the end, run the project's lint/typecheck/build and fix any errors you introduced.

## Brand & voice
- Loom OS brand: monochrome/geometric. Ink `#141414`, Paper `#FFFFFF`, greys `#6F6F6F` and `#E5E5E5`; display font **Space Grotesk** (tight tracking ~-3.5%). Reuse my site's existing font for body if it differs.
- Voice: senior developer, local-first, "allergic to cloud vendor lock-in", ship-products-not-just-code. Confident, concrete, no hype.
- Core hook: **"Own your agents' memory. Don't rent it."**
- Sub: *Loom OS gives Claude Code, Codex, Cursor, and your in-house agents one shared knowledge graph per project — running on your machine. No SDK, no cloud, no vendor lock-in.*
- Links to reuse: GitHub `https://github.com/mohamedhusseinios/Loom-OS`, email `hello@mabdulrahman.com`.

## Step 1 — Shared plumbing
- Add env vars `NEXT_PUBLIC_BOOKING_URL` (my Cal.com link) and `NEXT_PUBLIC_DEMO_URL` (demo video). Add them to `.env.example` with comments. Anywhere a real value is missing, render the button/embed but point to a clearly-marked `#` placeholder — never crash the build.
- Create a reusable `BookingButton` component (label default: "Book a 30-min teardown →") that links to `NEXT_PUBLIC_BOOKING_URL`, and a `DemoEmbed` component that embeds `NEXT_PUBLIC_DEMO_URL` (responsive 16:9; graceful placeholder if unset).
- Add a **"Book a teardown"** primary CTA to the site header/nav on every page.

## Step 2 — Homepage: make Loom OS the flagship
Without deleting my existing content, restructure the homepage so **Loom OS is the featured product**:
- Add a prominent Loom hero/feature block near the top: the hook + sub above, a `BookingButton` (primary) and a "View on GitHub" secondary button, and a one-line trust strip: *MIT-licensed · single process (no Docker, no Neo4j) · runs 100% local*.
- Promote Loom to the top of the "What I'm Building" / "Featured Work" area with a link to `/loom`.
- Keep Blog, Broadcast, AI News intact.

## Step 3 — New `/loom` page (product + services landing)
Create a dedicated route `/loom` implementing the full landing page below (if `loom-landing.html` is in the repo, use it as the design/content source of truth and port it into my component system; otherwise build from this spec). Responsive, accessible, on-brand. Sections:
1. **Hero** — hook + sub + `BookingButton` + GitHub button + trust strip.
2. **Problem** — "Your team runs five coding agents. None of them share a brain." 1–2 sentences on context scattering across tools and being locked inside a vendor's product.
3. **How it works** — 6 feature cards:
   - Filesystem inbox — any agent connects by writing a file. Zero SDK, zero auth.
   - Single-process daemon — `pip install` and run. No Docker, Neo4j, external DB, or cloud.
   - Code-aware graph — parses your codebase AST (files, functions, classes, call flows), enriched by what agents learn.
   - Dashboard control plane — browse the graph, watch agents live, search, dispatch work.
   - MCP + hybrid search — an MCP server plus graph+vector+relational search in one call.
   - Sandboxed task board — dispatch tasks that run in isolated git worktrees with a budget cap; review the diff, then merge.
   - Include a `DemoEmbed` after the cards.
4. **Who it's for** — AI dev agencies · engineering teams (5–50 devs) · local-first builders.
5. **Thesis band** (inverted/dark) — "The model is now a commodity. Your context is the moat." Short paragraph: models get cheaper and interchangeable; the lock-in is the context woven around them; Loom keeps that context yours, portable across whichever models win next.
6. **Work with me** — offer ladder cards:
   - Agent workflow teardown — **Free, 30 min** (flagship CTA).
   - Workflow audit — **$2,000**, 1–2 days.
   - Setup sprint (done-for-you) — **$6k–$12k**, fixed, 1–2 weeks.
   - Support retainer — **$1.5k–$3k/mo**.
7. **About** — me: Cairo-based, 9-year developer, builds local-first AI dev tools; I built Loom OS so I set it up faster than anyone.
8. **Final CTA** — "Stop renting your context." + `BookingButton`.
- Add page `metadata` (title, description, OpenGraph/Twitter) consistent with the rest of the site; add an OG image if the site has an OG-image convention.

## Step 4 — Launch blog post
Create a new blog post following my existing blog format/frontmatter. Title (pick the stronger for my blog): **"Why I choose local AI over cloud APIs — and why I built Loom OS"** or **"Own your context: the moat moved, and your agents' memory is leaking."**
Outline:
- Models are getting cheap and interchangeable; the real lock-in is the context around them (mention how proprietary assistants quietly absorb your codebase/decisions).
- The cost of agent sprawl: every agent has its own private memory; nothing is shared; knowledge scatters.
- What "owning your context" looks like in practice — local-first, multi-agent shared memory.
- How Loom OS does it (the 6 capabilities, briefly).
- CTA: link to `/loom` and a `BookingButton`.
Keep it ~800–1,200 words, first-person, concrete. End every post/page CTA pointing to `/loom` or the booking link.

## Step 5 — Distribution hygiene
- Internal links: homepage → `/loom`, blog post → `/loom`, `/loom` → blog post.
- Update `sitemap`/`robots` (whatever the repo uses) to include `/loom` and the new post.
- Ensure the new pages are responsive and pass basic a11y (semantic headings, alt text, color contrast, focus states).

## Done criteria — report back
- A summary of every file created/changed and why.
- Confirmation that lint/typecheck/build pass.
- The two env vars I need to set (`NEXT_PUBLIC_BOOKING_URL`, `NEXT_PUBLIC_DEMO_URL`) and where.
- Screenshots or the local dev URL for the homepage, `/loom`, and the new blog post.
Do not push or deploy — leave it on the `feat/loom-funnel` branch for me to review.
