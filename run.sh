#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    exit 1
fi

while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    export "$key=$value"
done < "$ENV_FILE"

cd "$SCRIPT_DIR"

caffeinate -is /Users/prashanthk/miniconda3/bin/python3 book.py