#!/usr/bin/env bash
# NOTE: Interim / secondary packaging. The primary ship path is the Tauri desktop app:
#   cd desktop && npm run tauri build   (see coding_agent/README.md)
# This script remains as a shell-launcher fallback (opens the browser via run.sh --open).
# Build dist/Loom-Coding-Agent-<version>.dmg — full Loom bring-up (daemon + coding_agent + dashboard).
#
# Usage:
#   bash scripts/packaging/macos/build-dmg.sh
#   bash scripts/packaging/macos/build-dmg.sh --skip-npm-check
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
VERSION="$(python3 -c "import pathlib,re; t=pathlib.Path('$ROOT/pyproject.toml').read_text(); print(re.search(r'^version\s*=\s*\"([^\"]+)\"', t, re.M).group(1))")"
DIST="$ROOT/dist"
STAGE="$DIST/dmg-stage"
VOLNAME="Loom Coding Agent"
APP_NAME="Loom Coding Agent.app"
DMG_NAME="Loom-Coding-Agent-${VERSION}.dmg"
SKIP_NPM_CHECK=0

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-npm-check) SKIP_NPM_CHECK=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--skip-npm-check]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ "$(uname -s)" != "Darwin" ]; then
  echo "DMG packaging requires macOS (hdiutil)." >&2
  exit 1
fi

command -v hdiutil >/dev/null
command -v python3 >/dev/null
if [ "$SKIP_NPM_CHECK" -eq 0 ]; then
  command -v npm >/dev/null || {
    echo "npm not found (needed for first-run dashboard install). Pass --skip-npm-check to build anyway." >&2
    exit 1
  }
fi

rm -rf "$STAGE"
mkdir -p "$STAGE/$APP_NAME/Contents/MacOS" "$STAGE/$APP_NAME/Contents/Resources/payload"

# --- App icon (Warp — primary Loom mark) ------------------------------------
ICON_SRC="$ROOT/docs/branding/loom-icon-warp-512.png"
if [ ! -f "$ICON_SRC" ]; then
  echo "Missing brand icon: $ICON_SRC" >&2
  exit 1
fi
ICONSET="$DIST/.AppIcon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
# iconutil expects exact names; build from the 512px Warp tile.
sips -z 16 16     "$ICON_SRC" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -z 32 32     "$ICON_SRC" --out "$ICONSET/diana.k@example.org" >/dev/null
sips -z 32 32     "$ICON_SRC" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -z 64 64     "$ICON_SRC" --out "$ICONSET/ivan.p@example.net" >/dev/null
sips -z 128 128   "$ICON_SRC" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -z 256 256   "$ICON_SRC" --out "$ICONSET/wendy.h@example.net" >/dev/null
sips -z 256 256   "$ICON_SRC" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -z 512 512   "$ICON_SRC" --out "$ICONSET/wendy.h@example.net" >/dev/null
sips -z 512 512   "$ICON_SRC" --out "$ICONSET/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$ICON_SRC" --out "$ICONSET/walt.e@example.net" >/dev/null
iconutil -c icns "$ICONSET" -o "$STAGE/$APP_NAME/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"
# Finder / DMG preview also get a PNG copy next to the app.
cp "$ICON_SRC" "$STAGE/.VolumeIcon.png" 2>/dev/null || true

# --- App launcher -----------------------------------------------------------
cat > "$STAGE/$APP_NAME/Contents/MacOS/LoomCodingAgent" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
RESOURCES="$APP_DIR/Contents/Resources"
PAYLOAD="$RESOURCES/payload"
SUPPORT="${HOME}/Library/Application Support/LoomCodingAgent"
INSTALL_ROOT="$SUPPORT/app"
LOG="$SUPPORT/launch.log"

