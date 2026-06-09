import os
import json
import time
import datetime
import requests

IST_OFFSET = datetime.timedelta(hours=5, minutes=30)
IST = datetime.timezone(IST_OFFSET)
PRODUCT_ARENA_CATEGORY_ID = 2


def get_user_config(user):
    prefix = "" if user == "self" else f"{user.upper()}_"
    config = {
        "at_token": os.environ.get(f"{prefix}CULT_AT_COOKIE", ""),
        "center_ids": os.environ.get(f"{prefix}CULT_CENTER_IDS", "1107"),
        "preferred_times": os.environ.get(f"{prefix}CULT_PREFERRED_TIMES", "19:00:00,20:00:00"),
        "workout_ids": os.environ.get(f"{prefix}CULT_WORKOUT_IDS", "350"),
        "max_retries": os.environ.get(f"{prefix}CULT_MAX_RETRIES", "3"),
        "retry_delay": os.environ.get(f"{prefix}CULT_RETRY_DELAY", "5"),
        "device_id": os.environ.get(f"{prefix}CULT_DEVICE_ID", "B3002D5B-3407-47BC-B569-3FA2B7DC9165"),
        "lat": os.environ.get(f"{prefix}CULT_LAT", "17.46301739619454"),
        "lon": os.environ.get(f"{prefix}CULT_LON", "78.35578668906744"),
        "user_agent": os.environ.get(f"{prefix}CULT_USER_AGENT", "CureFit/907080 CFNetwork/3860.600.12 Darwin/25.5.0"),
        "client_version": os.environ.get(f"{prefix}CULT_CLIENT_VERSION", "11.73"),
        "device_brand": os.environ.get(f"{prefix}CULT_DEVICE_BRAND", "apple"),
        "os_name": os.environ.get(f"{prefix}CULT_OS_NAME", "ios"),
        "gmail_address": os.environ.get(f"{prefix}GMAIL_ADDRESS", os.environ.get("GMAIL_ADDRESS", "")),
        "gmail_app_password": os.environ.get(f"{prefix}GMAIL_APP_PASSWORD", os.environ.get("GMAIL_APP_PASSWORD", "")).replace(" ", ""),
        "notify_email": os.environ.get(f"{prefix}NOTIFY_EMAIL", os.environ.get(f"{prefix}GMAIL_ADDRESS", os.environ.get("GMAIL_ADDRESS", ""))),
        "name": user,
    }
    return config


def get_headers(config):
    at_token = config["at_token"]
    if at_token.startswith("s%3A"):
        at_token = at_token[3:].replace("%2B", "+").replace("%3A", ":")
    if "CFAPP:" not in at_token:
        at_token = f"CFAPP:{at_token}"

    return {
        "clientversion": config["client_version"],
        "user-agent": config["user_agent"],
        "lon": config["lon"],
        "appsource": "flutter",
        "microappversion": "4.0.0",
        "deviceid": config["device_id"],
        "devicemodel": "iPhone",
        "timezone": "IST",
        "x-tenant-id": "curefit",
        "lat": config["lat"],
        "at": at_token,
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
        "accept-encoding": "gzip",
        "devicebrand": config["device_brand"],
        "osname": config["os_name"],
    }


def check_auth_expired(response, config):
    if response.status_code == 401:
        print(f"AUTH EXPIRED for user '{config['name']}': Got status 401.")
        print("ACTION REQUIRED: Update the CULT_AT_COOKIE Lambda env var with a fresh mobile app token.")
        try:
            from notify import send_notification
            send_notification("auth_expired", None, config)
        except Exception:
            pass
        raise Exception("AUTH_EXPIRED")


def fetch_schedule(center_id, workout_id, headers):
    url = f"https://www.cult.fit/api/v2/fitso/schedule?productType=FITNESS&centerId={center_id}&sportId={workout_id}&workoutId={workout_id}"
    try:
        response = requests.get(url=url, headers=headers, timeout=30)
        check_auth_expired(response, None)
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

        waitlist_slots = []

        for pref_time in preferred_times:
            for time_slot in last_date_data.get("classByTimeList", []):
                slot_time = time_slot.get("id", "")
                normalized_slot_time = slot_time.lstrip("0") if slot_time else ""
                normalized_pref_time = pref_time.lstrip("0")
                if normalized_slot_time != normalized_pref_time:
                    continue

                for center_class in time_slot.get("centerWiseClasses", []):
                    for workout in center_class.get("classes", []):
                        if workout.get("workoutId") not in workout_ids:
                            continue
                        state = workout.get("state", "")
                        if state == "AVAILABLE":
                            card_action = workout.get("cardAction", {})
                            card_url = card_action.get("url", "")
                            return workout, card_url
                        elif state == "WAITLIST_AVAILABLE":
                            waitlist_slots.append((workout, workout.get("cardAction", {}).get("url", "")))

        if waitlist_slots:
            return waitlist_slots[0][0], waitlist_slots[0][1]

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
        return response
    except requests.RequestException as e:
        print(f"Error booking slot (RequestException): {type(e).__name__}: {e}")
        return None


