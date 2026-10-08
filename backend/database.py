"""
Database connection and schema management for MediSync.
Uses SQLite for robust local persistence.
"""
import sqlite3
import json
import os
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "medisync.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        age INTEGER NOT NULL,
        allergies TEXT DEFAULT '',
        emergency_contact_1_name TEXT NOT NULL,
        emergency_contact_1_phone TEXT NOT NULL,
        emergency_contact_1_relation TEXT DEFAULT 'Family',
        emergency_contact_2_name TEXT NOT NULL,
        emergency_contact_2_phone TEXT NOT NULL,
        emergency_contact_2_relation TEXT DEFAULT 'Emergency Contact',
        emergency_email TEXT NOT NULL,
        guardian_mode_enabled INTEGER DEFAULT 0,
        guardian_acknowledged INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """)

    # Prescriptions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS prescriptions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        file_path TEXT,
        file_name TEXT,
        source TEXT NOT NULL,
        uploaded_at TEXT NOT NULL,
        extraction_status TEXT NOT NULL,
        doctor_clinic TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        FOREIGN KEY (user_id) REFERENCES users (id)
    );
    """)

    # Extracted Items (drafts pending review)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS extracted_items (
        id TEXT PRIMARY KEY,
        prescription_id TEXT NOT NULL,
        category TEXT NOT NULL,
        raw_data TEXT NOT NULL,
        confidence REAL NOT NULL,
        is_verified INTEGER DEFAULT 0,
        confirmed_data TEXT DEFAULT NULL,
        FOREIGN KEY (prescription_id) REFERENCES prescriptions (id)
    );
    """)

    # Schedule Items (confirmed master schedule)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schedule_items (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        prescription_id TEXT,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        details TEXT NOT NULL,
        recurrence TEXT DEFAULT 'daily',
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    );
    """)

    # Event Occurrences (discrete individual dose/event instances)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS event_occurrences (
        id TEXT PRIMARY KEY,
        schedule_item_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        details TEXT NOT NULL,
        scheduled_at TEXT NOT NULL,
        state TEXT NOT NULL,
        completed_at TEXT DEFAULT NULL,
        attempt_count INTEGER DEFAULT 0,
        last_attempt_at TEXT DEFAULT NULL,
        escalated INTEGER DEFAULT 0,
        escalated_at TEXT DEFAULT NULL,
        notes TEXT DEFAULT '',
        rescheduled_to TEXT DEFAULT NULL,
        FOREIGN KEY (schedule_item_id) REFERENCES schedule_items (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    );
    """)

    # Escalation and Notification Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS escalation_logs (
        id TEXT PRIMARY KEY,
        occurrence_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        escalation_type TEXT NOT NULL,
        target_name TEXT NOT NULL,
        target_contact TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (occurrence_id) REFERENCES event_occurrences (id)
    );
    """)

    # Audit Trail (immutable)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        details TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", DB_PATH)
