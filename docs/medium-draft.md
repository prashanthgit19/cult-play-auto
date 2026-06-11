# I Reverse-Engineered the Cult.fit App to Automate My Badminton Slot Booking

*How I built an AWS Lambda function that books my cult.fit Play slot at exactly 9:00 PM IST — every single day.*

---

## The 9:00 PM Bloodbath

If you've ever tried booking a badminton court on cult.fit Play, you know the pain. Slots for the upcoming week open at exactly 9:00 PM IST, and the popular ones — evening slots at good centers — vanish in under 5 seconds. It's worse than IRCTC Tatkal booking.

I've been playing badminton at Fitso Kondapur in Hyderabad for months. Every night at 8:59 PM, I'd open the app, fingers ready, refreshing like my life depended on it. And every night, I'd watch the 7 PM and 8 PM slots disappear before I could even tap "Book."

After weeks of frustration, I decided to automate it.

## The Web API Trap

My first instinct was to hit the cult.fit web API. I opened Chrome DevTools, logged into cult.fit, and started intercepting network requests. The API endpoints were straightforward:

```
GET /api/v2/fitso/schedule?centerId=1107&sportId=350&workoutId=350
POST /api/v2/fitso/class/book
```

But there was a problem. Every booking request returned a 302 redirect to an onboarding page asking me to fill out a PAR-Q (Physical Activity Readiness Questionnaire). The web API blocks Play bookings unless you've completed this form — and there's no way to bypass it programmatically.

The web API was a dead end.

## Going Mobile: Reverse-Engineering the cult.fit App

The cult.fit mobile app, on the other hand, doesn't have the PAR-Q restriction. Play bookings work fine on the app. So I needed to figure out what the mobile app does differently.

### Setting Up mitmproxy

