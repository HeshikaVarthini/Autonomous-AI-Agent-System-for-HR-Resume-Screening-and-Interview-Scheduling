"""
backend/form_watcher.py
=======================
HR pastes Google Form URL → system watches it → new response arrives
→ resume downloaded from Drive → pipeline triggered.

HOW IT WORKS:
  Google Form → linked Google Sheet (auto-created by Google)
  We poll that Sheet every 60s for new rows.
  When new row = new form submission → download resume from Drive.
"""

import re, io, asyncio, os, logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Backend directory — credentials/token are always loaded from here
BACKEND_DIR = Path(__file__).resolve().parent

# ── pip install google-auth google-auth-oauthlib google-api-python-client ──

# Form watcher + calendar scheduling (meetings must be visible on HR calendar)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
]


# ════════════════════════════════════════════════════════════════════════════
# STEP 1 — Google Auth (run once, saves token.json for auto-refresh)
# ════════════════════════════════════════════════════════════════════════════

def get_google_creds(
    token_path: str = None,
    creds_path: str = None,
):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = token_path or str(BACKEND_DIR / "token.json")
    creds_path = creds_path or str(BACKEND_DIR / "credentials.json")

    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    "\n\nMISSING credentials.json\n"
                    "Steps to fix:\n"
                    "1. Go to https://console.cloud.google.com\n"
                    "2. Create project → APIs & Services → Enable:\n"
                    "     - Google Sheets API\n"
                    "     - Google Drive API\n"
                    "     - Google Forms API\n"
                    "     - Google Calendar API\n"
                    "3. Credentials → Create → OAuth 2.0 Client ID → Desktop\n"
                    "4. Download → rename to credentials.json → put next to this file\n"
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        logger.info(f"Token saved → {token_path}")

    return creds


# ════════════════════════════════════════════════════════════════════════════
# STEP 2 — Extract Form ID from URL
# ════════════════════════════════════════════════════════════════════════════