# Finder/.app launches use a tiny PATH (no Homebrew, nvm, hermes, …).
_loom_prepend_path() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  case ":${PATH:-}:" in
    *":$dir:"*) ;;
    *) PATH="$dir${PATH:+:$PATH}" ;;
  esac
}
_loom_bootstrap_path() {
  _loom_prepend_path "/opt/homebrew/bin"
  _loom_prepend_path "/opt/homebrew/sbin"
  _loom_prepend_path "/usr/local/bin"
  _loom_prepend_path "/opt/homebrew/opt/node@24/bin"
  _loom_prepend_path "/opt/homebrew/opt/node@22/bin"
  _loom_prepend_path "/opt/homebrew/opt/node@20/bin"
  _loom_prepend_path "${HOME}/.hermes/node/bin"
  _loom_prepend_path "${HOME}/.local/bin"
  _loom_prepend_path "${HOME}/.bun/bin"
  if [ -d "${HOME}/.nvm/versions/node" ]; then
    local latest
    latest="$(ls -1 "${HOME}/.nvm/versions/node" 2>/dev/null | sort -V | tail -1 || true)"
    [ -n "${latest:-}" ] && _loom_prepend_path "${HOME}/.nvm/versions/node/${latest}/bin"
  fi
  if [ -d "${HOME}/.fnm/node-versions" ]; then
    local fnm_latest
    fnm_latest="$(ls -1 "${HOME}/.fnm/node-versions" 2>/dev/null | sort -V | tail -1 || true)"
    [ -n "${fnm_latest:-}" ] && _loom_prepend_path "${HOME}/.fnm/node-versions/${fnm_latest}/installation/bin"
  fi
  # Merge login-shell PATH last (covers custom installs from ~/.zprofile).
  local login_path=""
  if [ -x /bin/zsh ]; then
    login_path="$(/bin/zsh -lc 'printf %s "$PATH"' 2>/dev/null || true)"
  elif [ -x /bin/bash ]; then
    login_path="$(/bin/bash -lc 'printf %s "$PATH"' 2>/dev/null || true)"
  fi
  if [ -n "$login_path" ]; then
    PATH="${PATH:+$PATH:}$login_path"
  fi
  export PATH
}
_loom_bootstrap_path

_loom_resolve() {
  # Prefer real binaries over shims that may be missing in GUI context.
  local name="$1"
  local candidate
  for candidate in \
    "/opt/homebrew/bin/$name" \
    "/usr/local/bin/$name" \
    "${HOME}/.hermes/node/bin/$name" \
    "/opt/homebrew/opt/node@24/bin/$name" \
    "/opt/homebrew/opt/node@22/bin/$name" \
    "/opt/homebrew/opt/node@20/bin/$name"
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  command -v "$name" 2>/dev/null || return 1
}

mkdir -p "$SUPPORT"
exec > >(tee -a "$LOG") 2>&1
echo "---- $(date) ----"
echo "PATH=$PATH"

osascript <<'OSA' >/dev/null 2>&1 || true
display notification "Starting Loom Coding Agent…" with title "Loom OS"
OSA

need_copy=0
if [ ! -f "$INSTALL_ROOT/run.sh" ] || [ ! -d "$INSTALL_ROOT/coding_agent" ]; then
  need_copy=1
fi
if [ "$need_copy" -eq 1 ]; then
  echo "Installing payload → $INSTALL_ROOT"
  rm -rf "$INSTALL_ROOT"
  mkdir -p "$SUPPORT"
  cp -R "$PAYLOAD" "$INSTALL_ROOT"
fi

cd "$INSTALL_ROOT"

PYTHON_BIN="$(_loom_resolve python3 || true)"
NPM_BIN="$(_loom_resolve npm || true)"
NODE_BIN="$(_loom_resolve node || true)"

if [ -z "${PYTHON_BIN:-}" ]; then
  osascript -e 'display alert "Loom Coding Agent" message "Python 3.11+ is required. Install from https://www.python.org/downloads/ (or brew install python) then reopen the app."'
  exit 1
fi
if [ -z "${NPM_BIN:-}" ] || [ -z "${NODE_BIN:-}" ]; then
  osascript -e 'display alert "Loom Coding Agent" message "Node.js 20+ (npm) was not found on the app PATH. Install from https://nodejs.org/ or `brew install node`, then reopen the app. Tip: GUI apps do not see Terminal-only PATH entries."'
  exit 1
fi
echo "Using python=$PYTHON_BIN node=$NODE_BIN npm=$NPM_BIN"

