import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_notification(result, booked_class_info=None):
    gmail_address = os.environ.get("GMAIL_ADDRESS", "")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    notify_email = os.environ.get("NOTIFY_EMAIL", gmail_address)

    if not gmail_address or not gmail_app_password:
        print("Email credentials not configured. Skipping notification.")
        return

    if result == "success" and booked_class_info:
        subject = "Cult.fit: Class Booked Successfully!"
        body = (
            f"Your cult.fit class has been booked!\n\n"
            f"Workout: {booked_class_info.get('workout_name', 'Unknown')}\n"
            f"Time: {booked_class_info.get('start_time', 'Unknown')}\n"
            f"Center ID: {booked_class_info.get('center_id', 'Unknown')}\n"
            f"Available Seats: {booked_class_info.get('available_seats', 'Unknown')}\n"
            f"Class ID: {booked_class_info.get('class_id', 'Unknown')}\n\n"
            f"Check your cult.fit app for details."
        )
    else:
        subject = "Cult.fit: Booking FAILED"
        body = (
            f"Failed to book a cult.fit class.\n\n"
            f"All retry attempts were unsuccessful.\n"
            f"Check the GitHub Actions logs for details."
        )

    msg = MIMEMultipart()
    msg["From"] = gmail_address
    msg["To"] = notify_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, notify_email, msg.as_string())
        print(f"Notification email sent to {notify_email}")
    except Exception as e:
        print(f"Failed to send notification email: {e}")