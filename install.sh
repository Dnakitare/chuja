#!/usr/bin/env bash
#
# Install `chuja` globally so you can run it from any directory.
#
# Default (fast): if this project's .venv exists, symlink the `chuja` it
#   already contains onto your PATH. No re-download of the ML stack.
# Fallback (clean): if there's no .venv, do an isolated install with pipx.
#
# Override the link target with:  CHUJA_BIN=/usr/local/bin ./install.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${CHUJA_BIN:-$HOME/.local/bin}"

if [ -x "$HERE/.venv/bin/chuja" ]; then
    mkdir -p "$BIN"
    ln -sf "$HERE/.venv/bin/chuja" "$BIN/chuja"
    echo "✓ Linked chuja → $BIN/chuja  (reuses $HERE/.venv — nothing re-downloaded)"
    case ":$PATH:" in
        *":$BIN:"*)
            echo "  Run it from anywhere:   chuja"
            ;;
        *)
            echo "  ⚠ $BIN is not on your PATH yet. Add this to ~/.zshrc, then restart your shell:"
            echo "      export PATH=\"$BIN:\$PATH\""
            ;;
    esac
else
    echo "No .venv here — installing in an isolated environment with pipx…"
    if ! command -v pipx >/dev/null 2>&1; then
        echo "✗ pipx not found. Install it first:  brew install pipx  (or: python3 -m pip install --user pipx)"
        exit 1
    fi
    pipx install --force "$HERE"
    pipx inject chuja yt-dlp   # optional URL-ingestion support
    echo "✓ Installed with pipx.   Run:  chuja"
fi

echo
echo "Try:   chuja            # interactive"
echo "       chuja serve      # visual console"
echo "       chuja song.mp3   # separate a file"
