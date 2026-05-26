#!/bin/sh
set -e

echo "=== Cult.fit Play Auto-Booking - iSH Setup ==="

apk update
apk add python3 py3-pip curl

pip3 install requests

mkdir -p ~/cult-play-auto && cd ~/cult-play-auto

cat > .env << 'ENVEOF'
CULT_AT_COOKIE=CFAPP:a4ebda60-7758-41ca-817d-e9835cb5d771
CULT_CENTER_IDS=1107
CULT_PREFERRED_TIMES=19:00:00,20:00:00
CULT_WORKOUT_IDS=350
CULT_MAX_RETRIES=3
CULT_RETRY_DELAY=5
GMAIL_ADDRESS=koyyeprashanth@gmail.com
GMAIL_APP_PASSWORD=ciofcemqogomsenh
NOTIFY_EMAIL=koyyeprashanth@gmail.com
ENVEOF

curl -sL https://raw.githubusercontent.com/prashanthgit19/cult-play-auto/main/book.py -o book.py
curl -sL https://raw.githubusercontent.com/prashanthgit19/cult-play-auto/main/notify.py -o notify.py
curl -sL https://raw.githubusercontent.com/prashanthgit19/cult-play-auto/main/requirements.txt -o requirements.txt

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To test:    SKIP_SLEEP=true python3 book.py"
echo "To book at 9 PM, keep iSH open and run:"
echo "  python3 book.py"