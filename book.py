import os
import sys
import time
import datetime
import requests
import json
from pathlib import Path


def load_env_file():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env_file()

IST_OFFSET = datetime.timedelta(hours=5, minutes=30)
IST = datetime.timezone(IST_OFFSET)
PRODUCT_ARENA_CATEGORY_ID = 2


def get_headers():
    at_token = os.environ["CULT_AT_COOKIE"]
    if at_token.startswith("s%3A"):
        at_token = at_token[3:].replace("%2B", "+").replace("%3A", ":")
    if "CFAPP:" not in at_token:
        at_token = f"CFAPP:{at_token}"

    return {
        "clientversion": "11.73",
        "user-agent": "CureFit/907080 CFNetwork/3860.600.12 Darwin/25.5.0",
        "lon": os.environ.get("CULT_LON", "78.35578668906744"),
        "appsource": "flutter",
        "microappversion": "4.0.0",
        "deviceid": os.environ.get("CULT_DEVICE_ID", "B3002D5B-3407-47BC-B569-3FA2B7DC9165"),
        "devicemodel": "iPhone",
        "timezone": "IST",
        "x-tenant-id": "curefit",
        "lat": os.environ.get("CULT_LAT", "17.46301739619454"),
        "at": at_token,
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
        "accept-encoding": "gzip",
        "devicebrand": "apple",
        "osname": "ios",
    }


def get_center_ids():
    raw = os.environ.get("CULT_CENTER_IDS", "1107")
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def get_preferred_times():
    raw = os.environ.get("CULT_PREFERRED_TIMES", "07:00:00,08:00:00")
    return [x.strip() for x in raw.split(",") if x.strip()]


def get_workout_ids():
    raw = os.environ.get("CULT_WORKOUT_IDS", "350")
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def get_max_retries():
    return int(os.environ.get("CULT_MAX_RETRIES", "3"))


def get_retry_delay():
    return int(os.environ.get("CULT_RETRY_DELAY", "5"))


def sleep_until_target_time():
    if os.environ.get("SKIP_SLEEP", "false").lower() == "true":
        print("SKIP_SLEEP=true - Running immediately without waiting.")
        return

    now_ist = datetime.datetime.now(IST)
    target_ist = now_ist.replace(hour=20, minute=59, second=50, microsecond=0)

    if now_ist >= target_ist:
        print(f"Current time {now_ist.strftime('%H:%M:%S')} IST is past 20:59:50. Running immediately.")
        return

    wait_seconds = (target_ist - now_ist).total_seconds()

    if os.environ.get("CLOUD_MODE", "false").lower() == "true":
        if wait_seconds > 300:
            print(f"CLOUD_MODE: wait is {wait_seconds:.0f}s which exceeds 5min timeout. Sleeping 260s.")
            time.sleep(260)
            print(f"Woke up at {datetime.datetime.now(IST).strftime('%H:%M:%S')} IST")
        else:
            print(f"CLOUD_MODE: sleeping {wait_seconds:.0f}s until 20:59:50 IST")
            time.sleep(wait_seconds)
            print(f"Woke up at {datetime.datetime.now(IST).strftime('%H:%M:%S')} IST")
        return

    print(f"Current time: {now_ist.strftime('%H:%M:%S')} IST")
    print(f"Sleeping {wait_seconds:.0f} seconds until 20:59:50 IST (9:00 PM slot)")
    time.sleep(wait_seconds)
    print(f"Woke up at {datetime.datetime.now(IST).strftime('%H:%M:%S')} IST")


def check_auth_expired(response):
    if response.status_code == 401:
        print(f"AUTH EXPIRED: Got status 401. Your at token has expired.")
        print("ACTION REQUIRED: Update CULT_AT_COOKIE with a fresh mobile app token.")
        try:
            from notify import send_notification
            send_notification("auth_expired", None)
        except Exception:
            pass
        sys.exit(2)


def fetch_schedule(center_id, workout_id, headers):
    url = f"https://www.cult.fit/api/v2/fitso/schedule?productType=FITNESS&centerId={center_id}&sportId={workout_id}&workoutId={workout_id}"
    try:
        response = requests.get(url=url, headers=headers, timeout=30)
        check_auth_expired(response)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching schedule for center {center_id}: {e}")
        return None


def find_available_slot(schedule_data, preferred_times, workout_ids):
    try:
        class_by_date_map = schedule_data.get("classByDateMap", {})
        if not class_by_date_map:
            class_by_date_list = schedule_data.get("classByDateList", [])
            if class_by_date_list:
                last_date_data = class_by_date_list[-1]
            else:
                return None, None
        else:
            last_date_key = sorted(class_by_date_map.keys())[-1]
            last_date_data = class_by_date_map[last_date_key]

        for pref_time in preferred_times:
            for time_slot in last_date_data.get("classByTimeList", []):
                slot_time = time_slot.get("id", "")
                normalized_slot_time = slot_time.lstrip("0") if slot_time else ""
                normalized_pref_time = pref_time.lstrip("0")
                if normalized_slot_time != normalized_pref_time:
                    continue

                for center_class in time_slot.get("centerWiseClasses", []):
                    for workout in center_class.get("classes", []):
                        if (
                            workout.get("workoutId") in workout_ids
                            and workout.get("state") in ("AVAILABLE", "WAITLIST_AVAILABLE")
                        ):
                            card_action = workout.get("cardAction", {})
                            card_url = card_action.get("url", "")
                            return workout, card_url

        return None, None
    except Exception as e:
        print(f"Error finding available slot: {e}")
        return None, None


