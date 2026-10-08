"""
Reminder Engine, Occurrence Generator, and Multi-Attempt Escalation State Machine.
"""
import uuid
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from database import get_db

class ReminderEngine:
    """
    Manages schedule expansion into individual event occurrences,
    alarm attempts, state machine transitions, and emergency escalations.
    """

    @classmethod
    def generate_occurrences_for_item(
        cls,
        schedule_item_id: str,
        user_id: str,
        category: str,
        title: str,
        details: Dict[str, Any],
        start_date_str: str,
        end_date_str: str
    ) -> List[Dict[str, Any]]:
        occurrences = []
        start_dt = datetime.fromisoformat(start_date_str.replace("Z", ""))
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", ""))

        time_slots = details.get("time_slots", ["08:00"])
        current_dt = start_dt

        # For single-date events like Scans or Appointments
        if category in ["scan", "appointment"]:
            sched_time = details.get("scheduled_time", "09:00")
            h, m = map(int, sched_time.split(":"))
            event_time = current_dt.replace(hour=h, minute=m, second=0, microsecond=0)
            occurrences.append({
                "id": str(uuid.uuid4()),
                "schedule_item_id": schedule_item_id,
                "user_id": user_id,
                "category": category,
                "title": title,
                "details": json.dumps(details),
                "scheduled_at": event_time.isoformat(),
                "state": "Upcoming",
                "attempt_count": 0,
                "escalated": 0,
                "notes": details.get("preparation_notes") or details.get("notes") or ""
            })
            return occurrences

        # For recurring events like Medicines or Injections
        days_span = (end_dt.date() - start_dt.date()).days + 1
        if days_span < 1:
            days_span = 1

        for day_offset in range(days_span):
            day = start_dt.date() + timedelta(days=day_offset)
            for slot in time_slots:
                h, m = map(int, slot.split(":"))
                slot_time = datetime(day.year, day.month, day.day, h, m, 0)
                occurrences.append({
                    "id": str(uuid.uuid4()),
                    "schedule_item_id": schedule_item_id,
                    "user_id": user_id,
                    "category": category,
                    "title": title,
                    "details": json.dumps(details),
                    "scheduled_at": slot_time.isoformat(),
                    "state": "Upcoming",
                    "attempt_count": 0,
                    "escalated": 0,
                    "notes": details.get("instructions", "")
                })

        return occurrences

    @classmethod
    def process_action(
        cls,
        occurrence_id: str,
        action: str,
        notes: str = "",
        new_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Applies a state transition with strict healthcare rules:
        - Medicine: Take (Taken / Delayed based on timestamp), Snooze, Skip (Missed)
        - Injection: Complete (Completed / Delayed), Skip (Missed)
        - Scan: Complete (Completed), Reschedule, Miss
        - Appointment: Attend (Attended), Reschedule, Miss
        """
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM event_occurrences WHERE id = ?", (occurrence_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Occurrence {occurrence_id} not found")

        occ = dict(row)
        cat = occ["category"]
        now = datetime.now()
        now_str = now.isoformat()
        sched_dt = datetime.fromisoformat(occ["scheduled_at"])

        old_state = occ["state"]
        new_state = old_state
        completed_at = occ["completed_at"]
        rescheduled_to = None

        if cat == "medicine":
            if action in ["take", "taken"]:
                # If marked within 30 min of scheduled time -> Taken, else Delayed
                delay_minutes = (now - sched_dt).total_seconds() / 60
                if delay_minutes > 30:
                    new_state = "Delayed"
                else:
                    new_state = "Taken"
                completed_at = now_str
            elif action in ["skip", "miss"]:
                new_state = "Missed"
            elif action == "snooze":
                # Advance scheduled_at by 10 minutes
                new_sched = now + timedelta(minutes=10)
                cursor.execute(
                    "UPDATE event_occurrences SET scheduled_at = ?, attempt_count = attempt_count + 1 WHERE id = ?",
                    (new_sched.isoformat(), occurrence_id)
                )
                cls._log_audit(conn, occ["user_id"], "patient", "snooze_reminder", "event_occurrence", occurrence_id,
                               f"Snoozed alarm to {new_sched.strftime('%H:%M')}")
                conn.commit()
                conn.close()
                return {"success": True, "occurrence_id": occurrence_id, "state": old_state, "message": f"Snoozed for 10 minutes (Next: {new_sched.strftime('%I:%M %p')})"}

        elif cat == "injection":
            if action in ["complete", "completed"]:
                delay_minutes = (now - sched_dt).total_seconds() / 60
                new_state = "Delayed" if delay_minutes > 60 else "Completed"
                completed_at = now_str
            elif action in ["skip", "miss"]:
                new_state = "Missed"

        elif cat == "scan":
            if action in ["complete", "completed"]:
                new_state = "Completed"
                completed_at = now_str
            elif action == "reschedule" and new_time:
                new_state = "Rescheduled"
                rescheduled_to = new_time
            elif action in ["skip", "miss"]:
                new_state = "Missed"

        elif cat == "appointment":
            if action in ["attend", "attended"]:
                new_state = "Attended"
                completed_at = now_str
            elif action == "reschedule" and new_time:
                new_state = "Rescheduled"
                rescheduled_to = new_time
            elif action in ["skip", "miss"]:
                new_state = "Missed"

        cursor.execute("""
            UPDATE event_occurrences
            SET state = ?, completed_at = ?, notes = ?, rescheduled_to = ?
            WHERE id = ?
        """, (new_state, completed_at, notes or occ["notes"], rescheduled_to, occurrence_id))

        cls._log_audit(
            conn,
            occ["user_id"],
            "patient",
            f"update_status_{action}",
            "event_occurrence",
            occurrence_id,
            f"State changed from {old_state} to {new_state}"
        )

        conn.commit()
        conn.close()

        return {
            "success": True,
            "occurrence_id": occurrence_id,
            "old_state": old_state,
            "new_state": new_state,
            "completed_at": completed_at
        }

    @classmethod
    def trigger_alarm_simulation(cls, occurrence_id: str, attempt: int = 1) -> Dict[str, Any]:
        """
        Simulates alarm attempt (1, 2, or 3).
        If attempt reaches 3 without response, triggers emergency escalation!
        """
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM event_occurrences WHERE id = ?", (occurrence_id,))
        occ_row = cursor.fetchone()
        if not occ_row:
            conn.close()
            raise ValueError("Occurrence not found")

        occ = dict(occ_row)
        cursor.execute("SELECT * FROM users WHERE id = ?", (occ["user_id"],))
        user = dict(cursor.fetchone())

        now_str = datetime.now().isoformat()
        escalation_triggered = False
        escalation_data = None

        if attempt < 3:
            cursor.execute("""
                UPDATE event_occurrences
                SET attempt_count = ?, last_attempt_at = ?
                WHERE id = ?
            """, (attempt, now_str, occurrence_id))
            message = f"Alarm #{attempt} triggered for {occ['title']}. Awaiting response."
        else:
            # 3rd attempt reached without response -> ESCALATION!
            escalation_triggered = True
            cursor.execute("""
                UPDATE event_occurrences
                SET attempt_count = 3, state = 'Unresolved', escalated = 1, escalated_at = ?, last_attempt_at = ?
                WHERE id = ?
            """, (now_str, now_str, occurrence_id))

            # Log Call Escalation to Primary Contact
            call_id = str(uuid.uuid4())
            call_msg = (
                f"URGENT: Patient {user['name']} has not responded to 3 alarms for {occ['title']} "
                f"scheduled at {occ['scheduled_at']}. Please check immediately!"
            )
            cursor.execute("""
                INSERT INTO escalation_logs
                (id, occurrence_id, user_id, escalation_type, target_name, target_contact, message, status, created_at)
                VALUES (?, ?, ?, 'EMERGENCY_CALL', ?, ?, ?, 'DISPATCHED', ?)
            """, (call_id, occurrence_id, user["id"], user["emergency_contact_1_name"],
                  user["emergency_contact_1_phone"], call_msg, now_str))

            # Log Email / Notification Fallback
            email_id = str(uuid.uuid4())
            email_msg = (
                f"URGENT MEDISYNC ALERT: Unresolved medication reminder for {user['name']}. "
                f"Item: {occ['title']}. 3 Alarms Missed."
            )
            cursor.execute("""
                INSERT INTO escalation_logs
                (id, occurrence_id, user_id, escalation_type, target_name, target_contact, message, status, created_at)
                VALUES (?, ?, ?, 'EMERGENCY_EMAIL', ?, ?, ?, 'SENT', ?)
            """, (email_id, occurrence_id, user["id"], "Emergency Notification Dispatch",
                  user["emergency_email"], email_msg, now_str))

            escalation_data = {
                "patient_name": user["name"],
                "item_title": occ["title"],
                "emergency_contact_1": f"{user['emergency_contact_1_name']} ({user['emergency_contact_1_phone']})",
                "emergency_contact_2": f"{user['emergency_contact_2_name']} ({user['emergency_contact_2_phone']})",
                "emergency_email": user["emergency_email"],
                "call_message": call_msg,
                "email_message": email_msg
            }
            message = f"Max alarm attempts reached (3/3). Emergency Call & Notification Escalation dispatched!"

        cls._log_audit(
            conn,
            user["id"],
            "system",
            f"alarm_attempt_{attempt}",
            "event_occurrence",
            occurrence_id,
            message
        )

        conn.commit()
        conn.close()

        return {
            "success": True,
            "occurrence_id": occurrence_id,
            "attempt": attempt,
            "escalation_triggered": escalation_triggered,
            "escalation_data": escalation_data,
            "message": message
        }

    @classmethod
    def _log_audit(cls, conn, user_id: str, actor: str, action: str, entity_type: str, entity_id: str, details: str):
        conn.execute("""
            INSERT INTO audit_logs (id, user_id, actor, action, entity_type, entity_id, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(uuid.uuid4()), user_id, actor, action, entity_type, entity_id, details, datetime.now().isoformat()))
