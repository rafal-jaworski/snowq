#!/usr/bin/env bash
# Tworzy venv + instaluje connector (raz) i startuje snowqd, jeśli nie działa.
# Idempotentne: jeśli daemon już odpowiada, nic nie robi (zero kolejnych popupów).
# Wszystko (venv, socket, logi) leży obok tego pliku.
set -euo pipefail

D="$(cd "$(dirname "$0")" && pwd)"
VENV="$D/venv"
PY="$VENV/bin/python"

if [ -S "$D/snowqd.sock" ] && "$D/snowq" "SELECT 1" >/dev/null 2>&1; then
  echo "snowqd już działa ✓"
  exit 0
fi

[ -x "$PY" ] || { echo "tworzę venv…"; python3 -m venv "$VENV"; }
"$VENV/bin/pip" install -q --disable-pip-version-check snowflake-connector-python

echo "startuję snowqd — zaloguj się w przeglądarce (raz)…"
nohup "$PY" "$D/snowqd.py" >>"$D/snowqd.out" 2>&1 &
echo "  pid $!"

for _ in $(seq 1 90); do
  if [ -S "$D/snowqd.sock" ] && "$D/snowq" "SELECT 1" >/dev/null 2>&1; then
    echo "snowqd gotowy ✓"
    exit 0
  fi
  sleep 2
done
echo "snowqd nie wstał — log: $D/snowqd.log / $D/snowqd.out" >&2
exit 1
