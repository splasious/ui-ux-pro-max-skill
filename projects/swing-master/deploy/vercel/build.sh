#!/bin/sh
# Vercel build for a project that is NOT linked to GitHub: fetch the code, then
# build the static dashboard into ./public.  Override the source with env vars.
set -eu
REPO="${SM_GIT_REPO:-https://github.com/splasious/ui-ux-pro-max-skill.git}"
REF="${SM_GIT_REF:-claude/trading-app-themes-ogqq9v}"
SUBDIR="${SM_GIT_SUBDIR:-projects/swing-master}"
OUT="$(pwd)/public"

rm -rf src
git clone --quiet --depth 1 --branch "$REF" "$REPO" src
echo "building $REPO@$REF ($(git -C src rev-parse --short HEAD)) from $SUBDIR"
cd "src/$SUBDIR"
SM_STATE_DIR=/tmp/sm-state python3 -m swing_master.main export-static "$OUT/index.html"
