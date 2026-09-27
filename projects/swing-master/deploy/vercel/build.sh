#!/bin/sh
# Vercel build for a project that is NOT linked to GitHub: fetch the code, then
# build the static dashboard into ./public.  Override the source with env vars.
# Data: add SM_TM_EMAIL and SM_TM_PASSWORD (a TradingMaster login) to the Vercel project's
# environment variables, marked Sensitive, and the build reads real F&O data from
# TradingMaster.  Without them it builds the demo.  SM_DATA_SOURCE overrides either way.
set -eu
REPO="${SM_GIT_REPO:-https://github.com/splasious/ui-ux-pro-max-skill.git}"
REF="${SM_GIT_REF:-claude/trading-app-themes-ogqq9v}"
SUBDIR="${SM_GIT_SUBDIR:-projects/swing-master}"
OUT="$(pwd)/public"

if [ -z "${SM_DATA_SOURCE:-}" ] && [ -n "${SM_TM_EMAIL:-}${SM_TM_TOKEN:-}" ]; then
  export SM_DATA_SOURCE=TRADINGMASTER
fi
echo "data source: ${SM_DATA_SOURCE:-DEMO}"

rm -rf src
git clone --quiet --depth 1 --branch "$REF" "$REPO" src
echo "building $REPO@$REF ($(git -C src rev-parse --short HEAD)) from $SUBDIR"
cd "src/$SUBDIR"
SM_STATE_DIR=/tmp/sm-state python3 -m swing_master.main export-static "$OUT" --split
