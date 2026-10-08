"""
Data models and schemas for MediSync.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from enum import Enum

class UserRole(str, Enum):
    PATIENT = "patient"
    GUARDIAN = "guardian"
    DOCTOR = "doctor"

class EventCategory(str, Enum):
    MEDICINE = "medicine"
    INJECTION = "injection"
    SCAN = "scan"
    APPOINTMENT = "appointment"
    OTHER = "other"

class MedicineState(str, Enum):
    UPCOMING = "Upcoming"
    TAKEN = "Taken"
    DELAYED = "Delayed"
    MISSED = "Missed"
    UNRESOLVED = "Unresolved"

class InjectionState(str, Enum):
    UPCOMING = "Upcoming"
    COMPLETED = "Completed"
    DELAYED = "Delayed"
    MISSED = "Missed"
    UNRESOLVED = "Unresolved"

class ScanState(str, Enum):
    UPCOMING = "Upcoming"
    COMPLETED = "Completed"
    RESCHEDULED = "Rescheduled"
    MISSED = "Missed"

class AppointmentState(str, Enum):
    UPCOMING = "Upcoming"
    ATTENDED = "Attended"
    RESCHEDULED = "Rescheduled"
    MISSED = "Missed"

class UserSignUp(BaseModel):
    name: str = Field(..., min_length=2)
    email: str = Field(..., min_length=5)
    age: int = Field(..., ge=1, le=125)
    allergies: Optional[str] = ""
    emergency_contact_1_name: str = Field(..., min_length=2)
    emergency_contact_1_phone: str = Field(..., min_length=5)
    emergency_contact_1_relation: Optional[str] = "Family / Spouse"
    emergency_contact_2_name: str = Field(..., min_length=2)
    emergency_contact_2_phone: str = Field(..., min_length=5)
    emergency_contact_2_relation: Optional[str] = "Relative / Friend"
    emergency_email: str = Field(..., min_length=5)

class UserLogin(BaseModel):
    email: str = Field(..., min_length=3)

class DraftItemEdit(BaseModel):
    id: str
    category: str
    data: Dict[str, Any]
    confirmed: bool = True

class ConfirmScheduleRequest(BaseModel):
    prescription_id: str
    items: List[DraftItemEdit]
    notes: Optional[str] = ""

class EventActionRequest(BaseModel):
    occurrence_id: str
    action: str  # "take", "complete", "attend", "snooze", "skip", "reschedule"
    notes: Optional[str] = ""
    new_time: Optional[str] = None  # for reschedule

class ManualEntryRequest(BaseModel):
    user_id: str
    category: str
    title: str
    details: Dict[str, Any]
    start_date: str
    end_date: str
    time_slots: List[str]  # e.g., ["08:00", "13:00", "20:00"]