I used [mitmproxy](https://mitmproxy.org/) to intercept HTTPS traffic from my iPhone:

1. Installed mitmproxy on my Mac: `pip install mitmproxy`
2. Configured my iPhone's Wi-Fi proxy to point to my Mac's IP on port 8080
3. Installed the mitmproxy CA certificate on my iPhone (Settings > General > VPN & Device Management)
4. Enabled full trust for the certificate (Settings > General > About > Certificate Trust Settings)
5. Opened the cult.fit app and started browsing

Within seconds, mitmproxy lit up with requests to `cult.fit`. I found what I was looking for:

```
GET https://www.cult.fit/api/v2/fitso/schedule?centerId=1107&sportId=350&workoutId=350
```

The request headers were the key:

```
at: CFAPP:a4ebda60-7758-41ca-817d-e9835cb5d771
clientversion: 11.73
deviceid: B3002D5B-3407-47BC-B569-3FA2B7DC9165
appsource: flutter
x--tenant-id: curefit
```

The `at` header is the authentication token. Unlike web cookies (`s%3ACFAPP:uuid.signature`), the mobile app uses a simpler `CFAPP:uuid` format. And crucially — the mobile API doesn't block Play bookings with the PAR-Q redirect.

I also found the booking endpoint:

```
POST https://www.cult.fit/api/v2/fitso/class/book
Body: {
    "slotId": 12345,
    "bookingTimestamp": 1717234800000,
    "centerId": 1107,
    "workoutId": 350,
    "productArenaCategoryId": 2,
    "params": null
}
```

The booking was just a POST request with the right slot ID and timestamp. This was automatable.

## Building the Automation

I wrote a Python script that:

1. **Fetches the schedule** for my center and workout
2. **Finds the best available slot** — preferring AVAILABLE over WAITLIST_AVAILABLE
3. **Books the slot** at exactly 9:00 PM IST
4. **Sends an email notification** via Gmail SMTP

### The Slot Selection Logic

The schedule API returns a `classByDateMap` with slots for each day. I look at the **last date** (the newly opened week) and check my preferred times in order (7 PM first, then 8 PM as fallback).

The key insight: the API returns two states:
- `AVAILABLE` — there are open seats
- `WAITLIST_AVAILABLE` — all seats are taken, but you can join the waitlist

My script prefers `AVAILABLE` slots and only falls back to `WAITLIST_AVAILABLE` if no open seats exist. When it books a waitlist slot, the notification clearly says "Slots Full — Joined Waitlist" so I know what happened.

### The Timing Problem

The slots open at exactly 9:00 PM IST. If I schedule the script to run at 9:00 PM, there's network latency, Lambda cold start time, and other delays. I needed the booking request to hit the API as close to 9:00:00 as possible.

Solution: I trigger the Lambda at 8:55 PM IST, then **sleep until 9:00:00 PM** inside the function. This way, the code is already warm and ready to fire the instant the clock strikes 9.

```python
def sleep_until_target_time(target_hour=21, target_minute=0):
    now_ist = datetime.datetime.now(IST)
    target = now_ist.replace(hour=target_hour, minute=target_minute, second=0)
    wait_seconds = (target - now_ist).total_seconds()
    time.sleep(wait_seconds)
    # Now book!
```

### The Retry Logic

Sometimes the first attempt fails — the API might return an error, or the slot data might not be ready yet. I added a retry mechanism with configurable attempts:

```python
for attempt in range(1, max_retries + 1):
    # fetch schedule, find slot, book
    if booking_result == "success":
        break
    time.sleep(retry_delay)  # wait 5 seconds before retrying
```

## From Local Script to AWS Lambda

Running the script on my Mac wasn't reliable — the laptop might be closed, the Wi-Fi might drop, or I might be away from home. I needed it to run in the cloud, every day, without fail.

### Why AWS Lambda?

- **Free tier**: 1 million requests and 400,000 GB-seconds per month. My daily booking uses 1 request × ~6 seconds. That's $0/month.
- **EventBridge**: Built-in cron scheduler that triggers the Lambda at exactly 9:00 PM IST daily.
- **No server management**: Just upload the code and set a schedule.

### The Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────┐     ┌──────────────┐
│  EventBridge     │────▶│  AWS Lambda      │────▶│  cult.fit API │────▶│  Gmail SMTP  │
│  cron(30 15 * *) │     │  sleep → fetch   │     │  /schedule    │     │  email       │
│  9:00 PM IST     │     │  book → notify    │     │  /class/book  │     │  notification │
└─────────────────┘     └──────────────────┘     └───────────────┘     └──────────────┘
```

The Lambda function:
1. Receives an EventBridge event at 9:00 PM IST
2. Sleeps until exactly 9:00:00 PM
3. Fetches the schedule from the cult.fit mobile API
4. Finds the best available slot
5. Books it
6. Sends an email notification (success, waitlist, or failure)

### Multi-User Support

My friend also plays badminton at the same center. I extended the system to support multiple users with a single Lambda function:

- Each user gets their own `at` token and device headers
- Environment variables are prefixed: `CULT_AT_COOKIE` for me, `FRIEND_CULT_AT_COOKIE` for my friend
- Two separate EventBridge rules fire at 9:00 PM IST: one with `{"user": "self"}` and one with `{"user": "friend"}`
- The Lambda reads the correct config based on the event payload
- Each user gets their own email notification

```python
def get_user_config(user="self"):
    prefix = "" if user == "self" else f"{user.upper()}_"
    return {
        "at_token": os.environ.get(f"{prefix}CULT_AT_COOKIE", ""),
        "center_ids": os.environ.get(f"{prefix}CULT_CENTER_IDS", "1107"),
        # ... more config
    }
```

## The Token Expiry Problem

There's one problem I haven't been able to fully automate: the `at` token expires periodically. Since cult.fit uses phone OTP for login, there's no way to programmatically refresh the token.

When the token expires, I get an email notification:

```
Subject: cultfit: TOKEN EXPIRED - Action Required!

Your cult.fit mobile app token (at) has expired.

ACTION REQUIRED:
1. Open cult.fit app on your phone
2. Set up mitmproxy and intercept traffic
3. Copy the new 'at' header value (CFAPP:...)
4. Update the Lambda environment variable
```

Then I re-capture the token using mitmproxy and update the Lambda env var. It takes about 5 minutes.

For my friend, who also uses an iPhone, the process is the same — I capture her token via mitmproxy and update the `FRIEND_CULT_AT_COOKIE` env var.

## Lessons Learned

### 1. `requests.Response` is Falsy for Error Codes

I initially wrote:

```python
if response:
    # process response
```

But `requests.Response` objects with 4xx/5xx status codes evaluate as falsy. The correct check is:

```python
if response is not None:
    # process response — check status_code yourself
```

This bug caused the script to silently ignore booking failures.

### 2. Waitlist ≠ Available

The cult.fit API returns two slot states: `AVAILABLE` and `WAITLIST_AVAILABLE`. Initially, I treated both the same — if there's a slot, book it. But my friend and I don't want to be on a waitlist; we want a confirmed booking.

The fix was straightforward: prefer `AVAILABLE` slots, and only fall back to `WAITLIST_AVAILABLE` if no confirmed slots exist. The notification system now clearly distinguishes between "Slot Booked Successfully" and "Slots Full — Joined Waitlist."

### 3. AWS CLI v1 vs v2 Command Syntax

The AWS CLI has two major versions with different command syntax. v1 uses kebab-case (`aws sts get-caller-identity`) while v2 uses PascalCase (`aws sts GetCallerIdentity`). My setup script used PascalCase, which failed for users with v1 installed. The fix: use kebab-case, which works on both versions.

### 4. Sleeping in Lambda

AWS Lambda has a maximum timeout of 15 minutes. My function triggers at 8:55 PM IST, sleeps for ~5 minutes until 9:00 PM, then executes the booking. The 300-second timeout (5 minutes) is well within Lambda's 15-minute limit. But this means the Lambda costs a few more seconds of compute time — still within the free tier.

### 5. Lambda Environment Variables JSON Parsing

When setting Lambda environment variables via the AWS CLI, the JSON format is finicky. Initial attempts with nested quotes and escaped characters failed. The fix was to build the JSON string separately using a heredoc, then pass it to the CLI:

```bash
ENV_JSON=$(cat <<EOF
{"CULT_AT_COOKIE":"$AT_COOKIE","CULT_CENTER_IDS":"1107"}
EOF
)
aws lambda update-function-configuration \
    --environment "{\"Variables\":$ENV_JSON}"
```

## The Open-Source Repo

I've open-sourced the entire project: [github.com/prashanthgit19/cultfit-sportsplay-booking-automation](https://github.com/prashanthgit19/cultfit-sportsplay-booking-automation)

### What's Included

- **`cultplay/` Python package** — Core booking logic, config management, notifications
- **`book.py`** — CLI entry point with `--dry-run`, `--skip-sleep`, `--user`, `--center`, `--workout`, `--times`
- **`lambda_function.py`** — AWS Lambda entry point with multi-user support
- **`setup_aws.sh`** — One-command AWS setup (IAM role, Lambda function, EventBridge rules)
- **`deploy.sh`** — Quick Lambda deployment after code changes
- **Token capture guide** — Step-by-step mitmproxy instructions for iPhone and Android emulator
- **GitHub Actions workflow** — Alternative deployment for public repos

### Quick Start

```bash
git clone https://github.com/prashanthgit19/cultfit-sportsplay-booking-automation.git
cd cultfit-sportsplay-booking-automation
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your cult.fit token and preferences
python book.py --dry-run    # Preview available slots
python book.py --skip-sleep # Run immediately (for testing)
```

### AWS Deployment

```bash
./setup_aws.sh   # One-time setup
./deploy.sh       # After code changes
```

## Results

I've been running this automation for over a month now. The booking success rate is near 100% for AVAILABLE slots. Every evening at 9:00 PM IST, the Lambda fires, and within seconds I get an email:

```
Subject: cultfit Play: Slot Booked Successfully!

Your cult.fit Play slot has been booked!

Workout: Badminton
Date: 2025-06-15
Time: 19:00:00
Center ID: 1107

Check your cult.fit app for details.
```

No more refreshing, no more tapping, no more missed slots.

---

*If you found this useful, star the [GitHub repo](https://github.com/prashanthgit19/cultfit-sportsplay-booking-automation) and share it with your badminton group. And if you have ideas for improvements, PRs are welcome!*

**Tags:** `cultfit`, `cult.fit`, `badminton`, `automation`, `aws-lambda`, `python`, `slot-booking`, `hyderabad`, `sports`, `play`