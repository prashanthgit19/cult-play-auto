import os
import sys
import time
import datetime
import requests

IST_OFFSET = datetime.timedelta(hours=5, minutes=30)
IST = datetime.timezone(IST_OFFSET)


def get_headers():
    st_cookie = os.environ["CULT_ST_COOKIE"]
    at_cookie = os.environ["CULT_AT_COOKIE"]
    api_key = os.environ["CULT_API_KEY"]
    cookies = {"st": st_cookie, "at": at_cookie}
    headers = {
        "apiKey": api_key,
        "Cookie": "; ".join([f"{k}={v}" for k, v in cookies.items()]),
    }
    return headers


def get_center_ids():
    raw = os.environ.get("CULT_CENTER_IDS", "20,130,212")
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def get_preferred_times():
    raw = os.environ.get("CULT_PREFERRED_TIMES", "07:30:00,08:00:00,07:00:00")
    return [x.strip() for x in raw.split(",") if x.strip()]


def get_workout_ids():
    raw = os.environ.get("CULT_WORKOUT_IDS", "69")
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
    print(f"Current time: {now_ist.strftime('%H:%M:%S')} IST")
    print(f"Sleeping {wait_seconds:.0f} seconds until 20:59:50 IST (9:00 PM slot)")
    time.sleep(wait_seconds)
    print(f"Woke up at {datetime.datetime.now(IST).strftime('%H:%M:%S')} IST")


def check_auth_expired(response):
    if response.status_code in (401, 403):
        print(f"AUTH EXPIRED: Got status {response.status_code}. Your cookies have expired.")
        print("ACTION REQUIRED: Update your GitHub Secrets (CULT_ST_COOKIE and CULT_AT_COOKIE).")
        try:
            from notify import send_notification
            send_notification("auth_expired", None)
        except Exception:
            pass
        sys.exit(2)
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("statusCode") in (401, 403):
            print(f"AUTH EXPIRED: API returned auth error code {body.get('statusCode')}. Cookies expired.")
            print("ACTION REQUIRED: Update your GitHub Secrets (CULT_ST_COOKIE and CULT_AT_COOKIE).")
            try:
                from notify import send_notification
                send_notification("auth_expired", None)
            except Exception:
                pass
            sys.exit(2)
    except ValueError:
        pass


def fetch_classes_for_center(center_id, headers):
    url = f"https://www.cult.fit/api/cult/classes?center={center_id}"
    try:
        response = requests.get(url=url, headers=headers, timeout=30)
        check_auth_expired(response)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching classes for center {center_id}: {e}")
        return None


def get_booking_date(json_data):
    try:
        return json_data["classByDateList"][-1]
    except (KeyError, IndexError) as e:
        print(f"Error getting booking date: {e}")
        return None


def find_available_class(booking_date, preferred_times, workout_ids):
    try:
        for time_slot in preferred_times:
            for class_by_time in booking_date.get("classByTimeList", []):
                for workout in class_by_time.get("classes", []):
                    if (
                        workout.get("startTime") == time_slot
                        and workout.get("availableSeats", 0) > 0
                        and workout.get("workoutId") in workout_ids
                    ):
                        return workout
        return None
    except Exception as e:
        print(f"Error finding available class: {e}")
        return None


def book_class(class_id, headers):
    url = f"https://www.cult.fit/api/cult/class/{class_id}/book"
    try:
        response = requests.post(url=url, headers=headers, timeout=30)
        return response
    except requests.RequestException as e:
        print(f"Error booking class: {e}")
        return None


def main():
    print("=" * 50)
    print("Cult.fit Auto-Booking Script")
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
            json_data = fetch_classes_for_center(center_id, headers)
            if not json_data:
                continue

            booking_date = get_booking_date(json_data)
            if not booking_date:
                continue

            workout = find_available_class(booking_date, preferred_times, workout_ids)
            if workout:
                class_id = workout["id"]
                print(f"Found available class: ID={class_id}, "
                      f"Workout={workout.get('workoutName')}, "
                      f"Time={workout.get('startTime')}, "
                      f"Seats={workout.get('availableSeats')}")

                response = book_class(class_id, headers)
                if response:
                    try:
                        resp_json = response.json()
                    except ValueError:
                        resp_json = response.text

                    print(f"Booking response: {response.status_code} - {resp_json}")

                    if response.status_code == 200:
                        print("CLASS BOOKED SUCCESSFULLY!")
                        booked_class_info = {
                            "class_id": class_id,
                            "workout_name": workout.get("workoutName", "Unknown"),
                            "start_time": workout.get("startTime", "Unknown"),
                            "center_id": center_id,
                            "available_seats": workout.get("availableSeats", 0),
                        }
                        booking_result = "success"
                        break
                    else:
                        print(f"Booking failed with status {response.status_code}")
                else:
                    print("Booking request failed - no response")
            else:
                print(f"No available class found at center {center_id}")

        if booking_result == "success":
            break

        if attempt < max_retries:
            print(f"Attempt failed. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)

    if booking_result != "success":
        print("\nAll attempts failed. Could not book a class.")
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