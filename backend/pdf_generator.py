"""
Professional Healthcare Activity Report & Consultation Report Generator for MediSync.
Calculates mathematical adherence metrics and produces an executive, printable A4 PDF.
"""
import io
import json
from datetime import datetime
from typing import Dict, Any, List
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from database import get_db

class NumberedCanvas(canvas.Canvas):
    """Adds professional page numbers and running footer."""
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        footer_text = f"MediSync Consultation Report  |  Page {self._pageNumber} of {page_count}"
        self.drawRightString(A4[0] - 36, 22, footer_text)
        disclaimer = "CONFIDENTIAL PATIENT ADHERENCE RECORD - Factual data for clinical consultation."
        self.drawString(36, 22, disclaimer)
        self.restoreState()

class ReportGenerator:

    @classmethod
    def compute_report_data(cls, user_id: str) -> Dict[str, Any]:
        """Queries database and computes factual adherence statistics and table rows."""
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            conn.close()
            raise ValueError("User not found")
        user = dict(user_row)

        cursor.execute("SELECT * FROM event_occurrences WHERE user_id = ? ORDER BY scheduled_at ASC", (user_id,))
        all_occurrences = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM escalation_logs WHERE user_id = ? ORDER BY created_at ASC", (user_id,))
        escalations = [dict(r) for r in cursor.fetchall()]

        conn.close()

        # Parse JSON details for each occurrence
        for occ in all_occurrences:
            if isinstance(occ.get("details"), str):
                try:
                    occ["details_parsed"] = json.loads(occ["details"])
                except Exception:
                    occ["details_parsed"] = {}
            else:
                occ["details_parsed"] = occ.get("details") or {}

        # Categorize
        med_events = [e for e in all_occurrences if e["category"] == "medicine"]
        inj_events = [e for e in all_occurrences if e["category"] == "injection"]
        scan_events = [e for e in all_occurrences if e["category"] == "scan"]
        appt_events = [e for e in all_occurrences if e["category"] == "appointment"]

        # Medicine Adherence Statistics
        total_med = len(med_events)
        taken_med = sum(1 for e in med_events if e["state"] == "Taken")
        delayed_med = sum(1 for e in med_events if e["state"] == "Delayed")
        missed_med = sum(1 for e in med_events if e["state"] == "Missed")
        unresolved_med = sum(1 for e in med_events if e["state"] == "Unresolved")
        upcoming_med = sum(1 for e in med_events if e["state"] == "Upcoming")

        completed_doses = taken_med + delayed_med
        due_doses = total_med - upcoming_med
        adherence_pct = round((completed_doses / due_doses * 100), 1) if due_doses > 0 else 100.0

        # Enriched Drug-wise Breakdown
        drug_stats = {}
        for e in med_events:
            t = e["title"]
            d = e["details_parsed"]
            st = e["state"]

            if t not in drug_stats:
                dosage_str = d.get("strength") or d.get("dosage") or ""
                freq_str = d.get("frequency") or ""
                food_str = d.get("food_relation") or ""
                regimen_info = f"{dosage_str} ({freq_str}, {food_str})".strip(" ,()")
                drug_stats[t] = {
                    "medicine_name": t,
                    "regimen": regimen_info or "As prescribed",
                    "total": 0,
                    "taken": 0,
                    "delayed": 0,
                    "missed": 0,
                    "unresolved": 0,
                    "upcoming": 0,
                    "delay_dates": set(),
                    "miss_dates": set()
                }

            drug_stats[t]["total"] += 1
            date_key = e["scheduled_at"][:10] if e.get("scheduled_at") else ""

            if st == "Taken":
                drug_stats[t]["taken"] += 1
            elif st == "Delayed":
                drug_stats[t]["delayed"] += 1
                if date_key:
                    drug_stats[t]["delay_dates"].add(date_key)
            elif st == "Missed":
                drug_stats[t]["missed"] += 1
                if date_key:
                    drug_stats[t]["miss_dates"].add(date_key)
            elif st == "Unresolved":
                drug_stats[t]["unresolved"] += 1
                if date_key:
                    drug_stats[t]["miss_dates"].add(date_key)
            elif st == "Upcoming":
                drug_stats[t]["upcoming"] += 1

        # Convert date sets to count for JSON serialization
        for t, s in drug_stats.items():
            s["days_delayed_count"] = len(s["delay_dates"])
            s["days_missed_count"] = len(s["miss_dates"])
            s.pop("delay_dates", None)
            s.pop("miss_dates", None)
            due = s["total"] - s["upcoming"]
            s["adherence_rate"] = round(((s["taken"] + s["delayed"]) / due * 100), 1) if due > 0 else 100.0

        # Detailed Procedures & Appointments Table List
        procedures_list = []
        for e in (inj_events + scan_events + appt_events):
            cat_label = "💉 Injection" if e["category"] == "injection" else ("🔬 Scan / Test" if e["category"] == "scan" else "🩺 Consultation")
            sched_dt = e["scheduled_at"].replace("T", " ")[:16]
            comp_dt = e["completed_at"].replace("T", " ")[:16] if e.get("completed_at") else "--"
            instructions = e.get("notes") or e["details_parsed"].get("preparation_notes") or e["details_parsed"].get("instructions") or "Routine clinical care"

            procedures_list.append({
                "id": e["id"],
                "category_label": cat_label,
                "title": e["title"],
                "scheduled_datetime": sched_dt,
                "instructions": instructions,
                "status": e["state"],
                "completed_datetime": comp_dt
            })

        # Detailed Day-by-Day Adherence History Log
        history_log = []
        for e in all_occurrences:
            sched_raw = e.get("scheduled_at", "")
            date_str = sched_raw[:10] if len(sched_raw) >= 10 else "--"
            time_str = sched_raw[11:16] if len(sched_raw) >= 16 else "--"
            try:
                # 12h format
                h, m = map(int, time_str.split(":"))
                ampm = "PM" if h >= 12 else "AM"
                h12 = h % 12 or 12
                time_display = f"{h12}:{m:02d} {ampm}"
            except Exception:
                time_display = time_str

            st = e["state"]
            comp_raw = e.get("completed_at")
            comp_time_display = "--"
            delay_text = "Scheduled"

            if comp_raw and len(comp_raw) >= 16:
                ct = comp_raw[11:16]
                try:
                    ch, cm = map(int, ct.split(":"))
                    comp_ampm = "PM" if ch >= 12 else "AM"
                    ch12 = ch % 12 or 12
                    comp_time_display = f"{ch12}:{cm:02d} {comp_ampm}"
                except Exception:
                    comp_time_display = ct

            if st == "Taken":
                delay_text = "Taken On-Time"
            elif st == "Delayed":
                delay_text = "Delayed (>30 mins)"
            elif st == "Missed":
                delay_text = "Explicitly Skipped"
            elif st == "Unresolved":
                delay_text = "3 Alarms Missed / Escalated"
            elif st in ["Completed", "Attended"]:
                delay_text = "Completed"
            elif st == "Rescheduled":
                delay_text = f"Rescheduled to {e.get('rescheduled_to') or 'New Date'}"
            elif st == "Upcoming":
                delay_text = "Upcoming"

            d = e.get("details_parsed", {})
            dose_info = d.get("strength") or d.get("dosage") or d.get("scan_type") or e.get("notes") or "Standard dose"

            history_log.append({
                "date": date_str,
                "scheduled_time": time_display,
                "title": e["title"],
                "category": e["category"],
                "dosage_regimen": dose_info,
                "status": st,
                "actual_time": comp_time_display,
                "observation_note": delay_text
            })

        # Diagnostic Counts
        inj_total = len(inj_events)
        inj_completed = sum(1 for e in inj_events if e["state"] in ["Completed", "Taken"])
        inj_delayed = sum(1 for e in inj_events if e["state"] == "Delayed")
        inj_missed = sum(1 for e in inj_events if e["state"] == "Missed")

        scan_total = len(scan_events)
        scan_completed = sum(1 for e in scan_events if e["state"] == "Completed")
        scan_rescheduled = sum(1 for e in scan_events if e["state"] == "Rescheduled")
        scan_missed = sum(1 for e in scan_events if e["state"] == "Missed")

        appt_total = len(appt_events)
        appt_attended = sum(1 for e in appt_events if e["state"] == "Attended")
        appt_rescheduled = sum(1 for e in appt_events if e["state"] == "Rescheduled")
        appt_missed = sum(1 for e in appt_events if e["state"] == "Missed")

        # Factual Observations
        observations = []
        if delayed_med > 0:
            observations.append(f"Recorded {delayed_med} dose(s) taken beyond the scheduled 30-minute window.")
        if missed_med > 0:
            observations.append(f"Patient logged {missed_med} explicitly skipped medication dose(s).")
        if unresolved_med > 0:
            observations.append(f"{unresolved_med} reminder(s) reached maximum 3 alarm attempts without direct confirmation.")
        if len(escalations) > 0:
            observations.append(f"{len(escalations)} emergency escalation alert(s) dispatched to primary contact ({user['emergency_contact_1_name']}).")
        if adherence_pct >= 90.0:
            observations.append(f"Overall medication schedule compliance maintained above 90% ({adherence_pct}%).")
        elif adherence_pct < 75.0:
            observations.append(f"Medication adherence is below 75% ({adherence_pct}%). Review reminder intervals during consultation.")
        if not observations:
            observations.append("All scheduled events adhere accurately to patient-confirmed timing.")

        return {
            "user": user,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "med_stats": {
                "total": total_med,
                "taken": taken_med,
                "delayed": delayed_med,
                "missed": missed_med,
                "unresolved": unresolved_med,
                "upcoming": upcoming_med,
                "due": due_doses,
                "adherence_pct": adherence_pct,
                "drug_breakdown": drug_stats
            },
            "inj_stats": {
                "total": inj_total,
                "completed": inj_completed,
                "delayed": inj_delayed,
                "missed": inj_missed
            },
            "scan_stats": {
                "total": scan_total,
                "completed": scan_completed,
                "rescheduled": scan_rescheduled,
                "missed": scan_missed
            },
            "appt_stats": {
                "total": appt_total,
                "attended": appt_attended,
                "rescheduled": appt_rescheduled,
                "missed": appt_missed
            },
            "procedures_list": procedures_list,
            "history_log": history_log,
            "escalations": escalations,
            "observations": observations
        }

    @classmethod
    def generate_pdf(cls, user_id: str) -> bytes:
        """Generates an executive, printable A4 PDF file using ReportLab with exact tabular columns."""
        data = cls.compute_report_data(user_id)
        user = data["user"]
        med = data["med_stats"]

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=42
        )

        styles = getSampleStyleSheet()
        normal = styles["Normal"]

        title_style = ParagraphStyle(
            "DocTitle",
            parent=normal,
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0F172A")
        )
        subtitle_style = ParagraphStyle(
            "DocSubtitle",
            parent=normal,
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#475569")
        )
        h2_style = ParagraphStyle(
            "Heading2",
            parent=normal,
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#1E3A8A"),
            spaceBefore=10,
            spaceAfter=5
        )
        disclaimer_style = ParagraphStyle(
            "Disclaimer",
            parent=normal,
            fontName="Helvetica-Oblique",
            fontSize=7.5,
            leading=10.5,
            textColor=colors.HexColor("#991B1B"),
            backColor=colors.HexColor("#FEF2F2"),
            borderPadding=5
        )
        body_style = ParagraphStyle(
            "Body",
            parent=normal,
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#334155")
        )
        cell_bold = ParagraphStyle(
            "CellBold",
            parent=normal,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#0F172A")
        )

        elements = []

        # 1. Header Banner
        header_table = Table([
            [
                Paragraph("<b>MEDISYNC</b> | Healthcare Activity & Adherence Report", title_style),
                Paragraph(f"<b>Generated:</b> {data['generated_at']}<br/><b>Purpose:</b> Clinical Consultation Review", subtitle_style)
            ]
        ], colWidths=[350, 172])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT')
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 6))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0284C7"), spaceAfter=8))

        # Persistent Non-negotiable Medical Disclaimer
        elements.append(Paragraph(
            "<b>IMPORTANT SAFETY NOTICE:</b> This document is an automated factual record of patient-confirmed schedule entries, reminder responses, and escalation actions. <b>It does not constitute medical advice, clinical diagnosis, or therapeutic instruction.</b> Consult your physician for medical decisions.",
            disclaimer_style
        ))
        elements.append(Spacer(1, 8))

        # Patient Demographics Card
        demo_data = [
            [
                Paragraph(f"<b>Patient Name:</b> {user['name']}", body_style),
                Paragraph(f"<b>Age:</b> {user['age']} yrs", body_style),
                Paragraph(f"<b>Guardian Mode:</b> {'Active (Age ≥ 60)' if user['guardian_mode_enabled'] else 'Standard'}", body_style)
            ],
            [
                Paragraph(f"<b>Known Allergies:</b> {user['allergies'] or 'None'}", body_style),
                Paragraph(f"<b>Emergency Contact 1:</b> {user['emergency_contact_1_name']} ({user['emergency_contact_1_phone']})", body_style),
                Paragraph(f"<b>Emergency Email:</b> {user['emergency_email']}", body_style)
            ]
        ]
        demo_table = Table(demo_data, colWidths=[175, 175, 172])
        demo_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ]))
        elements.append(demo_table)
        elements.append(Spacer(1, 10))

        # KPI Summary Grid
        kpi_data = [
            [
                Paragraph(f"<font size=15 color='#0284C7'><b>{med['adherence_pct']}%</b></font><br/>Adherence Rate", body_style),
                Paragraph(f"<font size=15 color='#16A34A'><b>{med['taken']}</b></font><br/>Taken On-Time", body_style),
                Paragraph(f"<font size=15 color='#D97706'><b>{med['delayed']}</b></font><br/>Delayed (>30m)", body_style),
                Paragraph(f"<font size=15 color='#DC2626'><b>{med['missed']}</b></font><br/>Explicitly Missed", body_style),
                Paragraph(f"<font size=15 color='#7C3AED'><b>{med['unresolved']}</b></font><br/>Unresolved", body_style),
                Paragraph(f"<font size=15 color='#64748B'><b>{med['upcoming']}</b></font><br/>Upcoming", body_style),
            ]
        ]
        kpi_table = Table(kpi_data, colWidths=[87, 87, 87, 87, 87, 87])
        kpi_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#94A3B8")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(kpi_table)
        elements.append(Spacer(1, 10))

        # =========================================================================
        # TABULAR COLUMN 1: Medication Summary Breakdown Table
        # =========================================================================
        elements.append(Paragraph("1. Medication Compliance Breakdown (Prescribed Regimen vs Actual Response)", h2_style))
        
        drug_rows = [
            [
                Paragraph("<b>Medicine Name</b>", cell_bold),
                Paragraph("<b>Prescribed Regimen</b>", cell_bold),
                Paragraph("<b>Total Doses</b>", cell_bold),
                Paragraph("<b>Taken On-Time</b>", cell_bold),
                Paragraph("<b>Delayed Doses</b>", cell_bold),
                Paragraph("<b>Missed Doses</b>", cell_bold),
                Paragraph("<b>Unresolved</b>", cell_bold),
                Paragraph("<b>Adherence %</b>", cell_bold)
            ]
        ]
        for drug_name, s in med["drug_breakdown"].items():
            drug_rows.append([
                Paragraph(f"<b>{drug_name}</b>", body_style),
                Paragraph(s.get("regimen", "Standard"), body_style),
                str(s["total"]),
                str(s["taken"]),
                f"{s['delayed']} ({s.get('days_delayed_count', 0)}d)",
                f"{s['missed']} ({s.get('days_missed_count', 0)}d)",
                str(s["unresolved"]),
                f"<b>{s['adherence_rate']}%</b>"
            ])
        if len(drug_rows) == 1:
            drug_rows.append(["No confirmed medications recorded", "-", "-", "-", "-", "-", "-", "-"])

        drug_table = Table(drug_rows, colWidths=[112, 130, 48, 50, 52, 48, 42, 40])
        drug_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F766E")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")])
        ]))
        elements.append(drug_table)
        elements.append(Spacer(1, 10))

        # =========================================================================
        # TABULAR COLUMN 2: Injections, Diagnostic Tests & Consultations Table
        # =========================================================================
        elements.append(Paragraph("2. Injections, Diagnostic Tests & Physician Consultations", h2_style))
        proc_rows = [
            [
                Paragraph("<b>Category</b>", cell_bold),
                Paragraph("<b>Healthcare Event / Item</b>", cell_bold),
                Paragraph("<b>Scheduled Date & Time</b>", cell_bold),
                Paragraph("<b>Preparation / Clinic Notes</b>", cell_bold),
                Paragraph("<b>Status</b>", cell_bold),
                Paragraph("<b>Completed At</b>", cell_bold)
            ]
        ]
        if data["procedures_list"]:
            for p in data["procedures_list"]:
                proc_rows.append([
                    Paragraph(p["category_label"], body_style),
                    Paragraph(f"<b>{p['title']}</b>", body_style),
                    p["scheduled_datetime"],
                    Paragraph(p["instructions"], body_style),
                    Paragraph(f"<b>{p['status']}</b>", body_style),
                    p["completed_datetime"]
                ])
        else:
            proc_rows.append(["-", "No injections, diagnostic tests or consultations scheduled", "-", "-", "-", "-"])

        proc_table = Table(proc_rows, colWidths=[70, 120, 85, 125, 57, 65])
        proc_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
            ('ALIGN', (4, 0), (5, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")])
        ]))
        elements.append(proc_table)
        elements.append(Spacer(1, 10))

        # =========================================================================
        # TABULAR COLUMN 3: Date-Wise Daily Adherence History Log Table
        # =========================================================================
        elements.append(Paragraph("3. Daily Healthcare Adherence Log (Chronological Patient Record)", h2_style))
        hist_rows = [
            [
                Paragraph("<b>Date</b>", cell_bold),
                Paragraph("<b>Scheduled</b>", cell_bold),
                Paragraph("<b>Medicine / Healthcare Event</b>", cell_bold),
                Paragraph("<b>Prescribed Regimen</b>", cell_bold),
                Paragraph("<b>Adherence Status</b>", cell_bold),
                Paragraph("<b>Actual Time</b>", cell_bold),
                Paragraph("<b>Variance / Observation</b>", cell_bold)
            ]
        ]
        # Show recent 20 entries to fit cleanly
        recent_history = data["history_log"][:25]
        if recent_history:
            for h in recent_history:
                status_color = "#16A34A" if h["status"] in ["Taken", "Completed", "Attended"] else (
                    "#D97706" if h["status"] == "Delayed" else (
                        "#DC2626" if h["status"] == "Missed" else (
                            "#7C3AED" if h["status"] == "Unresolved" else "#475569"
                        )
                    )
                )
                hist_rows.append([
                    h["date"],
                    h["scheduled_time"],
                    Paragraph(f"<b>{h['title']}</b>", body_style),
                    Paragraph(h["dosage_regimen"], body_style),
                    Paragraph(f"<font color='{status_color}'><b>{h['status']}</b></font>", body_style),
                    h["actual_time"],
                    Paragraph(h["observation_note"], body_style)
                ])
        else:
            hist_rows.append(["-", "-", "No historical events recorded", "-", "-", "-", "-"])

        hist_table = Table(hist_rows, colWidths=[55, 50, 120, 95, 62, 55, 85])
        hist_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ALIGN', (0, 0), (1, -1), 'CENTER'),
            ('ALIGN', (4, 0), (5, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 3.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")])
        ]))
        elements.append(hist_table)
        elements.append(Spacer(1, 10))

        # 4. Escalation Log
        elements.append(Paragraph("4. Escalation & Safety Notifications Log", h2_style))
        esc_rows = [["Timestamp", "Type", "Target Recipient", "Delivery Status", "Escalation Message"]]
        if data["escalations"]:
            for esc in data["escalations"]:
                esc_rows.append([
                    esc["created_at"][:16].replace("T", " "),
                    esc["escalation_type"],
                    f"{esc['target_name']}",
                    esc["status"],
                    Paragraph(esc["message"], ParagraphStyle("EscMsg", parent=normal, fontSize=7, leading=8.5))
                ])
        else:
            esc_rows.append(["No emergency escalations triggered. All reminders answered.", "-", "-", "OK", "-"])

        esc_table = Table(esc_rows, colWidths=[80, 75, 95, 52, 220])
        esc_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#B91C1C")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ALIGN', (1, 0), (3, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 3.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#FEF2F2")])
        ]))
        elements.append(esc_table)
        elements.append(Spacer(1, 8))

        # 5. Recorded Observations
        elements.append(Paragraph("5. Recorded Factual Observations", h2_style))
        for obs in data["observations"]:
            elements.append(Paragraph(f"• <b>Observation:</b> {obs}", body_style))
            elements.append(Spacer(1, 2))

        elements.append(Spacer(1, 8))
        elements.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#CBD5E1"), spaceAfter=6))
        elements.append(Paragraph(
            "<b>Doctor Verification Notes:</b> ____________________________________________________________________________________________<br/>"
            "Physician Signature / Seal: _____________________________________   Date: ________________________",
            ParagraphStyle("Sig", parent=normal, fontSize=7.5, leading=12, textColor=colors.HexColor("#475569"))
        ))

        # Build PDF
        doc.build(elements, canvasmaker=NumberedCanvas)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes
