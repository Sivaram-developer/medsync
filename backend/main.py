"""
MediSync - Personal Healthcare Reminder & Adherence Assistant
Full-stack FastAPI Application.
"""
import os
import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, get_db
from models import (
    UserSignUp, UserLogin, ConfirmScheduleRequest,
    EventActionRequest, ManualEntryRequest
)
from ocr_engine import SmartPrescriptionExtractor
from reminder_engine import ReminderEngine
from pdf_generator import ReportGenerator

app = FastAPI(title="MediSync API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/", response_class=HTMLResponse)
def get_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>MediSync is running. Please check static/index.html</h1>"

# ----------------- AUTHENTICATION & USER PROFILE -----------------

@app.post("/api/auth/signup")
def signup(data: UserSignUp):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (data.email,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    user_id = str(uuid.uuid4())
    guardian_mode = 1 if data.age >= 60 else 0
    now_str = datetime.now().isoformat()

    cursor.execute("""
        INSERT INTO users (
            id, name, email, age, allergies,
            emergency_contact_1_name, emergency_contact_1_phone, emergency_contact_1_relation,
            emergency_contact_2_name, emergency_contact_2_phone, emergency_contact_2_relation,
            emergency_email, guardian_mode_enabled, guardian_acknowledged, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, data.name, data.email, data.age, data.allergies or "",
        data.emergency_contact_1_name, data.emergency_contact_1_phone, data.emergency_contact_1_relation,
        data.emergency_contact_2_name, data.emergency_contact_2_phone, data.emergency_contact_2_relation,
        data.emergency_email, guardian_mode, 0, now_str
    ))

    # Log audit
    cursor.execute("""
        INSERT INTO audit_logs (id, user_id, actor, action, entity_type, entity_id, details, created_at)
        VALUES (?, ?, 'patient', 'user_signup', 'user', ?, ?, ?)
    """, (str(uuid.uuid4()), user_id, user_id, f"User registered with Guardian Mode: {bool(guardian_mode)}", now_str))

    conn.commit()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = dict(cursor.fetchone())
    conn.close()

    return {"success": True, "user": user}

@app.post("/api/auth/login")
def login(data: UserLogin):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (data.email.strip(),))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Account not found. Please sign up first.")

    user = dict(row)
    conn.close()
    return {"success": True, "user": user}

@app.get("/api/auth/me/{user_id}")
def get_user_profile(user_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": dict(row)}

# ----------------- PRESCRIPTION UPLOAD & AI OCR EXTRACTION -----------------

@app.post("/api/prescriptions/upload")
async def upload_prescription(
    user_id: str = Form(...),
    preset_key: Optional[str] = Form(None),
    raw_text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    """
    Step 1 & 2: Prescription Upload and Human-in-the-loop Draft Extraction.
    Nothing activates until patient confirms!
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    prescription_id = str(uuid.uuid4())
    now_str = datetime.now().isoformat()
    saved_file_path = ""
    file_name = "Prescription"
    source = "manual"
    doctor_clinic = "Consulting Clinic"

    text_to_parse = ""

    if preset_key:
        preset_info = SmartPrescriptionExtractor.get_sample_preset(preset_key)
        text_to_parse = preset_info["raw_text"]
        doctor_clinic = preset_info["doctor_clinic"]
        source = f"preset_{preset_key}"
        file_name = f"Preset_{preset_key}.pdf"
    elif file and file.filename:
        file_name = file.filename
        source = "file_upload"
        ext = os.path.splitext(file.filename)[1]
        saved_file_path = os.path.join(UPLOADS_DIR, f"{prescription_id}{ext}")
        file_bytes = await file.read()
        with open(saved_file_path, "wb") as f_out:
            f_out.write(file_bytes)

        # For text or parsed representation
        if raw_text and raw_text.strip():
            text_to_parse = raw_text
        else:
            # Fallback simulated OCR if text not directly sent with file
            preset_info = SmartPrescriptionExtractor.get_sample_preset("regimen_1")
            text_to_parse = preset_info["raw_text"]
            doctor_clinic = preset_info["doctor_clinic"]
    elif raw_text and raw_text.strip():
        text_to_parse = raw_text
        source = "direct_entry"
    else:
        # Default preset if nothing provided
        preset_info = SmartPrescriptionExtractor.get_sample_preset("regimen_1")
        text_to_parse = preset_info["raw_text"]
        doctor_clinic = preset_info["doctor_clinic"]

    # Save Prescription record
    cursor.execute("""
        INSERT INTO prescriptions (id, user_id, file_path, file_name, source, uploaded_at, extraction_status, doctor_clinic)
        VALUES (?, ?, ?, ?, ?, ?, 'draft_ready', ?)
    """, (prescription_id, user_id, saved_file_path, file_name, source, now_str, doctor_clinic))

    # Run Smart Extractor
    extractor = SmartPrescriptionExtractor()
    extracted_items = extractor.extract(text_to_parse, file_name)

    # Save Extracted Draft Items to DB
    for item in extracted_items:
        cursor.execute("""
            INSERT INTO extracted_items (id, prescription_id, category, raw_data, confidence, is_verified, confirmed_data)
            VALUES (?, ?, ?, ?, ?, 0, NULL)
        """, (item["id"], prescription_id, item["category"], json.dumps(item["data"]), item["confidence"]))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "prescription_id": prescription_id,
        "doctor_clinic": doctor_clinic,
        "source_text": text_to_parse,
        "draft_items": extracted_items
    }

# ----------------- SCHEDULE CONFIRMATION (HUMAN-IN-THE-LOOP) -----------------

@app.post("/api/prescriptions/confirm")
def confirm_schedule(req: ConfirmScheduleRequest):
    """
    Step 3: Patient reviews and confirms draft items.
    Converts confirmed items into ScheduleItems and expands exact event occurrences!
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM prescriptions WHERE id = ?", (req.prescription_id,))
    presc_row = cursor.fetchone()
    if not presc_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Prescription not found")
    presc = dict(presc_row)
    user_id = presc["user_id"]

    now = datetime.now()
    now_str = now.isoformat()
    total_occurrences_created = 0

    for item in req.items:
        if not item.confirmed:
            continue

        item_id = str(uuid.uuid4())
        data = item.data
        title = data.get("title") or data.get("medicine_name") or "Healthcare Event"
        category = item.category

        days = int(data.get("days", 5))
        start_date = now
        end_date = now + timedelta(days=days - 1)

        # For Scan or Appointment with offset
        if category in ["scan", "appointment"]:
            offset = int(data.get("scheduled_day_offset", 2))
            start_date = now + timedelta(days=offset)
            end_date = start_date

        cursor.execute("""
            INSERT INTO schedule_items (id, user_id, prescription_id, category, title, details, recurrence, start_date, end_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'daily', ?, ?, 'active', ?)
        """, (
            item_id, user_id, req.prescription_id, category, title,
            json.dumps(data), start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), now_str
        ))

        # Generate individual discrete occurrences
        occurrences = ReminderEngine.generate_occurrences_for_item(
            schedule_item_id=item_id,
            user_id=user_id,
            category=category,
            title=title,
            details=data,
            start_date_str=start_date.strftime("%Y-%m-%d"),
            end_date_str=end_date.strftime("%Y-%m-%d")
        )

        for occ in occurrences:
            cursor.execute("""
                INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state, attempt_count, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (
                occ["id"], occ["schedule_item_id"], occ["user_id"],
                occ["category"], occ["title"], occ["details"],
                occ["scheduled_at"], occ["state"], occ["notes"]
            ))
            total_occurrences_created += 1

    # Update prescription extraction status to confirmed
    cursor.execute("UPDATE prescriptions SET extraction_status = 'confirmed' WHERE id = ?", (req.prescription_id,))

    # Log audit
    cursor.execute("""
        INSERT INTO audit_logs (id, user_id, actor, action, entity_type, entity_id, details, created_at)
        VALUES (?, ?, 'patient', 'confirm_schedule', 'prescription', ?, ?, ?)
    """, (str(uuid.uuid4()), user_id, req.prescription_id, f"Patient confirmed schedule with {total_occurrences_created} occurrences generated", now_str))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": f"Schedule successfully activated! Generated {total_occurrences_created} discrete healthcare events.",
        "occurrences_created": total_occurrences_created
    }

