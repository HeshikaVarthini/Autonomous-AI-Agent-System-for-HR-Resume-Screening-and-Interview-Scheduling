"""
backend/api_forms.py
====================
The API endpoint HR hits when they paste a Google Form link.
When a new response arrives, resume is auto-downloaded from the form and saved.
"""
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from form_watcher import watcher_registry

_log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BACKEND_DIR / "uploads"
RESULTS_DIR = BACKEND_DIR / "upload_results"  # Parse + score results per resume

# Per-job config: job_id -> { "job_description", "keywords", "threshold", "calendar_id", "meeting_duration_minutes" }
job_config: dict = {}

router = APIRouter(prefix="/api/forms", tags=["Forms"])


@router.get("", summary="Forms API check", responses={200: {"content": {"application/json": {}, "text/html": {}}}})
async def forms_api_root(request: Request):
    """Confirm Forms API is mounted. Returns HTML in browser, JSON for API clients."""
    # Browser address bar sends Accept: text/html; fetch() sends */* — show HTML only for browser
    accept = (request.headers.get("accept") or "").strip().lower()
    want_json = request.query_params.get("json") == "1"
    if not want_json and accept.startswith("text/html"):
        html = """
        <!DOCTYPE html>
        <html><head><meta charset="utf-8"><title>Forms API</title>
        <style>body{font-family:system-ui;max-width:600px;margin:40px auto;padding:20px;background:#0f0f1a;color:#e2e8f0;}
        a{color:#818cf8;} h1{color:#a5b4fc;} .box{background:rgba(255,255,255,0.05);border-radius:12px;padding:16px;margin:12px 0;}
        code{background:rgba(0,0,0,0.3);padding:2px 6px;border-radius:4px;}</style></head>
        <body>
        <h1>Forms API is running</h1>
        <p>Use this API to connect Google Forms, score resumes, and schedule interviews from the HR calendar.</p>
        <div class="box">
        <strong>Step 1 — Main app</strong><br>
        <a href="/">Open the FormWatcher app</a> (add job, paste form link, connect).
        </div>
        <div class="box">
        <strong>Step 2 — API docs</strong><br>
        <a href="/docs">Open Swagger docs</a> to see all endpoints (watch, watchers, check-interview-responses, etc.).
        </div>
        <div class="box">
        <strong>Step 3 — HR calendar & candidate invite</strong><br>
        When a candidate scores above threshold, the system finds a free slot on <b>your (HR) Google Calendar</b>,
        creates the meeting there (with Google Meet), and <b>sends a calendar invite by email to the candidate</b> using the <b>email from your Google Form</b>. The meeting is visible in your calendar; the candidate gets an email and, when they accept, the event appears on their calendar (no access to their calendar needed). Ensure your form has a question titled e.g. <b>Email</b> or <b>Email address</b> so we can detect it and invite them. Open the event link in <code>backend/upload_results/*_result.json</code> (scheduled_event.event_link) or the link printed in the terminal.         If the <b>candidate or the interviewer</b> declines, use
        <code>POST /api/forms/check-interview-responses</code> to reschedule and send a new invite. Optionally set <code>interviewer_email</code> in job config (or in the watch body) so the interviewer is added as an attendee and can trigger reschedule if they decline.
        </div>
        <p><a href="/api/forms?json=1">View as JSON</a></p>
        </body></html>
        """
        return HTMLResponse(html)
    return JSONResponse({"ok": True, "api": "forms", "message": "Forms API is running. Use POST /api/forms/watch to connect a form."})


class WatchRequest(BaseModel):
    form_url: str                # HR pastes this
    job_id: str                  # Which job this form is for
    poll_every: int = 60
    download_existing: bool = False
    job_description: str = ""    # HR's job description; resume is scored against this (LLM or keyword fallback)
    job_keywords: list[str] = []  # Optional: explicit keywords; if job_description set, LLM uses it
    score_threshold: float = 50   # Min score 0-100 to pass
    interviewer_email: str = ""  # Optional: add as attendee so if interviewer declines we reschedule too