def extract_form_id(url: str) -> str:
    """
    Google Forms API only accepts the form ID from the EDIT URL.
    - Use: https://docs.google.com/forms/d/FORM_ID/edit  (or .../viewform)
    - Do NOT use: https://docs.google.com/forms/d/e/1FAIpQLS... (share link — different ID, API returns 404)
    """
    url = url.strip()

    # Reject view/share link — Forms API cannot use this ID (404)
    if "/forms/d/e/" in url:
        raise ValueError(
            "This is a form VIEW/SHARE link (the one you send to respondents). "
            "FormWatcher needs the form EDIT link instead.\n\n"
            "How to get the EDIT link:\n"
            "1. Open Google Forms (forms.google.com) and open YOUR form.\n"
            "2. Look at the browser address bar. The URL should look like:\n"
            "   https://docs.google.com/forms/d/XXXXXXXXXX/edit\n"
            "3. Copy that full URL (with /edit) and paste it here.\n\n"
            "Do not use the link from 'Send' or 'Preview' — use the URL when you are editing the form."
        )

    # Already a raw ID (long enough to be a real form ID)
    if re.match(r'^[a-zA-Z0-9_-]{20,}$', url):
        return url

    # Edit/viewform format: /forms/d/FORM_ID (same ID works for both)
    m = re.search(r'/forms/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)

    raise ValueError(
        f"Cannot extract Form ID from: {url}\n"
        "Use the form EDIT link: https://docs.google.com/forms/d/YOUR_FORM_ID/edit"
    )


# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — Find the Google Sheet linked to this Form
# ════════════════════════════════════════════════════════════════════════════

def find_linked_sheet(form_id: str, creds) -> dict:
    """
    Every Google Form auto-creates a response Sheet.
    We find it using the Forms API.
    
    Returns: {
        "sheet_id": "...",
        "form_title": "Job Application - Senior Dev",
        "sheet_url": "https://docs.google.com/spreadsheets/d/..."
    }
    """
    from googleapiclient.discovery import build

    forms_svc = build("forms", "v1", credentials=creds)
    form = forms_svc.forms().get(formId=form_id).execute()

    form_title = form.get("info", {}).get("title", "Untitled Form")
    sheet_id   = form.get("linkedSheetId")

    if not sheet_id:
        raise ValueError(
            f"Form '{form_title}' has no linked response sheet.\n\n"
            "Fix:\n"
            "  1. Open your Google Form\n"
            "  2. Click 'Responses' tab (top)\n"
            "  3. Click the green Sheets icon\n"
            "  4. This creates the response sheet automatically\n"
            "  5. Paste the form link again"
        )

    logger.info(f"Form: '{form_title}' → Sheet: {sheet_id}")

    return {
        "sheet_id":   sheet_id,
        "form_title": form_title,
        "form_id":    form_id,
        "sheet_url":  f"https://docs.google.com/spreadsheets/d/{sheet_id}",
    }


# ════════════════════════════════════════════════════════════════════════════
# STEP 4 — Read column headers from the Sheet
# ════════════════════════════════════════════════════════════════════════════

def read_columns(sheet_id: str, creds) -> dict:
    """
    Reads row 1 of the sheet (column headers = form question names).
    Auto-detects which column is name / email / phone / resume / linkedin.

    Returns: {"name": 1, "email": 2, "phone": 3, "resume": 4, ...}
    """
    from googleapiclient.discovery import build

    svc = build("sheets", "v4", credentials=creds)
    result = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="A1:Z1",
    ).execute()

    headers = result.get("values", [[]])[0]
    logger.info(f"Sheet headers: {headers}")

    col_map = {}
    for i, h in enumerate(headers):
        low = h.lower().strip()

        if "timestamp" in low:
            col_map["timestamp"] = i
        elif any(x in low for x in ["name", "full name", "your name"]):
            col_map["name"] = i
        elif any(x in low for x in ["email", "mail id", "e-mail", "your email", "email address", "candidate email"]):
            col_map["email"] = i
        elif any(x in low for x in ["phone", "mobile", "contact", "whatsapp"]):
            col_map["phone"] = i
        elif "resume" in low or "cv" in low:
            col_map["resume"] = i
        elif "resume" not in col_map and any(x in low for x in [
            "upload", "file", "attachment", "document", "pdf", "upload your", "your resume",
            "file 1", "link", "attach", "upload file", "file upload", "upload resume", "cv upload"
        ]):
            col_map["resume"] = i
        elif "linkedin" in low:
            col_map["linkedin"] = i
        elif any(x in low for x in ["file name", "filename", "document name", "uploaded file name", "name of file", "attachment name", "resume name", "cv name"]):
            col_map["resume_filename"] = i

    if "resume" in col_map:
        idx = col_map["resume"]
        name = headers[idx] if idx < len(headers) else "?"
        logger.info(f"Detected columns: {col_map} (resume = column '{name}')")
    else:
        logger.warning("No 'resume' column detected. Headers: " + str(headers) + " — add a File upload question to your form.")
    return col_map, headers


# ════════════════════════════════════════════════════════════════════════════
# STEP 4b — Get hyperlinks for a column (Forms often show "Link" instead of URL)
# ════════════════════════════════════════════════════════════════════════════