# ----------------- TODAY'S SCHEDULE & TIMELINE -----------------

@app.get("/api/schedule/today/{user_id}")
def get_today_schedule(user_id: str):
    conn = get_db()
    cursor = conn.cursor()

    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT * FROM event_occurrences
        WHERE user_id = ? AND scheduled_at LIKE ?
        ORDER BY scheduled_at ASC
    """, (user_id, f"{today_str}%"))

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Parse JSON details
    for r in rows:
        try:
            r["details"] = json.loads(r["details"])
        except Exception:
            pass

    medicines = [r for r in rows if r["category"] == "medicine"]
    injections = [r for r in rows if r["category"] == "injection"]
    scans = [r for r in rows if r["category"] == "scan"]
    appointments = [r for r in rows if r["category"] == "appointment"]

    return {
        "today_date": today_str,
        "total": len(rows),
        "medicines": medicines,
        "injections": injections,
        "scans": scans,
        "appointments": appointments
    }

@app.get("/api/schedule/timeline/{user_id}")
def get_timeline(
    user_id: str,
    category: Optional[str] = None,
    state: Optional[str] = None
):
    conn = get_db()
    cursor = conn.cursor()

    query = "SELECT * FROM event_occurrences WHERE user_id = ?"
    params = [user_id]

    if category and category != "all":
        query += " AND category = ?"
        params.append(category)

    if state and state != "all":
        query += " AND state = ?"
        params.append(state)

    query += " ORDER BY scheduled_at ASC"

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in rows:
        try:
            r["details"] = json.loads(r["details"])
        except Exception:
            pass

    return {"total": len(rows), "events": rows}

# ----------------- EVENT INTERACTIONS & ALARM ACTIONS -----------------

@app.post("/api/events/action")
def take_event_action(req: EventActionRequest):
    try:
        res = ReminderEngine.process_action(
            occurrence_id=req.occurrence_id,
            action=req.action,
            notes=req.notes or "",
            new_time=req.new_time
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/events/simulate-alarm")
def simulate_alarm(
    occurrence_id: str = Form(...),
    attempt: int = Form(1)
):
    """
    Simulates Alarm #1, #2, or #3.
    On attempt 3, escalates to Emergency Call & Email!
    """
    try:
        res = ReminderEngine.trigger_alarm_simulation(occurrence_id, attempt)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/events/simulate-full-escalation")
def simulate_full_escalation(occurrence_id: str = Form(...)):
    """
    Direct simulation trigger: Simulates 3 missed alarms and fires
    full emergency call & email escalation to the 2 emergency contacts!
    """
    try:
        res = ReminderEngine.trigger_alarm_simulation(occurrence_id, 3)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ----------------- REPORTS & ANALYTICS -----------------

@app.get("/api/reports/summary/{user_id}")
def get_report_summary(user_id: str):
    try:
        summary = ReportGenerator.compute_report_data(user_id)
        return {"success": True, "report": summary}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/reports/pdf/{user_id}")
def download_pdf_report(user_id: str):
    try:
        pdf_bytes = ReportGenerator.generate_pdf(user_id)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=MediSync_Consultation_Report_{user_id[:8]}.pdf"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ----------------- SEED DEMO DATA HELPER -----------------

@app.post("/api/seed-demo/{user_id}")
def seed_demo_data(user_id: str):
    """
    Seeds a rich realistic healthcare schedule with varied adherence history
    (e.g., Taken on time, Delayed, Missed, Upcoming, Injections, Scans, Consultations, Escalation)
    so the doctor consultation report and dashboard look comprehensive right away!
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    user = dict(user_row)

    # Clean existing occurrences for clean demo experience
    cursor.execute("DELETE FROM event_occurrences WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM schedule_items WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM escalation_logs WHERE user_id = ?", (user_id,))

    now = datetime.now()

    # 1. Paracetamol 650mg (5 days, 3x/day -> 15 doses)
    p_item_id = str(uuid.uuid4())
    cursor.execute("""
        INSERT INTO schedule_items (id, user_id, category, title, details, recurrence, start_date, end_date, status, created_at)
        VALUES (?, ?, 'medicine', 'Paracetamol 650mg', ?, 'daily', ?, ?, 'active', ?)
    """, (p_item_id, user_id, json.dumps({
        "medicine_name": "Paracetamol", "strength": "650mg", "form": "Tablet",
        "time_slots": ["08:00", "13:00", "20:00"], "food_relation": "After Food", "days": 5
    }), (now - timedelta(days=2)).strftime("%Y-%m-%d"), (now + timedelta(days=2)).strftime("%Y-%m-%d"), now.isoformat()))

    # Days -2, -1, 0, +1, +2
    slots = ["08:00", "13:00", "20:00"]
    for day_offset in range(-2, 3):
        day_date = now.date() + timedelta(days=day_offset)
        for idx, s in enumerate(slots):
            h, m = map(int, s.split(":"))
            sched_dt = datetime(day_date.year, day_date.month, day_date.day, h, m)

            # Determine realistic past vs future state
            if day_offset < 0:
                if idx == 0:
                    st = "Taken"
                    comp = sched_dt + timedelta(minutes=10)
                elif idx == 1:
                    st = "Delayed"
                    comp = sched_dt + timedelta(minutes=45)
                else:
                    st = "Missed"
                    comp = None
            elif day_offset == 0:
                if h < now.hour:
                    st = "Taken"
                    comp = sched_dt + timedelta(minutes=15)
                else:
                    st = "Upcoming"
                    comp = None
            else:
                st = "Upcoming"
                comp = None

            cursor.execute("""
                INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state, completed_at, attempt_count, notes)
                VALUES (?, ?, ?, 'medicine', 'Paracetamol 650mg', ?, ?, ?, ?, ?, 'Take with water after food')
            """, (str(uuid.uuid4()), p_item_id, user_id, json.dumps({"strength": "650mg", "form": "Tablet"}),
                  sched_dt.isoformat(), st, comp.isoformat() if comp else None, 1 if st != "Upcoming" else 0))

    # 2. Pantoprazole 40mg (1x/day morning before breakfast)
    panto_id = str(uuid.uuid4())
    cursor.execute("""
        INSERT INTO schedule_items (id, user_id, category, title, details, recurrence, start_date, end_date, status, created_at)
        VALUES (?, ?, 'medicine', 'Pantoprazole 40mg', ?, 'daily', ?, ?, 'active', ?)
    """, (panto_id, user_id, json.dumps({
        "medicine_name": "Pantoprazole", "strength": "40mg", "form": "Tablet",
        "time_slots": ["07:30"], "food_relation": "Before Food", "days": 5
    }), (now - timedelta(days=2)).strftime("%Y-%m-%d"), (now + timedelta(days=2)).strftime("%Y-%m-%d"), now.isoformat()))

    for day_offset in range(-2, 3):
        day_date = now.date() + timedelta(days=day_offset)
        sched_dt = datetime(day_date.year, day_date.month, day_date.day, 7, 30)
        st = "Taken" if day_offset <= 0 else "Upcoming"
        comp = (sched_dt + timedelta(minutes=5)) if day_offset <= 0 else None
        cursor.execute("""
            INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state, completed_at, attempt_count, notes)
            VALUES (?, ?, ?, 'medicine', 'Pantoprazole 40mg', ?, ?, ?, ?, 1, 'Empty stomach in morning')
        """, (str(uuid.uuid4()), panto_id, user_id, json.dumps({"strength": "40mg"}), sched_dt.isoformat(), st, comp.isoformat() if comp else None))

    # 3. Injection Insulin / B12
    inj_id = str(uuid.uuid4())
    inj_sched = (now + timedelta(hours=3)).replace(minute=0, second=0)
    cursor.execute("""
        INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state, attempt_count, notes)
        VALUES (?, ?, ?, 'injection', 'Inj. Lantus Insulin 10 Units', ?, ?, 'Upcoming', 0, 'Subcutaneous bedtime injection')
    """, (str(uuid.uuid4()), inj_id, user_id, json.dumps({"dosage": "10 Units", "route": "Subcutaneous"}), inj_sched.isoformat()))

    # 4. Diagnostic Blood Test
    scan_id = str(uuid.uuid4())
    scan_sched = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0)
    cursor.execute("""
        INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state, attempt_count, notes)
        VALUES (?, ?, ?, 'scan', 'Fasting Blood Sugar & Lipid Profile', ?, ?, 'Upcoming', 0, 'Strict overnight fasting (10 hours required). Water allowed.')
    """, (str(uuid.uuid4()), scan_id, user_id, json.dumps({"scan_type": "Blood Test", "lab_location": "Clinical Diagnostics Lab"}), scan_sched.isoformat()))

    # 5. Doctor Consultation Follow-up
    appt_id = str(uuid.uuid4())
    appt_sched = (now + timedelta(days=3)).replace(hour=11, minute=0, second=0)
    cursor.execute("""
        INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state, attempt_count, notes)
        VALUES (?, ?, ?, 'appointment', 'Follow-up: Dr. S. Ramanathan, MD', ?, ?, 'Upcoming', 0, 'Review fever & blood report. Bring previous prescriptions.')
    """, (str(uuid.uuid4()), appt_id, user_id, json.dumps({"doctor_name": "Dr. S. Ramanathan", "clinic": "Apollo Clinic"}), appt_sched.isoformat()))

    # Add 1 Sample Escalation Record
    esc_time = (now - timedelta(days=1, hours=2)).isoformat()
    cursor.execute("""
        INSERT INTO escalation_logs (id, occurrence_id, user_id, escalation_type, target_name, target_contact, message, status, created_at)
        VALUES (?, ?, ?, 'EMERGENCY_CALL', ?, ?, ?, 'ANSWERED_BY_GUARDIAN', ?)
    """, (
        str(uuid.uuid4()), p_item_id, user_id,
        user["emergency_contact_1_name"], user["emergency_contact_1_phone"],
        f"Simulated alert: 3 consecutive alarms unanswered for Paracetamol 650mg. Guardian acknowledged and assisted patient.",
        esc_time
    ))

    conn.commit()
    conn.close()

    return {"success": True, "message": "Demo healthcare schedule and historical records seeded successfully!"}
