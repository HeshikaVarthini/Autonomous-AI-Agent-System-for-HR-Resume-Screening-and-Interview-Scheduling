"""
backend/calendar_scheduler.py
==============================
Use HR's Google Calendar: find free slots and create interview events
when a candidate scores above threshold.
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Defaults: look 7 days ahead, 30 min meeting, 9am–5pm window (UTC; adjust if needed)
DEFAULT_DAYS_AHEAD = 7
DEFAULT_DURATION_MINUTES = 30
DEFAULT_TZ = "UTC"
# Optional: only consider slots between start_hour and end_hour (0-24)
WORK_START_HOUR = 9
WORK_END_HOUR = 17


def _parse_rfc3339(s: str) -> datetime:
    """Parse RFC3339 string to datetime (timezone-aware)."""
    s = s.replace("Z", "+00:00")
    if s.endswith("+00:00"):
        return datetime.fromisoformat(s)
    return datetime.fromisoformat(s)


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def get_free_slots(creds, calendar_id: str = "primary", days_ahead: int = DEFAULT_DAYS_AHEAD,
                   duration_minutes: int = DEFAULT_DURATION_MINUTES):
    """
    Query calendar freebusy and return list of (start, end) free slots, each at least duration_minutes.
    Returns list of (datetime, datetime) in UTC.
    """
    from googleapiclient.discovery import build
    service = build("calendar", "v3", credentials=creds)
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days_ahead)
    body = {
        "timeMin": _to_rfc3339(now),
        "timeMax": _to_rfc3339(time_max),
        "items": [{"id": calendar_id}],
    }
    try:
        resp = service.freebusy().query(body=body).execute()
    except Exception as e:
        logger.warning("Freebusy query failed: %s", e)
        raise RuntimeError(f"Calendar freebusy failed: {e}. Enable Calendar API and add scopes (see backend/CALENDAR_SETUP.txt), then delete token.json and reconnect.") from e
    cal = resp.get("calendars", {}).get(calendar_id, {})
    busy_list = cal.get("busy", [])
    errors = cal.get("errors", [])
    if errors:
        err_msg = "; ".join(str(e) for e in errors)
        logger.warning("Calendar %s errors: %s", calendar_id, errors)
        raise RuntimeError(f"Calendar returned errors: {err_msg}") from None

    # Sort and merge overlapping busy intervals
    delta = timedelta(minutes=duration_minutes)
    if not busy_list:
        # Entire window is free; yield first slot and exit
        yield (now, now + delta)
        return
    busy_times = []
    for b in busy_list:
        start = _parse_rfc3339(b["start"])
        end = _parse_rfc3339(b["end"])
        busy_times.append((start, end))
    busy_times.sort(key=lambda x: x[0])
    merged = []
    for s, e in busy_times:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # Free slots = gaps between merged busy, and before first / after last
    free_slots = []
    delta = timedelta(minutes=duration_minutes)
    # Before first busy
    if merged:
        gap_start = now
        gap_end = merged[0][0]
        if (gap_end - gap_start) >= delta:
            free_slots.append((gap_start, gap_end))
    # Between busy intervals
    for i in range(len(merged) - 1):
        gap_start = merged[i][1]
        gap_end = merged[i + 1][0]
        if (gap_end - gap_start) >= delta:
            free_slots.append((gap_start, gap_end))
    # After last busy
    if merged:
        gap_start = merged[-1][1]
        gap_end = time_max
        if (gap_end - gap_start) >= delta:
            free_slots.append((gap_start, gap_end))
    if not merged:
        free_slots = [(now, time_max)]

    # Return first free chunk of duration_minutes from any gap
    for slot_start, slot_end in free_slots:
        if (slot_end - slot_start) >= delta:
            yield (slot_start, slot_start + delta)
            return


def create_calendar_event(creds, calendar_id: str, start_dt: datetime, end_dt: datetime,
                         summary: str, description: str = "", attendee_emails: list = None,
                         add_google_meet: bool = True):
    """Create a calendar event, optionally with a Google Meet link. Returns created event dict or None on failure."""
    import uuid
    from googleapiclient.discovery import build
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    body = {
        "summary": summary,
        "description": description or "",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": DEFAULT_TZ},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": DEFAULT_TZ},
    }
    if attendee_emails:
        body["attendees"] = [{"email": e} for e in attendee_emails if e]
    if add_google_meet:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": uuid.uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    try:
        service = build("calendar", "v3", credentials=creds)
        event = service.events().insert(
            calendarId=calendar_id,
            body=body,
            sendUpdates="all",
            conferenceDataVersion=1,
        ).execute()
        return event
    except Exception as e:
        logger.warning("Calendar event insert failed: %s", e)
        raise RuntimeError(f"Calendar event create failed: {e}. Check CALENDAR_SETUP.txt and that token has calendar scope.") from e


def schedule_interview(creds, calendar_id: str, candidate_name: str, candidate_email: str,
                       job_id: str, duration_minutes: int = DEFAULT_DURATION_MINUTES,
                       days_ahead: int = DEFAULT_DAYS_AHEAD, interviewer_email: str = None):
    """
    Find first free slot and create an interview event on the HR calendar. Invite candidate (and optionally interviewer).
    If interviewer_email is set, they are added as attendee so they get the invite and reschedule runs if they decline.
    Returns dict: { "ok": bool, "event_link": str|None, "start": str, "end": str, "error": str|None }
    """
    try:
        slots = list(get_free_slots(creds, calendar_id=calendar_id, days_ahead=days_ahead, duration_minutes=duration_minutes))
    except Exception as e:
        return {"ok": False, "event_link": None, "start": None, "end": None, "error": str(e)}
    if not slots:
        return {"ok": False, "event_link": None, "start": None, "end": None, "error": "No free slots found in the next %d days." % days_ahead}
    start_dt, end_dt = slots[0]
    summary = f"Interview: {candidate_name}"
    description = f"Automatically scheduled for candidate above threshold (Job: {job_id})."
    attendee_emails = []
    if candidate_email:
        attendee_emails.append(candidate_email)
    if interviewer_email and (interviewer_email or "").strip():
        ie = (interviewer_email or "").strip()
        if ie and ie.lower() != (candidate_email or "").strip().lower():
            attendee_emails.append(ie)
    try:
        event = create_calendar_event(creds, calendar_id, start_dt, end_dt, summary, description, attendee_emails, add_google_meet=True)
    except Exception as e:
        return {"ok": False, "event_link": None, "start": start_dt.isoformat(), "end": end_dt.isoformat(), "error": str(e)}
    if not event:
        return {"ok": False, "event_link": None, "start": start_dt.isoformat(), "end": end_dt.isoformat(), "error": "Failed to create event"}
    # htmlLink opens the event in the HR's Google Calendar (event is on this calendar)
    link = event.get("htmlLink") or event.get("link")
    meet_link = None
    if event.get("conferenceData", {}).get("entryPoints"):
        for ep in event["conferenceData"]["entryPoints"]:
            if ep.get("entryPointType") == "video" or ep.get("entryPointType") == "videoCall":
                meet_link = ep.get("uri")
                break
    meet_link = meet_link or event.get("conferenceData", {}).get("hangoutLink")
    return {
        "ok": True,
        "event_link": link,
        "meet_link": meet_link,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "event_id": event.get("id"),
        "calendar_id": calendar_id,
        "candidate_invited": bool(candidate_email),
        "candidate_email": candidate_email or None,
        "error": None,
    }


def get_event_attendee_response(creds, calendar_id: str, event_id: str, attendee_email: str):
    """
    Get the response status of an attendee for an event.
    Returns: "accepted" | "declined" | "tentative" | "needsAction" | None (if not found or error).
    """
    from googleapiclient.discovery import build
    try:
        service = build("calendar", "v3", credentials=creds)
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        email_lower = (attendee_email or "").strip().lower()
        for att in event.get("attendees", []):
            if (att.get("email") or "").lower() == email_lower:
                return att.get("responseStatus", "needsAction")
        return "needsAction"
    except Exception as e:
        logger.warning("Get event attendee response failed: %s", e)
        return None


def get_event_any_attendee_declined(creds, calendar_id: str, event_id: str):
    """
    Check if any attendee (candidate or interviewer) has declined the event.
    Returns: (any_declined: bool, declined_emails: list[str])
    """
    from googleapiclient.discovery import build
    try:
        service = build("calendar", "v3", credentials=creds)
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        declined = []
        for att in event.get("attendees", []):
            if (att.get("responseStatus") or "").lower() == "declined":
                declined.append((att.get("email") or "").strip())
        return (len(declined) > 0, declined)
    except Exception as e:
        logger.warning("Get event attendees failed: %s", e)
        return (False, [])


def cancel_event(creds, calendar_id: str, event_id: str):
    """Cancel (delete) a calendar event. Returns True on success."""
    from googleapiclient.discovery import build
    try:
        service = build("calendar", "v3", credentials=creds)
        service.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates="all").execute()
        return True
    except Exception as e:
        logger.warning("Cancel event failed: %s", e)
        return False