def _sanitize_filename(name: str) -> str:
    """Safe filename from candidate name."""
    if not name or not name.strip():
        return "candidate"
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in name.strip())[:50].strip() or "candidate"


def _sanitize_resume_filename(name: str) -> str:
    """Safe filename for uploaded resume (allow dots for extension)."""
    if not name or not name.strip():
        return ""
    # Strip path if present, keep only base name
    base = name.strip().replace("\\", "/").split("/")[-1]
    # Allow letters, digits, spaces, hyphen, underscore, dot
    safe = "".join(c if c.isalnum() or c in " ._-" else "_" for c in base)[:120].strip()
    return safe if safe else ""


# ── what happens when a new response arrives ──────────────────────────────
async def on_new_response(response, resume_bytes, resume_filename, job_id):
    """
    Fires for every form response. Saves resume, then parses it and scores against threshold.
    """
    import json
    import uuid

    name = response.get("name") or response.get("email") or "candidate"
    row = response.get("row_number", "")

    sheet_filename = _sanitize_resume_filename(response.get("resume_filename_from_sheet") or "")
    file_to_save = sheet_filename or resume_filename

    _log.info(
        "FORM RESPONSE (row #%s) Name=%s Email=%s Job=%s Resume=%s (%s)",
        row, response.get("name", ""), response.get("email", ""), job_id, file_to_save,
        "downloaded" if resume_bytes else "missing",
    )

    saved_path = None
    if resume_bytes:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = _sanitize_filename(name)
        short_id = uuid.uuid4().hex[:8]
        saved_path = UPLOADS_DIR / f"{safe_name}_{row}_{short_id}_{file_to_save}"
        with open(saved_path, "wb") as f:
            f.write(resume_bytes)
        _log.info("Resume saved -> %s", saved_path)

        # Parse resume and score against job description (LLM) or keywords + threshold
        try:
            from resume_parser import parse_resume, evaluate_resume
            config = job_config.get(job_id, {})
            job_description = (config.get("job_description") or "").strip()
            keywords = config.get("keywords", [])
            threshold = config.get("threshold", 50)

            parsed = parse_resume(resume_bytes, file_to_save)
            response["resume_parse"] = parsed

            if job_description:
                # Score using LLM (or keyword fallback from JD) against job description
                from llm_scorer import score_resume_with_llm
                llm_result = score_resume_with_llm(job_description, parsed["text"], threshold=threshold)
                response["resume_score"] = {
                    "score": llm_result["score"],
                    "above_threshold": llm_result["above_threshold"],
                    "reasoning": llm_result.get("reasoning", ""),
                    "source": llm_result.get("source", "llm"),
                    "matched": llm_result.get("matched_keywords", []),
                    "missing": llm_result.get("missing_keywords", []),
                }
                response["above_threshold"] = llm_result["above_threshold"]
                response["score_threshold"] = threshold
                _log.info(
                    "Resume (job-description): score=%s threshold=%s above=%s source=%s",
                    llm_result["score"], threshold, llm_result["above_threshold"], llm_result.get("source"),
                )
            else:
                result = evaluate_resume(resume_bytes, file_to_save, keywords=keywords, threshold=threshold)
                parsed = result["parse"]
                response["resume_parse"] = parsed
                response["resume_score"] = {**result["score"], "reasoning": "", "source": "keywords"}
                response["above_threshold"] = result["above_threshold"]
                response["score_threshold"] = result["threshold"]
                _log.info(
                    "Resume (keywords): score=%s threshold=%s above=%s matched=%s",
                    result["score"]["score"], threshold, result["above_threshold"], result["score"].get("matched", []),
                )

            # Save result JSON
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            result_path = RESULTS_DIR / f"{safe_name}_{row}_{short_id}_result.json"
            scr = response["resume_score"]
            save_obj = {
                "name": name,
                "email": response.get("email"),
                "row": row,
                "job_id": job_id,
                "resume_file": str(saved_path),
                "parse_ok": parsed["parse_ok"],
                "word_count": parsed["word_count"],
                "score": scr.get("score"),
                "threshold": threshold,
                "above_threshold": response["above_threshold"],
                "reasoning": scr.get("reasoning", ""),
                "source": scr.get("source", "keywords"),
                "matched_keywords": scr.get("matched", scr.get("matched_keywords", [])),
                "missing_keywords": scr.get("missing", scr.get("missing_keywords", [])),
            }

            # If above threshold: find free slot on HR calendar and schedule interview
            if response["above_threshold"]:
                calendar_id = config.get("calendar_id") or "primary"
                meeting_mins = config.get("meeting_duration_minutes", 30)
                candidate_email = (response.get("email") or "").strip()
                try:
                    from form_watcher import get_google_creds
                    from calendar_scheduler import schedule_interview
                    creds = get_google_creds()
                    schedule_result = schedule_interview(
                        creds, calendar_id=calendar_id,
                        candidate_name=name, candidate_email=candidate_email, job_id=job_id,
                        duration_minutes=meeting_mins,
                        interviewer_email=config.get("interviewer_email"),
                    )
                    save_obj["scheduled_event"] = schedule_result
                    if schedule_result.get("ok"):
                        save_obj["reschedule_count"] = 0
                    if schedule_result.get("ok") and schedule_result.get("event_link"):
                        print(f"  In HR calendar: {schedule_result['event_link']}")
                        if schedule_result.get("meet_link"):
                            print(f"  Google Meet : {schedule_result['meet_link']}")
                        print(f"  Time: {schedule_result.get('start')} – {schedule_result.get('end')}")
                        if candidate_email:
                            print(f"  Candidate invite sent to: {candidate_email} (they get email; no access to their calendar needed)")
                    else:
                        _log.warning("Could not schedule interview: %s", schedule_result.get("error"))
                except Exception as cal_e:
                    _log.warning("Calendar schedule failed: %s", cal_e)
                    save_obj["scheduled_event"] = {"ok": False, "error": str(cal_e)}

            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(save_obj, f, indent=2, ensure_ascii=False)

            # Show parse + score in terminal
            scr = response["resume_score"]
            sep = "─" * 60
            print()
            print(sep)
            print("  RESUME PARSE & SCORE")
            print(sep)
            print(f"  Name       : {name}")
            print(f"  Row        : {row}  |  Job ID : {job_id}")
            print(f"  Parse OK   : {parsed['parse_ok']}  |  Word count : {parsed.get('word_count', 0)}")
            print(f"  Score      : {scr.get('score')} / 100  (threshold: {threshold})")
            print(f"  Pass       : {'YES' if response['above_threshold'] else 'NO'}")
            print(f"  Source     : {scr.get('source', 'keywords')}")
            if scr.get("reasoning"):
                print(f"  Reasoning  : {scr['reasoning'][:200]}{'...' if len(scr.get('reasoning', '')) > 200 else ''}")
            matched = scr.get("matched", scr.get("matched_keywords", []))
            missing = scr.get("missing", scr.get("missing_keywords", []))
            if matched:
                print(f"  Matched    : {matched[:12]}{' ...' if len(matched) > 12 else ''}")
            if missing:
                print(f"  Missing    : {missing[:12]}{' ...' if len(missing) > 12 else ''}")
            print(f"  Result file: {result_path.name}")
            if save_obj.get("scheduled_event", {}).get("ok"):
                ev = save_obj["scheduled_event"]
                print(f"  In HR calendar : {ev.get('event_link', '')}")
                print(f"  Time           : {ev.get('start', '')}")
                if ev.get("meet_link"):
                    print(f"  Meet link      : {ev.get('meet_link')}")
            elif save_obj.get("scheduled_event") and not save_obj["scheduled_event"].get("ok"):
                print(f"  Scheduled   : failed — {save_obj['scheduled_event'].get('error', '')}")
            print(sep)
            print()
        except Exception as e:
            _log.warning("Resume parse/score failed: %s", e)
            print(f"  [RESUME ERROR] {name} (row {row}): {e}")
            response["above_threshold"] = None
            response["resume_score"] = None


