# Loom — Brand Assets

Monochrome, geometric. Two logo directions; **Warp** is the primary.

## Directions
- **Warp** — the letter L woven on a loom (two warps, two wefts, interlaced). Primary mark.
- **Lattice** — an L traced through a knowledge graph (nodes + edges, converging on a hub).

## Files
| File | Use |
|------|-----|
| `loom-mark-warp.svg` / `-white.svg` | Icon mark, transparent (dark / light bg) |
| `loom-icon-warp.svg` | App-icon tile (rounded, dark bg, white mark) |
| `loom-lockup-warp.svg` | Mark + "Loom" wordmark |
| `loom-mark-lattice*.svg`, `loom-icon-lattice.svg`, `loom-lockup-lattice.svg` | Lattice equivalents |
| `favicon.ico` | Multi-res favicon (16/32/48) — primary (Warp) |
| `favicon-warp.ico` / `favicon-lattice.ico` | Per-direction favicons |
| `apple-touch-icon.png` (180) | iOS home-screen icon |
| `icon-192.png`, `icon-512.png` | PWA / Android icons |
| `loom-icon-*-512.png`, `loom-mark-*-512.png` | Raster previews |
| `site.webmanifest` | PWA manifest |

## Specs
- **Ink** `#141414` · **Paper** `#FFFFFF` · greys `#6F6F6F`, `#E5E5E5`
- **Wordmark** Space Grotesk, weight 600, tracking −3.5%
- **Clear space** ≥ 1× the mark's stroke height on all sides.
- **Min size** mark ≥ 16px; below that prefer the favicon `.ico`.

## Wire into the Next.js dashboard
Copy `favicon.ico`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`, and
`site.webmanifest` into `dashboard/app/` (or `dashboard/public/`). Next.js App Router
auto-serves `app/favicon.ico` and `app/apple-touch-icon.png`. For the manifest, add to
`app/[locale]/layout.tsx` metadata:

```ts
export const metadata = {
  title: "Loom",
  manifest: "/site.webmanifest",
  icons: { icon: "/favicon.ico", apple: "/apple-touch-icon.png" },
};
```
