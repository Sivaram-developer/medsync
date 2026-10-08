# MediSync — Personal Healthcare Reminder & Adherence Assistant

> *"Don't just remind patients about tablets. Keep their entire healthcare schedule organized, track what was completed or missed, and automatically prepare a useful history for their next consultation."*

---

## 🌟 Overview & Key Features

**MediSync** is an end-to-end, full-stack healthcare reminder and adherence tracking system built according to strict medical safety principles.

### Core Pipeline
$$\text{Prescription} \longrightarrow \text{Draft Schedule} \longrightarrow \text{Patient Confirmation} \longrightarrow \text{Reminder/Alarms} \longrightarrow \text{Adherence Record} \longrightarrow \text{Consultation Report (PDF)}$$

1. **Non-Negotiable Safety Boundaries**:
   - The application is a reminder and record-keeping system, **NOT a medical advisor**.
   - It **never fabricates** medicines, dosages, frequencies, or dates.
   - It **never activates an unconfirmed OCR draft**; nothing enters the active schedule without explicit human-in-the-loop patient confirmation.
   - Shows persistent medical disclaimer: *"This app helps you follow the schedule given by your doctor. It does not provide medical advice."*

2. **Patient Onboarding & Guardian Safety Mode**:
   - Patient registration: Name, Email ID, Age, Known Allergies, 2 Emergency Contacts (Phone, Relation), and Emergency Email.
   - **Guardian Safety Mode (Age $\ge$ 60)**: Automatically enabled for elderly patients to safeguard medication adherence with active family notifications.

3. **Intelligent Human-In-The-Loop OCR / AI Extractor**:
   - Accepts image uploads, PDFs, camera captures, doctor note text, or clinical presets.
   - Categorizes items into:
     - 💊 **Medicines / Tablets / Syrups** (Strength, frequency, time slots, duration, food relation).
     - 💉 **Injections** (Dose, route, frequency, high-priority alarm).
     - 🔬 **Diagnostic Scans & Lab Tests** (Type, date, lab location, prep notes such as "Fasting 8-10 hours").
     - 🩺 **Doctor Consultations & Follow-ups** (Physician name, clinic, review date).
   - Side-by-side verification screen with confidence indicators (`High Confidence` vs `Please verify`).

4. **Multi-Attempt Escalation Engine**:
   - **Medicine Workflow**:
     $$\text{Alarm \#1} \xrightarrow{\text{no response}} \text{Alarm \#2} \xrightarrow{\text{no response}} \text{Alarm \#3} \xrightarrow{\text{no response}} \text{Emergency Escalation}$$
   - **Escalation Trigger**:
     - Voice & phone call simulation to Primary Emergency Contact (`emergency_contact_1_phone`).
     - Automatic Emergency Email & SMS notification to `emergency_email`.
     - Patient or guardian acknowledge action immediately halts escalation and records audit logs.

5. **Adherence Calculation & Consultation Report**:
   - Mathematical Adherence Formula:
     $$\text{Adherence \%} = \frac{\text{Taken} + \text{Delayed}}{\text{Total Scheduled Doses} - \text{Upcoming}} \times 100$$
   - Drug-by-drug breakdown, injection compliance, diagnostic scan status, and doctor review logs.
   - **Professional Printable A4 PDF Report** generated via ReportLab (`/api/reports/pdf/{user_id}`).

---

## 🚀 Running the Application

### Localhost URL:
**[http://127.0.0.1:8000](http://127.0.0.1:8000)**

### Quick Command to Start Server:
```powershell
cd C:\Users\ADMIN\.gemini\antigravity\scratch\medisync
python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### Running Test Suite:
```powershell
cd C:\Users\ADMIN\.gemini\antigravity\scratch\medisync
python tests/test_medisync.py
python tests/integration_test.py
```

---

## 📁 Project Structure

```
medisync/
├── backend/
│   ├── database.py         # SQLite schema & persistent connection manager
│   ├── models.py           # Pydantic schemas, validation models, enums
│   ├── ocr_engine.py       # Pluggable OCR/AI extractor with confidence scores & presets
│   ├── reminder_engine.py  # 3-Attempt escalation state machine & occurrence generator
│   ├── pdf_generator.py    # ReportLab professional A4 PDF generator
│   └── main.py             # FastAPI REST endpoints & static file server
├── static/
│   └── index.html          # Responsive Single Page Application (SPA)
├── data/
│   └── medisync.db         # Persistent SQLite database
├── uploads/                # Encrypted/isolated uploaded prescription files
└── tests/
    ├── test_medisync.py    # Unit tests for occurrence math & adherence formula
    └── integration_test.py # End-to-end integration test
```