def _col_letter(idx: int) -> str:
    """Column index to A1 letter: 0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    while idx >= 0:
        s = chr(idx % 26 + ord("A")) + s
        idx = idx // 26 - 1
    return s


def fetch_column_hyperlinks(sheet_id: str, col_index: int, from_row: int, to_row: int, creds) -> list:
    """Get hyperlink URLs for a column range. Returns list of URL or None per row."""
    from googleapiclient.discovery import build
    if to_row <= from_row:
        return []
    range_str = f"{_col_letter(col_index)}{from_row + 1}:{_col_letter(col_index)}{to_row}"
    try:
        svc = build("sheets", "v4", credentials=creds)
        result = svc.spreadsheets().get(
            spreadsheetId=sheet_id,
            ranges=[range_str],
            fields="sheets(data(rowData(values(hyperlink))))",
        ).execute()
        sheets = result.get("sheets", [])
        if not sheets or not sheets[0].get("data"):
            return []
        row_data = sheets[0]["data"][0].get("rowData", [])
        out = []
        for row in row_data:
            vals = row.get("values", [])
            if vals and len(vals) > 0:
                url = vals[0].get("hyperlink")
                out.append(url if url else None)
            else:
                out.append(None)
        return out
    except Exception as e:
        logger.warning(f"Could not fetch hyperlinks for column: {e}")
        return []


def _find_drive_url_in_row(row: list) -> str:
    """Scan entire row for any cell containing a drive.google.com URL. Used as fallback."""
    for cell in row:
        if not cell or not isinstance(cell, str):
            continue
        s = cell.strip()
        if "drive.google.com" in s:
            for part in s.replace("\n", " ").split():
                if "drive.google.com" in part:
                    return part.strip()
        if s.startswith("http") and "drive" in s:
            return s
    return ""


def _extract_url_from_hyperlink_formula(cell_value: str) -> str:
    """Extract URL from =HYPERLINK("url", "display text") formula. Returns "" if not found."""
    if not cell_value or not isinstance(cell_value, str):
        return ""
    s = cell_value.strip()
    if not s.upper().startswith("=HYPERLINK("):
        return ""
    # Match first quoted string (the URL): =HYPERLINK("https://...", "text")
    m = re.search(r'=HYPERLINK\s*\(\s*"([^"]+)"', s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def fetch_row_formulas(sheet_id: str, from_row: int, to_row: int, creds) -> list:
    """Fetch cell formulas for the data range (to parse HYPERLINK formulas). Returns list of rows, each row = list of cell values."""
    if to_row <= from_row:
        return []
    try:
        from googleapiclient.discovery import build
        svc = build("sheets", "v4", credentials=creds)
        range_str = f"A{from_row + 1}:Z{to_row}"
        result = svc.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_str,
            valueRenderOption="FORMULA",
        ).execute()
        return result.get("values", [])
    except Exception as e:
        logger.debug("Could not fetch formulas: %s", e)
        return []


# ════════════════════════════════════════════════════════════════════════════
# STEP 5 — Poll sheet for new rows
# ════════════════════════════════════════════════════════════════════════════

def fetch_new_rows(sheet_id: str, col_map: dict, last_row: int, creds) -> tuple:
    """
    Fetches all rows after `last_row`.
    Returns: (list of response dicts, new last_row)
    
    Each response dict:
    {
        "name": "Arjun Mehta",
        "email": "arjun@gmail.com",
        "phone": "+91 98765...",
        "resume_url": "https://drive.google.com/open?id=...",
        "linkedin": "...",
        "timestamp": "...",
        "row_number": 5,
    }
    """
    from googleapiclient.discovery import build

    svc = build("sheets", "v4", credentials=creds)
    result = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="A:Z",
    ).execute()

    all_rows  = result.get("values", [])
    new_rows  = all_rows[last_row:]          # skip header + already processed

    if not new_rows:
        return [], last_row

    # Get hyperlinks: first try resume column, then try full row range (find Drive link in any column)
    resume_col = col_map.get("resume")
    hyperlinks = []
    if resume_col is not None and isinstance(resume_col, int):
        hyperlinks = fetch_column_hyperlinks(
            sheet_id, resume_col, last_row, last_row + len(new_rows), creds
        )
    # If no resume column or we want fallback: fetch hyperlinks for full range of new rows
    full_range_hyperlinks = []  # list of list of URLs per row
    try:
        from googleapiclient.discovery import build
        svc = build("sheets", "v4", credentials=creds)
        start_r = last_row + 1
        end_r = last_row + len(new_rows)
        range_str = f"A{start_r}:Z{end_r}"
        resp = svc.spreadsheets().get(
            spreadsheetId=sheet_id,
            ranges=[range_str],
            fields="sheets(data(rowData(values(hyperlink))))",
        ).execute()
        for sheet in resp.get("sheets", []):
            for data in sheet.get("data", []):
                for row in data.get("rowData", []):
                    row_urls = []
                    for cell in row.get("values", []):
                        u = cell.get("hyperlink") if isinstance(cell, dict) else None
                        row_urls.append(u)
                    full_range_hyperlinks.append(row_urls)
                break
            break
    except Exception as e:
        logger.debug("Full range hyperlinks: %s", e)

    # Form file-upload column often shows =HYPERLINK("https://drive.google.com/...", "Link") — get formulas to parse
    formula_rows = fetch_row_formulas(sheet_id, last_row, last_row + len(new_rows), creds)

    def first_drive_url(raw: str) -> str:
        """Take first URL from cell (may be comma-separated). Strip whitespace."""
        if not raw or not raw.strip():
            return ""
        for part in raw.split(","):
            part = part.strip()
            if "drive.google.com" in part or part.startswith("http"):
                return part
        return raw.strip()

    responses = []
    for i, row in enumerate(new_rows):
        # Pad row to avoid index errors
        while len(row) <= max((v for v in col_map.values() if isinstance(v, int)), default=0):
            row.append("")

        def col(key):
            idx = col_map.get(key)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        cell_resume = col("resume")
        # Use hyperlink URL if cell shows "Link" or doesn't look like a URL
        if i < len(hyperlinks) and hyperlinks[i]:
            resume_url = first_drive_url(hyperlinks[i]) or first_drive_url(cell_resume)
        else:
            resume_url = first_drive_url(cell_resume)
        # Fallback: use hyperlinks from full row (any column may have the file link)
        if not resume_url and i < len(full_range_hyperlinks):
            for cell_url in full_range_hyperlinks[i]:
                if cell_url and "drive.google.com" in str(cell_url):
                    resume_url = first_drive_url(cell_url)
                    break
        # Fallback: scan cell values for Drive URL text
        if not resume_url:
            resume_url = first_drive_url(_find_drive_url_in_row(row))
        # Fallback: parse =HYPERLINK("https://drive.google.com/...", "Link") from formula (how Forms often stores uploads)
        if not resume_url and i < len(formula_rows):
            row_formulas = formula_rows[i] if isinstance(formula_rows[i], (list, tuple)) else []
            for cell in row_formulas:
                if not cell:
                    continue
                cell_str = str(cell).strip()
                if "HYPERLINK" in cell_str and "drive.google.com" in cell_str:
                    url = _extract_url_from_hyperlink_formula(cell_str)
                    if url:
                        resume_url = first_drive_url(url)
                        break

        # File name may be in a separate column (e.g. "File name", "Filename") — use when saving
        submitted_filename = col("resume_filename").strip() if col_map.get("resume_filename") is not None else ""

        resp = {
            "row_number": last_row + i + 1,
            "timestamp":  col("timestamp"),
            "name":       col("name"),
            "email":      col("email"),
            "phone":      col("phone"),
            "resume_url": resume_url,
            "linkedin":   col("linkedin"),
            "resume_filename_from_sheet": submitted_filename,
        }

        if not resp["email"]:
            continue  # skip empty rows

        responses.append(resp)

    return responses, last_row + len(new_rows)


# ════════════════════════════════════════════════════════════════════════════
# STEP 6 — Extract Drive file ID + download resume
# ════════════════════════════════════════════════════════════════════════════

def extract_drive_id(drive_url: str) -> str | None:
    """
    Google Form stores uploaded resume as a Drive URL like:
      https://drive.google.com/open?id=1BxiMVs...
      https://drive.google.com/file/d/1BxiMVs.../view
    """
    if not drive_url or not drive_url.strip():
        return None
    drive_url = drive_url.strip()
    # Take first URL if comma-separated
    if "," in drive_url:
        drive_url = drive_url.split(",")[0].strip()

    # Raw ID (Drive file IDs are typically 25+ chars)
    if re.match(r'^[a-zA-Z0-9_-]{25,}$', drive_url):
        return drive_url

    # /file/d/ID/
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', drive_url)
    if m:
        return m.group(1)

    # ?id=ID
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', drive_url)
    if m:
        return m.group(1)

    return None


def download_resume(file_id: str, creds) -> tuple[bytes, str]:
    """
    Download resume from Google Drive.
    Returns: (file_bytes, filename)
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from googleapiclient.errors import HttpError

    svc = build("drive", "v3", credentials=creds)

    # Get metadata (may raise HttpError 404 if file not found, 403 if no access)
    try:
        meta = svc.files().get(
            fileId=file_id,
            fields="name,mimeType"
        ).execute()
    except HttpError as e:
        if e.resp.status == 404:
            raise FileNotFoundError(f"Drive file not found (id={file_id[:20]}...). Form uploads may be in a different account.") from e
        if e.resp.status == 403:
            raise PermissionError("No permission to access this file. Ensure you're signed in as the form owner.") from e
        raise

    filename  = meta.get("name", "resume.pdf")
    mime_type = meta.get("mimeType", "")

    # Google Docs → export as DOCX
    if mime_type == "application/vnd.google-apps.document":
        req = svc.files().export_media(
            fileId=file_id,
            mimeType="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        filename += ".docx"
    else:
        req = svc.files().get_media(fileId=file_id)

    buf = io.BytesIO()
    dl  = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()

    data = buf.getvalue()
    logger.info(f"Downloaded: {filename} ({len(data)} bytes)")
    return data, filename


# ════════════════════════════════════════════════════════════════════════════
# MAIN CLASS — FormWatcher
# ════════════════════════════════════════════════════════════════════════════

class FormWatcher:
    """
    Watch a Google Form for new responses.
    Automatically downloads resumes from Google Drive.
    
    Usage:
        watcher = FormWatcher(
            form_url="https://docs.google.com/forms/d/.../edit",
            job_id="job_001",
            on_new_response=my_async_callback,
            poll_every=60,
        )
        info = await watcher.setup()
        await watcher.start()            # runs forever (background task)
    
    Callback signature:
        async def my_async_callback(
            response: dict,         # form data (name, email, phone, etc.)
            resume_bytes: bytes,    # raw PDF/DOCX bytes
            resume_filename: str,   # e.g. "Arjun_Resume.pdf"
            job_id: str,
        ): ...
    """

    def __init__(
        self,
        form_url: str,
        job_id: str,
        on_new_response,
        poll_every: int = 60,
        credentials_path: str = None,
        token_path: str = None,
    ):
        self.form_url    = form_url
        self.job_id      = job_id
        self.callback    = on_new_response
        self.poll_every  = poll_every
        self.creds_path  = credentials_path or str(BACKEND_DIR / "credentials.json")
        self.token_path  = token_path or str(BACKEND_DIR / "token.json")

        # filled by setup()
        self.creds       = None
        self.form_id     = None
        self.form_title  = ""
        self.sheet_id    = None
        self.sheet_url   = ""
        self.col_map     = {}
        self.all_headers = []
        self.last_row    = 1        # 1 = skip header row
        self.running     = False
        self.total_processed = 0
        self.last_checked    = None
        self.last_error      = ""

    async def setup(self) -> dict:
        """
        Validate form URL, find linked sheet, read columns.
        Call once before start().
        """
        # Auth
        self.creds = get_google_creds(self.token_path, self.creds_path)

        # Form ID
        self.form_id = extract_form_id(self.form_url)

        # Linked sheet
        info = find_linked_sheet(self.form_id, self.creds)
        self.form_title = info["form_title"]
        self.sheet_id   = info["sheet_id"]
        self.sheet_url  = info["sheet_url"]

        # Columns
        self.col_map, self.all_headers = read_columns(self.sheet_id, self.creds)

        # Count existing rows → only watch NEW responses from now
        from googleapiclient.discovery import build
        svc = build("sheets", "v4", credentials=self.creds)
        existing = svc.spreadsheets().values().get(
            spreadsheetId=self.sheet_id, range="A:A"
        ).execute()
        self.last_row = len(existing.get("values", []))

        existing_count = max(0, self.last_row - 1)  # subtract header
        logger.info(
            f"Ready. Form='{self.form_title}' | "
            f"Existing responses={existing_count} | "
            f"Watching from row {self.last_row + 1}"
        )

        return {
            "form_title":         self.form_title,
            "form_id":            self.form_id,
            "sheet_id":           self.sheet_id,
            "sheet_url":          self.sheet_url,
            "columns_detected":   {k: self.all_headers[v] for k, v in self.col_map.items()
                                   if isinstance(k, str) and isinstance(v, int) and v < len(self.all_headers)},
            "existing_responses": existing_count,
            "watching_from_row":  self.last_row + 1,
        }

    async def start(self):
        """Poll loop — runs forever until stop()."""
        self.running = True
        logger.info(f"Watching '{self.form_title}' every {self.poll_every}s ...")

        while self.running:
            try:
                await self._poll_once()
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"Poll error: {e}")

            self.last_checked = datetime.utcnow()
            await asyncio.sleep(self.poll_every)

    async def stop(self):
        self.running = False

    async def _poll_once(self):
        """One poll cycle."""
        # Refresh expired token
        if self.creds and self.creds.expired and self.creds.refresh_token:
            from google.auth.transport.requests import Request
            self.creds.refresh(Request())

        new_responses, self.last_row = fetch_new_rows(
            self.sheet_id, self.col_map, self.last_row, self.creds
        )

        if new_responses:
            logger.info(f"Poll: found {len(new_responses)} new response(s), processing...")
        else:
            logger.debug(f"Poll: no new responses (last_row={self.last_row})")

        for resp in new_responses:
            try:
                await self._handle(resp)
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"Failed to process row#{resp.get('row_number')}: {e}")
                # Continue with next response so one failure doesn't block the rest

    async def _handle(self, response: dict):
        """Process one form submission: download resume and fire callback."""
        row_num = response.get("row_number", "?")
        resume_url = (response.get("resume_url") or "").strip()
        resume_preview = (resume_url[:70] + "…") if len(resume_url) > 70 else resume_url or "(empty)"

        logger.info(
            f"Row#{row_num} → {response.get('name', '')} <{response.get('email', '')}> | "
            f"resume column: {resume_preview!r}"
        )

        resume_bytes    = None
        resume_filename = "resume.pdf"

        # Download resume from Drive
        if resume_url:
            file_id = extract_drive_id(resume_url)
            if file_id:
                try:
                    resume_bytes, resume_filename = download_resume(file_id, self.creds)
                    logger.info(f"Row#{row_num}: resume downloaded → {resume_filename} ({len(resume_bytes)} bytes)")
                except Exception as e:
                    logger.error(f"Row#{row_num}: resume download failed: {e}")
            else:
                logger.warning(
                    f"Row#{row_num}: could not get Drive ID from resume column (value: {resume_preview!r})"
                )
        else:
            logger.warning(
                f"Row#{row_num}: no resume URL in sheet. "
                "Form needs a File upload question and the response sheet must have that column."
            )

        self.total_processed += 1

        # Fire the callback (saves resume and triggers pipeline)
        try:
            await self.callback(
                response=response,
                resume_bytes=resume_bytes,
                resume_filename=resume_filename,
                job_id=self.job_id,
            )
        except Exception as e:
            logger.error(f"Callback failed for {response.get('email')}: {e}")
            raise

    def status(self) -> dict:
        return {
            "running":         self.running,
            "form_title":      self.form_title,
            "form_url":        self.form_url,
            "job_id":          self.job_id,
            "sheet_id":        self.sheet_id,
            "last_row":        self.last_row,
            "total_processed": self.total_processed,
            "last_checked":    self.last_checked.isoformat() if self.last_checked else None,
            "last_error":      self.last_error,
        }