def sleep_until_target_time():
    if os.environ.get("SKIP_SLEEP", "false").lower() == "true":
        print("SKIP_SLEEP=true - Running immediately without waiting.")
        return

    now_ist = datetime.datetime.now(IST)
    target_ist = now_ist.replace(hour=21, minute=0, second=0, microsecond=0)

    if now_ist >= target_ist:
        print(f"Current time {now_ist.strftime('%H:%M:%S')} IST is past 21:00:00. Running immediately.")
        return

    wait_seconds = (target_ist - now_ist).total_seconds()
    print(f"Current time: {now_ist.strftime('%H:%M:%S')} IST")
    print(f"Sleeping {wait_seconds:.0f} seconds until 21:00:00 IST (9:00 PM slot)")
    time.sleep(wait_seconds)
    print(f"Woke up at {datetime.datetime.now(IST).strftime('%H:%M:%S')} IST")


def book_for_user(user):
    config = get_user_config(user)
    if not config["at_token"]:
        print(f"Skipping user '{user}': no CULT_AT_COOKIE configured")
        return None, None

    print(f"\n{'=' * 40}")
    print(f"Booking for user: {config['name']}")
    print(f"{'=' * 40}")

    headers = get_headers(config)
    center_ids = [int(x.strip()) for x in config["center_ids"].split(",") if x.strip()]
    preferred_times = [x.strip() for x in config["preferred_times"].split(",") if x.strip()]
    workout_ids = [int(x.strip()) for x in config["workout_ids"].split(",") if x.strip()]
    max_retries = int(config["max_retries"])
    retry_delay = int(config["retry_delay"])

    print(f"Centers: {center_ids}")
    print(f"Preferred times: {preferred_times}")
    print(f"Workout IDs: {workout_ids}")

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
                is_waitlist = (state == "WAITLIST_AVAILABLE")
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
                        if is_waitlist:
                            print("WAITLIST BOOKED - Slots were full, joined waitlist.")
                            booked_class_info = {
                                "workout_name": workout.get("workoutName", "Unknown"),
                                "start_time": workout.get("startTime", "Unknown"),
                                "date": workout.get("date", "Unknown"),
                                "center_id": center_id,
                                "slot_id": slot_id,
                                "available_seats": workout.get("availableSeats", 0),
                                "state": "WAITLIST_BOOKED",
                            }
                            booking_result = "waitlist"
                        else:
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
                        booking_result = "success" if not is_waitlist else "waitlist"
                        break
                    elif response.status_code == 400 and "Limit exceeded" in resp_str:
                        print("Booking limit exceeded for this slot.")
                        booking_result = "failure"
                        break
                    elif response.status_code == 401:
                        print(f"AUTH EXPIRED for user '{config['name']}'")
                        try:
                            from notify import send_notification
                            send_notification("auth_expired", None, config)
                        except Exception:
                            pass
                        return "auth_expired", None
                    else:
                        print(f"Booking failed with status {response.status_code}")

            if booking_result in ("success", "waitlist"):
                break

        if booking_result in ("success", "waitlist"):
            break

        if attempt < max_retries:
            print(f"Attempt failed. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)

    if booking_result not in ("success", "waitlist"):
        print(f"\nBooking result for '{config['name']}': {booking_result}")
        booking_result = booking_result or "failure"

    return booking_result, booked_class_info


def lambda_handler(event, context):
    print("=" * 50)
    print("Cult.fit Play Auto-Booking (AWS Lambda)")
    print("=" * 50)
    print(f"Triggered at: {datetime.datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} IST")
    print(f"Event: {json.dumps(event)}")

    sleep_until_target_time()

    user = event.get("user", "self") if isinstance(event, dict) else "self"

    booking_result, booked_class_info = book_for_user(user)
    config = get_user_config(user)

    try:
        from notify import send_notification
        send_notification(booking_result, booked_class_info, config)
    except Exception as e:
        print(f"Failed to send notification: {e}")

    return {
        "statusCode": 200 if booking_result in ("success", "waitlist") else 500,
        "body": json.dumps({
            "user": config["name"],
            "result": booking_result,
            "booked_class": booked_class_info,
        }),
    }