@router.post("/watch")
async def start_watching(body: WatchRequest):
    """
    HR pastes Google Form link here. Optionally set job_keywords and score_threshold
    to parse resumes and score them (candidate must score >= threshold).
    """
    try:
        job_config[body.job_id] = {
            "job_description": (body.job_description or "").strip(),
            "keywords": list(body.job_keywords) if body.job_keywords else [],
            "threshold": float(body.score_threshold),
            "calendar_id": getattr(body, "calendar_id", None) or "primary",
            "meeting_duration_minutes": getattr(body, "meeting_duration_minutes", None) or 30,
            "interviewer_email": (getattr(body, "interviewer_email", None) or "").strip() or None,
        }
        info = await watcher_registry.add(
            form_url=body.form_url,
            job_id=body.job_id,
            callback=on_new_response,
            poll_every=body.poll_every,
            download_existing=body.download_existing,
        )
        return {
            "status":  "watching",
            "message": f"Now watching '{info['form_title']}' for new responses",
            "job_description": job_config[body.job_id].get("job_description", ""),
            "job_keywords": job_config[body.job_id]["keywords"],
            "score_threshold": job_config[body.job_id]["threshold"],
            **info,
        }
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Setup failed: {e}")


@router.get("/watchers")
async def list_watchers():
    statuses = watcher_registry.all_status()
    for s in statuses:
        jid = s.get("job_id")
        if jid and jid in job_config:
            s["job_description"] = job_config[jid].get("job_description", "")
            s["job_keywords"] = job_config[jid].get("keywords", [])
            s["score_threshold"] = job_config[jid].get("threshold", 50)
    return statuses


