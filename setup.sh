#!/bin/bash
# Setup script for Replit environment
# Run this once: bash setup.sh

echo "=== Installing Chromium and dependencies ==="

# Install via nix-env (works even if replit.nix isn't applied)
nix-env -iA nixpkgs.chromium nixpkgs.chromedriver 2>/dev/null

# Find installed paths
CHROMIUM_PATH=$(which chromium 2>/dev/null || find /nix/store -name "chromium" -type f -executable 2>/dev/null | head -1)
CHROMEDRIVER_PATH=$(which chromedriver 2>/dev/null || find /nix/store -name "chromedriver" -type f -executable 2>/dev/null | head -1)

echo ""
echo "=== Results ==="
if [ -n "$CHROMIUM_PATH" ]; then
    echo "✅ Chromium found: $CHROMIUM_PATH"
    echo "export CHROME_BIN=$CHROMIUM_PATH" >> ~/.bashrc
else
    echo "❌ Chromium not found"
fi

if [ -n "$CHROMEDRIVER_PATH" ]; then
    echo "✅ chromedriver found: $CHROMEDRIVER_PATH"
    echo "export CHROMEDRIVER_PATH=$CHROMEDRIVER_PATH" >> ~/.bashrc
else
    echo "❌ chromedriver not found"
fi

echo ""
echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo ""
echo "=== Done! Run: source ~/.bashrc && python main.py ==="
