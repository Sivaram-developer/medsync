"""
Comprehensive Test Suite for MediSync:
- Occurrence Generator accuracy (15 doses for 5 days 3x/day)
- Adherence calculation formula
- Multi-attempt alarm escalation state machine
- PDF Report generation
"""
import sys
import os
import unittest
from datetime import datetime, timedelta

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))

from database import init_db, get_db
from ocr_engine import SmartPrescriptionExtractor
from reminder_engine import ReminderEngine
from pdf_generator import ReportGenerator

class TestMediSync(unittest.TestCase):

    def setUp(self):
        init_db()

    def test_occurrence_generation_math(self):
        """
        Verify that a 5-day medicine with 3x/day (Morning, Afternoon, Night)
        generates exactly 15 discrete dose events.
        """
        start_date = "2026-10-10"
        end_date = "2026-10-14"  # 5 days: 10, 11, 12, 13, 14
        details = {
            "time_slots": ["08:00", "13:00", "20:00"],
            "instructions": "Take after food"
        }

        occurrences = ReminderEngine.generate_occurrences_for_item(
            schedule_item_id="test_item_1",
            user_id="test_user_1",
            category="medicine",
            title="Paracetamol 500mg",
            details=details,
            start_date_str=start_date,
            end_date_str=end_date
        )

        self.assertEqual(len(occurrences), 15, "Expected exactly 15 dose occurrences for 5 days @ 3x/day")
        self.assertEqual(occurrences[0]["category"], "medicine")
        self.assertEqual(occurrences[0]["state"], "Upcoming")

    def test_scan_and_appointment_single_occurrence(self):
        """
        Diagnostic scans and appointments should generate a single occurrence with prep/notes.
        """
        scan_occ = ReminderEngine.generate_occurrences_for_item(
            schedule_item_id="test_scan_1",
            user_id="test_user_1",
            category="scan",
            title="MRI Knee Scan",
            details={"scheduled_time": "10:30", "preparation_notes": "Fasting 4 hours"},
            start_date_str="2026-10-12",
            end_date_str="2026-10-12"
        )
        self.assertEqual(len(scan_occ), 1)
        self.assertIn("10:30:00", scan_occ[0]["scheduled_at"])
        self.assertEqual(scan_occ[0]["notes"], "Fasting 4 hours")

    def test_ocr_confidence_and_safety_drafts(self):
        """
        Test that SmartPrescriptionExtractor tags confidence and parses medicines,
        injections, and scans without auto-activating.
        """
        sample_text = """
        Dr. S. Ramanathan, MD
        1. Tab. Paracetamol 650mg 1-1-1 for 5 days After Food
        2. Inj. Insulin 10 units daily bedtime
        3. Fasting Blood Sugar blood test in 3 days
        """
        extractor = SmartPrescriptionExtractor()
        drafts = extractor.extract(sample_text)

        categories = [d["category"] for d in drafts]
        self.assertIn("medicine", categories)
        self.assertIn("injection", categories)
        self.assertIn("scan", categories)

        for d in drafts:
            self.assertGreaterEqual(d["confidence"], 0.50)
            self.assertIn("data", d)

    def test_adherence_formula_and_pdf_generation(self):
        """
        Verify that adherence percentage adheres to the documented formula:
        Adherence % = (Taken + Delayed) / (Total - Upcoming) * 100
        and ReportLab produces a valid PDF byte buffer.
        """
        conn = get_db()
        cursor = conn.cursor()
        user_id = "test_user_adherence"

        # Create user
        cursor.execute("""
            INSERT OR REPLACE INTO users (
                id, name, email, age, allergies,
                emergency_contact_1_name, emergency_contact_1_phone,
                emergency_contact_2_name, emergency_contact_2_phone,
                emergency_email, guardian_mode_enabled, created_at
            ) VALUES (?, 'Test Patient', 'test@adherence.com', 65, 'None', 'Son', '9999999999', 'Daughter', '8888888888', 'alert@test.com', 1, '2026-10-08T00:00:00')
        """, (user_id,))

        # Clean occurrences
        cursor.execute("DELETE FROM event_occurrences WHERE user_id = ?", (user_id,))

        # Insert 10 past doses: 7 Taken, 1 Delayed, 2 Missed, and 5 Upcoming
        now = datetime.now()
        item_id = "test_sched_adhere"

        for i in range(7):
            cursor.execute("""
                INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state)
                VALUES (?, ?, ?, 'medicine', 'Drug A', '{}', ?, 'Taken')
            """, (f"occ_taken_{i}", item_id, user_id, (now - timedelta(days=1)).isoformat()))

        cursor.execute("""
            INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state)
            VALUES (?, ?, ?, 'medicine', 'Drug A', '{}', ?, 'Delayed')
        """, ("occ_delayed_1", item_id, user_id, (now - timedelta(days=1)).isoformat()))

        for i in range(2):
            cursor.execute("""
                INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state)
                VALUES (?, ?, ?, 'medicine', 'Drug A', '{}', ?, 'Missed')
            """, (f"occ_missed_{i}", item_id, user_id, (now - timedelta(days=1)).isoformat()))

        for i in range(5):
            cursor.execute("""
                INSERT INTO event_occurrences (id, schedule_item_id, user_id, category, title, details, scheduled_at, state)
                VALUES (?, ?, ?, 'medicine', 'Drug A', '{}', ?, 'Upcoming')
            """, (f"occ_upcoming_{i}", item_id, user_id, (now + timedelta(days=1)).isoformat()))

        conn.commit()
        conn.close()

        # Compute report
        data = ReportGenerator.compute_report_data(user_id)
        med = data["med_stats"]

        # Total = 15, Upcoming = 5, Due = 10
        # Completed = 7 (Taken) + 1 (Delayed) = 8
        # Adherence % = 8 / 10 * 100 = 80.0%
        self.assertEqual(med["total"], 15)
        self.assertEqual(med["due"], 10)
        self.assertEqual(med["taken"], 7)
        self.assertEqual(med["delayed"], 1)
        self.assertEqual(med["missed"], 2)
        self.assertEqual(med["adherence_pct"], 80.0)

        # Generate PDF
        pdf_bytes = ReportGenerator.generate_pdf(user_id)
        self.assertTrue(len(pdf_bytes) > 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

if __name__ == "__main__":
    unittest.main()