@router.delete("/watch/{job_id}")
async def stop_watching(job_id: str):
    if not watcher_registry.get(job_id):
        raise HTTPException(404, "No watcher for this job")
    await watcher_registry.remove(job_id)
    job_config.pop(job_id, None)
    return {"stopped": True}


@router.get("/job-config/{job_id}")
async def get_job_config(job_id: str):
    """Get job config including calendar and meeting duration."""
    c = job_config.get(job_id, {})
    return {
        "job_id": job_id,
        "job_description": c.get("job_description", ""),
        "keywords": c.get("keywords", []),
        "threshold": c.get("threshold", 50),
        "calendar_id": c.get("calendar_id", "primary"),
        "meeting_duration_minutes": c.get("meeting_duration_minutes", 30),
        "interviewer_email": c.get("interviewer_email"),
    }


class JobConfigUpdate(BaseModel):
    job_description: str = ""
    job_keywords: list[str] = []
    score_threshold: float = 50
    calendar_id: str = "primary"
    meeting_duration_minutes: int = 30
    interviewer_email: str | None = None


@router.patch("/job-config/{job_id}")
async def update_job_config(job_id: str, body: JobConfigUpdate):
    """Set job description, keywords and/or threshold for a job."""
    if job_id not in job_config:
        job_config[job_id] = {"job_description": "", "keywords": [], "threshold": 50, "calendar_id": "primary", "meeting_duration_minutes": 30, "interviewer_email": None}
    if body.job_description is not None:
        job_config[job_id]["job_description"] = (body.job_description or "").strip()
    if body.job_keywords is not None:
        job_config[job_id]["keywords"] = list(body.job_keywords)
    if body.score_threshold is not None:
        job_config[job_id]["threshold"] = float(body.score_threshold)
    if body.calendar_id is not None:
        job_config[job_id]["calendar_id"] = body.calendar_id or "primary"
    if body.meeting_duration_minutes is not None:
        job_config[job_id]["meeting_duration_minutes"] = int(body.meeting_duration_minutes)
    if body.interviewer_email is not None:
        job_config[job_id]["interviewer_email"] = (body.interviewer_email or "").strip() or None
    return job_config[job_id]