if [ ! -d .venv ]; then
  echo "Creating venv + installing loom-os (daemon + coding_agent)…"
  "$PYTHON_BIN" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -U pip
  pip install -e ".[llm]"
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ ! -d dashboard/node_modules ]; then
  echo "Installing dashboard dependencies…"
  (cd dashboard && "$NPM_BIN" install)
fi

chmod +x ./run.sh
echo "Launching ./run.sh --open"
# Ensure child processes keep the bootstrapped PATH (Homebrew node for Next.js).
export PATH
exec ./run.sh --open
LAUNCHER
chmod +x "$STAGE/$APP_NAME/Contents/MacOS/LoomCodingAgent"

cat > "$STAGE/$APP_NAME/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>LoomCodingAgent</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>os.loom.coding-agent</string>
  <key>CFBundleName</key>
  <string>Loom Coding Agent</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
  <key>CFBundleVersion</key>
  <string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

# --- Payload (full Loom bring-up sources; no venv / node_modules) ----------
PAYLOAD_DST="$STAGE/$APP_NAME/Contents/Resources/payload"
rsync -a \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude '.git' \
  --exclude 'dist' \
  --exclude 'build' \
  --exclude 'site' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.next' \
  --exclude 'graphify-out' \
  --exclude '.omc' \
  --exclude '.superpowers' \
  --exclude '*.pyc' \
  "$ROOT/daemon/" "$PAYLOAD_DST/daemon/"
rsync -a \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$ROOT/coding_agent/" "$PAYLOAD_DST/coding_agent/"
rsync -a \
  --exclude 'node_modules' --exclude '.next' --exclude '.venv' \
  "$ROOT/dashboard/" "$PAYLOAD_DST/dashboard/"
cp "$ROOT/pyproject.toml" "$ROOT/run.sh" "$ROOT/README.md" "$PAYLOAD_DST/"
chmod +x "$PAYLOAD_DST/run.sh"

# Keep package layout importable: pyproject expects daemon/ + coding_agent/ at root.
# Also copy minimal docs linked from README if present.
mkdir -p "$PAYLOAD_DST/docs/superpowers/specs" "$PAYLOAD_DST/docs/superpowers/plans" 2>/dev/null || true
for f in \
  docs/USAGE.md \
  docs/superpowers/specs/2026-11-16-loom-coding-agent-pattern-routing-design.md \
  docs/superpowers/plans/2026-11-22-coding-agent-phase-2-selection-ux.md
do
  if [ -f "$ROOT/$f" ]; then
    mkdir -p "$PAYLOAD_DST/$(dirname "$f")"
    cp "$ROOT/$f" "$PAYLOAD_DST/$f"
  fi
done

cat > "$STAGE/README - First Run.txt" <<EOF
Loom Coding Agent ${VERSION}
============================

This disk image includes the Loom OS daemon, coding_agent package, and
Next.js dashboard launcher (full local bring-up).

1. Drag "Loom Coding Agent" into Applications (optional).
2. Double-click the app.
3. First launch copies sources to:
     ~/Library/Application Support/LoomCodingAgent/app
   then creates a Python venv, pip-installs loom-os[llm], runs npm install
   in dashboard/, and starts ./run.sh --open.
4. Open http://localhost:3000 — configure your LLM API key under Agent settings.
5. Use Implement on a task to run the coding-agent loop.

Prerequisites: Python 3.11+, Node.js 20+, Git, network (first run only).

Docs: open coding_agent/README.md inside the installed app folder, or see the
project README on GitHub.
EOF

# Applications shortcut for drag-install UX
ln -sf /Applications "$STAGE/Applications"

# --- Create DMG -------------------------------------------------------------
mkdir -p "$DIST"
rm -f "$DIST/$DMG_NAME"
TMP_DMG="$DIST/.${DMG_NAME}.tmp.dmg"
rm -f "$TMP_DMG"

hdiutil create \
  -volname "$VOLNAME" \
  -srcfolder "$STAGE" \
  -ov \
  -format UDRW \
  "$TMP_DMG"

hdiutil convert "$TMP_DMG" -format ULMO -o "$DIST/$DMG_NAME"
rm -f "$TMP_DMG"
rm -rf "$STAGE"

echo "Created $DIST/$DMG_NAME"
ls -lh "$DIST/$DMG_NAME"