def extract_booking_params(card_url):
    params = {}
    if not card_url:
        return params
    if "?" in card_url:
        query = card_url.split("?", 1)[1]
        for pair in query.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = v
    return params


def book_slot(slot_id, center_id, workout_id, booking_timestamp, headers):
    url = "https://www.cult.fit/api/v2/fitso/class/book"
    body = {
        "slotId": int(slot_id),
        "bookingTimestamp": int(booking_timestamp),
        "centerId": int(center_id),
        "workoutId": int(workout_id),
        "productArenaCategoryId": PRODUCT_ARENA_CATEGORY_ID,
        "params": None,
    }
    try:
        print(f"Booking slot {slot_id} at center {center_id}...")
        response = requests.post(url=url, headers=headers, json=body, timeout=30)
        print(f"Got response: {response.status_code}")
        check_auth_expired(response)
        return response
    except requests.RequestException as e:
        print(f"Error booking slot (RequestException): {type(e).__name__}: {e}")
        return None
    except Exception as e:
        print(f"Error booking slot (Unexpected): {type(e).__name__}: {e}")
        return None


def main():
    print("=" * 50)
    print("Cult.fit Play Auto-Booking Script")
    print("=" * 50)

    sleep_until_target_time()

    headers = get_headers()
    center_ids = get_center_ids()
    preferred_times = get_preferred_times()
    workout_ids = get_workout_ids()
    max_retries = get_max_retries()
    retry_delay = get_retry_delay()

    print(f"Centers: {center_ids}")
    print(f"Preferred times: {preferred_times}")
    print(f"Workout IDs: {workout_ids}")
    print(f"Max retries: {max_retries}, Retry delay: {retry_delay}s")

    booking_result = None
    booked_class_info = None

    for attempt in range(1, max_retries + 1):
        print(f"\n--- Attempt {attempt}/{max_retries} ---")

        for center_id in center_ids:
            for workout_id in workout_ids:
                schedule_data = fetch_schedule(center_id, workout_id, headers)
                if not schedule_data:
                    continue

                workout, card_url = find_available_slot(schedule_data, preferred_times, [workout_id])
                if not workout:
                    print(f"No available slot for workout {workout_id} at center {center_id}")
                    continue

                booking_params = extract_booking_params(card_url)
                slot_id = booking_params.get("slotId", workout.get("id"))
                booking_ts = booking_params.get("bookingTimestamp")

                state = workout.get("state", "UNKNOWN")
                print(f"Found slot: ID={slot_id}, Workout={workout.get('workoutName')}, "
                      f"Time={workout.get('startTime')}, Date={workout.get('date')}, "
                      f"Seats={workout.get('availableSeats')}, State={state}")

                if not booking_ts:
                    date_str = workout.get("date", "")
                    start_time = workout.get("startTime", "")
                    try:
                        dt = datetime.datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M:%S")
                        dt = dt.replace(tzinfo=IST)
                        booking_ts = int(dt.timestamp() * 1000)
                    except ValueError:
                        print("Could not calculate booking timestamp")
                        continue

                response = book_slot(slot_id, center_id, workout_id, booking_ts, headers)
                if response is None:
                    print("Booking request failed - no response")
                else:
                    try:
                        resp_json = response.json()
                    except ValueError:
                        resp_json = response.text

                    print(f"Booking response: {response.status_code}")
                    resp_str = json.dumps(resp_json) if isinstance(resp_json, dict) else str(resp_json)
                    print(f"Response: {resp_str[:300]}")

                    if response.status_code == 200:
                        print("SLOT BOOKED SUCCESSFULLY!")
                        booked_class_info = {
                            "workout_name": workout.get("workoutName", "Unknown"),
                            "start_time": workout.get("startTime", "Unknown"),
                            "date": workout.get("date", "Unknown"),
                            "center_id": center_id,
                            "slot_id": slot_id,
                            "available_seats": workout.get("availableSeats", 0),
                            "state": state,
                        }
                        booking_result = "success"
                        break
                    elif response.status_code == 400 and "Booking Conflict" in resp_str:
                        print("Already booked at this timeslot - treating as success.")
                        booked_class_info = {
                            "workout_name": workout.get("workoutName", "Unknown"),
                            "start_time": workout.get("startTime", "Unknown"),
                            "date": workout.get("date", "Unknown"),
                            "center_id": center_id,
                            "slot_id": slot_id,
                            "available_seats": workout.get("availableSeats", 0),
                            "state": "ALREADY_BOOKED",
                        }
                        booking_result = "success"
                        break
                    elif response.status_code == 400 and "Limit exceeded" in resp_str:
                        print("Booking limit exceeded for this slot.")
                        booking_result = "failure"
                        break
                    else:
                        print(f"Booking failed with status {response.status_code}")

            if booking_result == "success":
                break

        if booking_result == "success":
            break

        if attempt < max_retries:
            print(f"Attempt failed. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)

    if booking_result != "success":
        print("\nAll attempts failed. Could not book a slot.")
        booking_result = "failure"
        booked_class_info = None

    try:
        from notify import send_notification
        send_notification(booking_result, booked_class_info)
    except Exception as e:
        print(f"Failed to send notification: {e}")

    if booking_result == "success":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()