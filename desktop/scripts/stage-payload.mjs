// Stage the Loom stack sources into src-tauri/payload/ so `tauri build` bundles them as app resources.
// Mirrors scripts/packaging/macos/build-dmg.sh rsync set (no venv / node_modules / build output).
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const dest = resolve(here, "..", "src-tauri", "payload");

const EXCLUDED = new Set([".venv", "node_modules", ".git", "dist", "build", "site", "__pycache__", ".pytest_cache", ".next", "graphify-out", ".omc", ".superpowers"]);
const skip = (src) => EXCLUDED.has(basename(src)) || src.endsWith(".pyc");

// Keep the tracked placeholder; wipe everything else from a previous stage.
mkdirSync(dest, { recursive: true });
for (const entry of readdirSync(dest)) {
  if (entry !== ".gitkeep") rmSync(join(dest, entry), { recursive: true, force: true });
}

for (const dir of ["daemon", "coding_agent", "dashboard"]) {
  cpSync(join(repo, dir), join(dest, dir), { recursive: true, filter: (src) => !skip(src) });
}
for (const file of ["pyproject.toml", "run.sh", "README.md"]) {
  if (existsSync(join(repo, file))) cpSync(join(repo, file), join(dest, file));
}
console.log(`staged payload -> ${dest}`);
