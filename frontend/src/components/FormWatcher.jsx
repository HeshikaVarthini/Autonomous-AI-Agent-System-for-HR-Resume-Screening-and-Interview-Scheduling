import { useState, useEffect } from "react";

const API = import.meta.env.VITE_API_URL || "/api";

export default function FormWatcher({ jobId, jobTitle }) {
  const [url, setUrl]               = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [phase, setPhase]           = useState("idle");   // idle|loading|watching|error
  const [info, setInfo]             = useState(null);
  const [errMsg, setErrMsg]         = useState("");
  const [tick, setTick]             = useState(0);
  const [downloadExisting, setDownloadExisting] = useState(false);

  // Refresh status every 10s when watching
  useEffect(() => {
    if (phase !== "watching") return;
    const t = setInterval(() => setTick(x => x + 1), 10000);
    return () => clearInterval(t);
  }, [phase]);

  useEffect(() => {
    if (phase !== "watching" || !jobId) return;
    fetch(`${API}/forms/watchers`)
      .then(r => r.json())
      .then(list => {
        const w = list.find(x => x.job_id === jobId);
        if (w) setInfo(prev => ({ ...prev, ...w }));
      })
      .catch(() => {});
  }, [tick]);

  const connect = async () => {
    if (!url.trim()) return;
    setPhase("loading");
    setErrMsg("");
    try {
      const r = await fetch(`${API}/forms/watch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          form_url: url.trim(),
          job_id: jobId,
          download_existing: downloadExisting,
          job_description: (jobDescription || "").trim(),
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Failed");
      setInfo(data);
      setPhase("watching");
    } catch (e) {
      setErrMsg(e.message);
      setPhase("error");
    }
  };

  const disconnect = async () => {
    await fetch(`${API}/forms/watch/${jobId}`, { method: "DELETE" });
    setPhase("idle");
    setInfo(null);
    setUrl("");
  };

  const pollNow = async () => {
    await fetch(`${API}/forms/poll-now/${jobId}`, { method: "POST" });
    setTick(x => x + 1);
  };

  const downloadExisting = async () => {
    const r = await fetch(`${API}/forms/download-existing/${jobId}`, { method: "POST" });
    const data = await r.json();
    setTick(x => x + 1);
  };

  return (
    <div style={s.card}>
      <style>{css}</style>

      <div style={s.label}>FORM & SCORING — {jobTitle}</div>

      {/* ── IDLE ── */}
      {(phase === "idle" || phase === "error") && (
        <div>
          <div style={s.label}>JOB SKILLS (resumes scored against these)</div>
          <textarea
            style={s.textarea}
            placeholder="e.g. Python, SQL, 3 years experience, communication skills. Resumes scored against these (LLM or keyword)."
            rows={4}
            value={jobDescription}
            onChange={e => setJobDescription(e.target.value)}
          />
          <div style={{ ...s.label, marginTop: 16 }}>GOOGLE FORM LINK</div>
          <div style={s.row}>
            <input
              style={s.input}
              placeholder="https://docs.google.com/forms/d/XXXX/edit (use EDIT link)"
              value={url}
              onChange={e => setUrl(e.target.value)}
              onKeyDown={e => e.key === "Enter" && connect()}
            />
            <button
              style={{ ...s.btn, ...(url ? s.btnActive : s.btnDim) }}
              onClick={connect}
              disabled={!url.trim()}
            >
              Connect →
            </button>
          </div>

          {phase === "error" && (
            <div style={s.errBox}>❌ {errMsg}</div>
          )}

          <label style={s.checkbox}>
            <input
              type="checkbox"
              checked={downloadExisting}
              onChange={e => setDownloadExisting(e.target.checked)}
            />
            Download resumes for existing responses too (when connecting)
          </label>
          <div style={s.hint}>
            Use the form <strong>EDIT</strong> link: open your form in Google Forms and copy the URL from the address bar (it should end with /edit). Do not use the link from Send or Preview.
          </div>
        </div>
      )}

      {/* ── LOADING ── */}
      {phase === "loading" && (
        <div style={s.loading}>
          <span className="spin" style={s.spinner} />
          Connecting to form...
        </div>
      )}

      {/* ── WATCHING ── */}
      {phase === "watching" && info && (
        <div>
          {/* Header */}
          <div style={s.watchHeader}>
            <div style={s.liveRow}>
              <span className="pulse" style={s.liveDot} />
              <span style={s.liveText}>Live — watching for responses</span>
            </div>
            <div style={s.actions}>
              <button style={s.smallBtn} onClick={downloadExisting} title="Download resumes for all existing rows">Download existing</button>
              <button style={s.smallBtn} onClick={pollNow}>Check now</button>
              <button style={s.smallBtnRed} onClick={disconnect}>Disconnect</button>
            </div>
          </div>

          {/* Info grid */}
          <div style={s.infoGrid}>
            <InfoRow label="Form" value={info.form_title} bold />
            <InfoRow label="Existing responses" value={info.existing_responses} />
            <InfoRow label="New responses found" value={info.total_processed ?? 0} accent />
            <InfoRow label="Last checked" value={
              info.last_checked
                ? new Date(info.last_checked).toLocaleTimeString()
                : "pending..."
            } />
            <InfoRow label="Response sheet" value={
              <a href={info.sheet_url} target="_blank" rel="noreferrer"
                style={{ color: "#818cf8", fontSize: 12, textDecoration: "none" }}>
                Open Sheet ↗
              </a>
            } />
            {(info.job_description || "").trim() && (
              <InfoRow label="Job skills" value={`${(info.job_description || "").slice(0, 80)}${(info.job_description || "").length > 80 ? "…" : ""}`} />
            )}
          </div>

          {/* Detected columns */}
          {info.columns_detected && (
            <div style={{ marginTop: 12 }}>
              <div style={s.colLabel}>Auto-detected fields</div>
              <div style={s.tags}>
                {Object.entries(info.columns_detected).map(([k, v]) => (
                  <span key={k} style={{ ...s.tag, ...(k === "resume" ? s.tagAccent : {}) }}>
                    {k}
                  </span>
                ))}
              </div>

              {!info.columns_detected.resume && (
                <div style={s.warn}>
                  ⚠ No file upload column detected. Make sure your form has a
                  "File Upload" question for resumes.
                </div>
              )}
              {!info.columns_detected.email && (
                <div style={s.warn}>
                  ⚠ No email column detected. Check your form has an email field.
                </div>
              )}
            </div>
          )}

          {info.last_error && (
            <div style={s.errBox}>⚠ Last error: {info.last_error}</div>
          )}
        </div>
      )}
    </div>
  );
}

function InfoRow({ label, value, bold, accent }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "5px 0", borderBottom: "1px solid rgba(255,255,255,0.03)"
    }}>
      <span style={{ fontSize: 11, color: "rgba(255,255,255,0.25)", fontFamily: "monospace" }}>
        {label}
      </span>
      <span style={{
        fontSize: 12,
        fontWeight: bold ? 600 : 400,
        color: accent ? "#34d399" : bold ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.5)"
      }}>
        {value}
      </span>
    </div>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────
const s = {
  card: {
    background: "#0f0f1a",
    border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 16,
    padding: 24,
    fontFamily: "'DM Sans', system-ui, sans-serif",
    maxWidth: 580,
  },
  label: {
    fontSize: 10, color: "rgba(255,255,255,0.2)",
    fontFamily: "monospace", textTransform: "uppercase",
    letterSpacing: "0.1em", marginBottom: 16,
  },
  row:    { display: "flex", gap: 10 },
  textarea: {
    width: "100%",
    minHeight: 90,
    background: "rgba(255,255,255,0.03)",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 10,
    padding: "10px 14px",
    color: "rgba(255,255,255,0.8)",
    fontSize: 13,
    outline: "none",
    fontFamily: "inherit",
    resize: "vertical",
  },
  input: {
    flex: 1,
    background: "rgba(255,255,255,0.03)",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 10, padding: "10px 14px",
    color: "rgba(255,255,255,0.8)", fontSize: 13,
    outline: "none", fontFamily: "monospace",
  },
  btn: {
    padding: "10px 18px", borderRadius: 10,
    fontSize: 13, cursor: "pointer",
    border: "1px solid rgba(99,102,241,0.3)",
    transition: "all 0.15s", whiteSpace: "nowrap",
  },
  btnActive: {
    background: "rgba(99,102,241,0.2)", color: "rgba(165,168,255,0.9)",
  },
  btnDim: {
    background: "rgba(255,255,255,0.04)", color: "rgba(255,255,255,0.2)",
    cursor: "not-allowed",
  },
  checkbox: {
    display: "flex", alignItems: "center", gap: 8, marginTop: 10,
    fontSize: 12, color: "rgba(255,255,255,0.5)", cursor: "pointer",
  },
  hint: { marginTop: 10, fontSize: 11, color: "rgba(255,255,255,0.18)" },
  errBox: {
    marginTop: 10, padding: "8px 12px",
    background: "rgba(239,68,68,0.08)",
    border: "1px solid rgba(239,68,68,0.18)",
    borderRadius: 8, color: "rgba(252,165,165,0.85)", fontSize: 12,
  },
  loading: {
    display: "flex", alignItems: "center", gap: 10,
    color: "rgba(255,255,255,0.35)", fontSize: 13, padding: "8px 0",
  },
  spinner: {
    width: 16, height: 16,
    border: "2px solid rgba(99,102,241,0.2)",
    borderTopColor: "#6366f1",
    borderRadius: "50%", display: "inline-block",
  },
  watchHeader: {
    display: "flex", justifyContent: "space-between",
    alignItems: "center", marginBottom: 14,
  },
  liveRow:  { display: "flex", alignItems: "center", gap: 8 },
  liveDot: {
    width: 8, height: 8, borderRadius: "50%",
    background: "#34d399", display: "inline-block",
    boxShadow: "0 0 6px #34d399",
  },
  liveText: { fontSize: 13, color: "rgba(255,255,255,0.65)", fontWeight: 500 },
  actions:  { display: "flex", gap: 6 },
  smallBtn: {
    padding: "4px 10px", background: "rgba(255,255,255,0.05)",
    border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6,
    color: "rgba(255,255,255,0.35)", fontSize: 11, cursor: "pointer",
  },
  smallBtnRed: {
    padding: "4px 10px", background: "rgba(239,68,68,0.08)",
    border: "1px solid rgba(239,68,68,0.15)", borderRadius: 6,
    color: "rgba(252,165,165,0.7)", fontSize: 11, cursor: "pointer",
  },
  infoGrid: {
    background: "rgba(255,255,255,0.02)",
    borderRadius: 10, padding: "4px 12px",
  },
  colLabel: {
    fontSize: 10, color: "rgba(255,255,255,0.2)",
    fontFamily: "monospace", textTransform: "uppercase",
    letterSpacing: "0.08em", marginBottom: 8,
  },
  tags:     { display: "flex", flexWrap: "wrap", gap: 6 },
  tag: {
    padding: "3px 10px",
    background: "rgba(255,255,255,0.04)",
    border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 6, fontSize: 11,
    color: "rgba(255,255,255,0.4)", fontFamily: "monospace",
  },
  tagAccent: {
    background: "rgba(99,102,241,0.12)",
    border: "1px solid rgba(99,102,241,0.25)",
    color: "rgba(165,168,255,0.8)",
  },
  warn: {
    marginTop: 8, fontSize: 11,
    color: "rgba(251,191,36,0.7)", padding: "6px 10px",
    background: "rgba(251,191,36,0.05)",
    border: "1px solid rgba(251,191,36,0.12)",
    borderRadius: 6,
  },
};

const css = `
  @keyframes spin { to { transform: rotate(360deg); } }
  .spin { animation: spin 0.8s linear infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
  .pulse { animation: pulse 2s ease-in-out infinite; }
`;