# ════════════════════════════════════════════════════════════════════════════
# Registry — multiple watchers (one per job)
# ════════════════════════════════════════════════════════════════════════════

class WatcherRegistry:
    def __init__(self):
        self._watchers: dict[str, FormWatcher] = {}
        self._tasks:    dict[str, asyncio.Task]  = {}

    async def add(self, form_url: str, job_id: str, callback, poll_every=60, download_existing: bool = False) -> dict:
        if job_id in self._watchers:
            await self.remove(job_id)

        w = FormWatcher(form_url, job_id, callback, poll_every)
        info = await w.setup()

        # Optionally process all existing responses once (download their resumes)
        if download_existing and info.get("existing_responses", 0) > 0:
            logger.info(f"Downloading resumes for {info['existing_responses']} existing responses...")
            w.last_row = 1  # Process from first data row
            try:
                await w._poll_once()
            except Exception as e:
                logger.error(f"Error processing existing responses: {e}")
            logger.info(f"Existing responses processed. total_processed={w.total_processed}")

        self._watchers[job_id] = w
        self._tasks[job_id]    = asyncio.create_task(w.start())

        return info

    async def remove(self, job_id: str):
        if job_id in self._watchers:
            await self._watchers[job_id].stop()
            del self._watchers[job_id]
        if job_id in self._tasks:
            self._tasks[job_id].cancel()
            del self._tasks[job_id]

    def all_status(self) -> list:
        return [w.status() for w in self._watchers.values()]

    def get(self, job_id: str) -> FormWatcher | None:
        return self._watchers.get(job_id)


watcher_registry = WatcherRegistry()