@router.post("/poll-now/{job_id}")
async def poll_now(job_id: str):
    """Manually trigger one poll (checks for new responses only)."""
    w = watcher_registry.get(job_id)
    if not w:
        raise HTTPException(404, "No watcher for this job")
    await w._poll_once()
    return {"polled": True, "total_processed": w.total_processed}


@router.post("/download-existing/{job_id}")
async def download_existing_now(job_id: str):
    """Process all existing responses in the sheet (download their resumes). Use when you have existing rows that were never processed."""
    w = watcher_registry.get(job_id)
    if not w:
        raise HTTPException(404, "No watcher for this job")
    before = w.total_processed
    w.last_row = 1  # Process from first data row
    await w._poll_once()
    added = w.total_processed - before
    return {"ok": True, "processed": added, "total_processed": w.total_processed}


# Max times we reschedule when candidate declines (then stop and leave last invite pending)
MAX_RESCEDULE_ATTEMPTS = 3


@router.post("/check-interview-responses")
async def check_interview_responses():
    """
    Check all scheduled interviews: if the candidate or the interviewer declined,
    find a new slot on HR calendar, create a new event with Meet, send new invite, and cancel the old event.
    Call this periodically (e.g. daily) or from a "Check responses" button.
    """
    import json
    from form_watcher import get_google_creds
    from calendar_scheduler import (
        get_event_any_attendee_declined,
        cancel_event,
        schedule_interview,
    )
    try:
        creds = get_google_creds()
    except Exception as e:
        raise HTTPException(503, f"Calendar not available: {e}")
    checked = 0
    rescheduled = 0
    details = []
    if not RESULTS_DIR.exists():
        return {"checked": 0, "rescheduled": 0, "details": []}
    for path in RESULTS_DIR.glob("*_result.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        se = data.get("scheduled_event") or {}
        if not se.get("ok") or not se.get("event_id"):
            continue
        email = (data.get("email") or "").strip()
        if not email:
            continue
        reschedule_count = data.get("reschedule_count", 0)
        if reschedule_count >= MAX_RESCEDULE_ATTEMPTS:
            continue
        job_id = data.get("job_id", "")
        config = job_config.get(job_id, {})
        calendar_id = config.get("calendar_id", "primary")
        meeting_mins = config.get("meeting_duration_minutes", 30)
        name = data.get("name", "Candidate")
        event_id = se["event_id"]
        checked += 1
        any_declined, declined_emails = get_event_any_attendee_declined(creds, calendar_id, event_id)
        if not any_declined:
            details.append({"file": path.name, "email": email, "status": "no_decline"})
            continue
        declined_who = ", ".join(declined_emails) if declined_emails else "attendee"
        # Candidate or interviewer declined: find new slot, create new event, cancel old
        new_result = schedule_interview(
            creds, calendar_id=calendar_id,
            candidate_name=name, candidate_email=email, job_id=job_id,
            duration_minutes=meeting_mins,
            interviewer_email=config.get("interviewer_email"),
        )
        if not new_result.get("ok"):
            details.append({"file": path.name, "email": email, "action": "reschedule_failed", "error": new_result.get("error"), "declined": declined_emails})
            continue
        cancel_event(creds, calendar_id, event_id)
        data["scheduled_event"] = new_result
        data["reschedule_count"] = reschedule_count + 1
        data.setdefault("rescheduled_events", []).append({
            "previous_event_id": event_id,
            "reason": "attendee_declined",
            "declined_emails": declined_emails,
        })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        rescheduled += 1
        details.append({
            "file": path.name, "email": email, "action": "rescheduled",
            "declined": declined_emails,
            "new_start": new_result.get("start"), "new_meet_link": new_result.get("meet_link"),
        })
        _log.info("Rescheduled interview for %s (declined by: %s) -> %s", email, declined_who, new_result.get("start"))
    return {"checked": checked, "rescheduled": rescheduled, "details": details}
