import os
import mysql.connector
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from flask import Flask, render_template, request, redirect, session

# -------------------------
# GET DB CONNECTION (Render-safe)
# -------------------------
def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST"),
        port=os.environ.get("DB_PORT"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS"),
        database=os.environ.get("DB_NAME"),
        ssl_disabled=True   # <--- FIX: prevents Render from hanging
    )

# -------------------------
# EMAIL CONFIG (iCloud)
# -------------------------
OWNER_EMAIL = "tristianrivera@icloud.com"
OWNER_APP_PASSWORD = "isgk-upxi-bpef-gpuw"

def notify_owner(name, phone, time):
    msg = MIMEText(
        f"New appointment booked:\n\n"
        f"Name: {name}\n"
        f"Phone: {phone}\n"
        f"Time: {time}\n"
    )
    msg["Subject"] = "New Appointment Booked"
    msg["From"] = OWNER_EMAIL
    msg["To"] = OWNER_EMAIL

    with smtplib.SMTP("smtp.mail.me.com", 587) as server:
        server.starttls()
        server.login(OWNER_EMAIL, OWNER_APP_PASSWORD)
        server.send_message(msg)

# -------------------------
# FORMAT DATE/TIME
# -------------------------
def format_casual_datetime(dt_str):
    dt = datetime.fromisoformat(dt_str)

    day = dt.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

    return dt.strftime(f"%B {day}{suffix}, %Y — %I:%M %p")

# -------------------------
# FLASK APP
# -------------------------
app = Flask(__name__)
app.secret_key = "supersecretkey"

@app.route("/")
def home():
    return render_template("home.html", title="Home")

# -------------------------
# BOOKING PAGE (Render‑safe)
# -------------------------
@app.route("/book", methods=["GET", "POST"])
def book():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":
        name = request.form["name"]
        phone = request.form["phone"]
        raw_time = request.form["time"]
        slot_id = request.form["slot_id"]

        time = format_casual_datetime(raw_time)

        # Prevent double booking
        cursor.execute("SELECT * FROM appointments WHERE datetime=%s", (raw_time,))
        existing = cursor.fetchone()
        if existing:
            return "This time slot is already booked."

        # Insert appointment
        cursor.execute(
            "INSERT INTO appointments (name, phone, datetime, status) VALUES (%s, %s, %s, %s)",
            (name, phone, raw_time, "pending")
        )
        db.commit()

        # Remove slot from availability
        cursor.execute("DELETE FROM availability WHERE id=%s", (slot_id,))
        db.commit()

        # -------------------------
        # SAFE NOTIFICATION (won't crash worker)
        # -------------------------
        import threading

        def safe_notify():
            try:
                notify_owner(name, phone, time)
            except Exception as e:
                print("Notification failed:", e)

        threading.Thread(target=safe_notify).start()

        # Confirmation page
        return render_template(
            "confirmation.html",
            title="Confirmed",
            name=name,
            phone=phone,
            time=time
        )

    # GET request: show available times
    cursor.execute("SELECT * FROM availability ORDER BY date, time")
    available_times = cursor.fetchall()

    return render_template("book.html", title="Book Appointment", available=available_times)

# -------------------------
# ADMIN LOGIN
# -------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cursor.execute(
            "SELECT * FROM admin WHERE username=%s AND password=%s",
            (username, password)
        )
        admin = cursor.fetchone()

        if admin:
            session["admin"] = True
            return redirect("/admin")
        else:
            return "Invalid login"

    return render_template("admin_login.html")

# -------------------------
# ADMIN DASHBOARD
# -------------------------
@app.route("/admin")
def admin_dashboard():
    if "admin" not in session:
        return redirect("/admin/login")

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM appointments
        WHERE status != 'cancelled' AND datetime > NOW()
        ORDER BY datetime
    """)
    upcoming = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM appointments
        WHERE datetime <= NOW()
        ORDER BY datetime DESC
    """)
    past = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM appointments
        WHERE status = 'cancelled'
        ORDER BY datetime DESC
    """)
    cancelled = cursor.fetchall()

    cursor.execute("SELECT * FROM availability ORDER BY date, time")
    availability = cursor.fetchall()

    return render_template(
        "admin_dashboard.html",
        upcoming=upcoming,
        past=past,
        cancelled=cancelled,
        availability=availability
    )

# -------------------------
# ADD AVAILABILITY
# -------------------------
@app.route("/admin/add-availability", methods=["POST"])
def add_availability():
    if "admin" not in session:
        return redirect("/admin/login")

    db = get_db()
    cursor = db.cursor(dictionary=True)

    date = request.form["date"]
    time = request.form["time"]

    cursor.execute(
        "INSERT INTO availability (date, time) VALUES (%s, %s)",
        (date, time)
    )
    db.commit()

    return redirect("/admin")

# -------------------------
# DELETE AVAILABILITY
# -------------------------
@app.route("/admin/delete-availability/<int:id>")
def delete_availability(id):
    if "admin" not in session:
        return redirect("/admin/login")

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("DELETE FROM availability WHERE id=%s", (id,))
    db.commit()

    return redirect("/admin")

# -------------------------
# APPROVE APPOINTMENT
# -------------------------
@app.route("/admin/approve/<int:id>")
def approve_appt(id):
    if "admin" not in session:
        return redirect("/admin/login")

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("UPDATE appointments SET status='approved' WHERE id=%s", (id,))
    db.commit()

    return redirect("/admin")

# -------------------------
# CANCEL APPOINTMENT
# -------------------------
@app.route("/admin/cancel/<int:id>")
def cancel_appt(id):
    if "admin" not in session:
        return redirect("/admin/login")

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("UPDATE appointments SET status='cancelled' WHERE id=%s", (id,))
    db.commit()

    return redirect("/admin")

# -------------------------
# LOGOUT
# -------------------------
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/admin/login")

# -------------------------
# RUN SERVER (Render requires PORT binding)
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
