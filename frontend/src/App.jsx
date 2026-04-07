import { useState } from "react";
import FormWatcher from "./components/FormWatcher";

export default function App() {
    const [jobs, setJobs] = useState([]);
    const [jobTitle, setJobTitle] = useState("");
    const [showAdd, setShowAdd] = useState(false);

    const addJob = () => {
        if (!jobTitle.trim()) return;
        const id = "job_" + Date.now();
        setJobs((prev) => [
            ...prev,
            { id, title: jobTitle.trim(), createdAt: new Date().toLocaleString() },
        ]);
        setJobTitle("");
        setShowAdd(false);
    };

    const removeJob = (id) => {
        setJobs((prev) => prev.filter((j) => j.id !== id));
    };

    return (
        <div style={styles.page}>
            {/* ── Header ── */}
            <header style={styles.header}>
                <div>
                    <div style={styles.logoRow}>
                        <div style={styles.logoDot} />
                        <h1 style={styles.logoText}>FormWatcher</h1>
                    </div>
                    <p style={styles.subtitle}>
                        Automated Google Form response tracking & resume downloader
                    </p>
                </div>
            </header>

            {/* ── Hero Section ── */}
            {jobs.length === 0 && !showAdd && (
                <div style={styles.hero} className="slide-up">
                    <div style={styles.heroIcon}>📋</div>
                    <h2 style={styles.heroTitle}>Watch Google Forms Automatically</h2>
                    <p style={styles.heroDesc}>
                        Paste a Google Form link for any job opening. The system will
                        automatically detect new responses and download candidate resumes in
                        real-time.
                    </p>

                    <div style={styles.stepsRow}>
                        <Step num="1" text="Create a job & paste your Google Form link" />
                        <div style={styles.stepArrow}>→</div>
                        <Step num="2" text="System connects to the linked response sheet" />
                        <div style={styles.stepArrow}>→</div>
                        <Step num="3" text="Resumes are auto-downloaded on every submission" />
                    </div>

                    <button style={styles.ctaBtn} onClick={() => setShowAdd(true)}>
                        + Add Your First Job
                    </button>
                </div>
            )}

            {/* ── Add Job Form ── */}
            {(showAdd || jobs.length > 0) && (
                <div style={styles.addSection} className="animate-in">
                    <div style={styles.addRow}>
                        <input
                            style={styles.addInput}
                            placeholder="Job title (e.g. Senior Developer, Marketing Intern)"
                            value={jobTitle}
                            onChange={(e) => setJobTitle(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && addJob()}
                        />
                        <button
                            style={{
                                ...styles.addBtn,
                                ...(jobTitle.trim() ? styles.addBtnActive : styles.addBtnDim),
                            }}
                            onClick={addJob}
                            disabled={!jobTitle.trim()}
                        >
                            + Add Job
                        </button>
                    </div>
                </div>
            )}

            {/* ── Job Cards ── */}
            <div style={styles.jobsList}>
                {jobs.map((job, i) => (
                    <div
                        key={job.id}
                        style={{ ...styles.jobCard, animationDelay: `${i * 0.08}s` }}
                        className="slide-up"
                    >
                        <div style={styles.jobHeader}>
                            <div>
                                <h3 style={styles.jobTitle}>{job.title}</h3>
                                <span style={styles.jobMeta}>
                                    {job.id} • created {job.createdAt}
                                </span>
                            </div>
                            <button style={styles.removeBtn} onClick={() => removeJob(job.id)}>
                                ✕
                            </button>
                        </div>
                        <FormWatcher jobId={job.id} jobTitle={job.title} />
                    </div>
                ))}
            </div>

            {/* ── Footer ── */}
            <footer style={styles.footer}>
                <span style={styles.footerText}>
                    Data Wrangling Project — Semester 8
                </span>
            </footer>
        </div>
    );
}

/* ── Step helper component ──────────────────────────────────────────── */
function Step({ num, text }) {
    return (
        <div style={styles.step}>
            <div style={styles.stepNum}>{num}</div>
            <p style={styles.stepText}>{text}</p>
        </div>
    );
}

/* ── Styles ──────────────────────────────────────────────────────────── */
const styles = {
    page: {
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        maxWidth: 860,
        margin: "0 auto",
        padding: "0 24px",
    },

    /* Header */
    header: {
        padding: "40px 0 20px",
        borderBottom: "1px solid rgba(255,255,255,0.04)",
    },
    logoRow: {
        display: "flex",
        alignItems: "center",
        gap: 10,
    },
    logoDot: {
        width: 10,
        height: 10,
        borderRadius: "50%",
        background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
        boxShadow: "0 0 12px rgba(99,102,241,0.4)",
    },
    logoText: {
        fontSize: 22,
        fontWeight: 700,
        background: "linear-gradient(135deg, #e0e7ff, #a5b4fc)",
        WebkitBackgroundClip: "text",
        WebkitTextFillColor: "transparent",
        letterSpacing: "-0.02em",
    },
    subtitle: {
        fontSize: 13,
        color: "rgba(255,255,255,0.3)",
        marginTop: 4,
        letterSpacing: "0.01em",
    },

    /* Hero */
    hero: {
        textAlign: "center",
        padding: "80px 20px 60px",
    },
    heroIcon: {
        fontSize: 48,
        marginBottom: 20,
        filter: "drop-shadow(0 4px 12px rgba(99,102,241,0.3))",
    },
    heroTitle: {
        fontSize: 28,
        fontWeight: 700,
        color: "rgba(255,255,255,0.9)",
        marginBottom: 12,
        letterSpacing: "-0.02em",
    },
    heroDesc: {
        fontSize: 14,
        color: "rgba(255,255,255,0.35)",
        lineHeight: 1.7,
        maxWidth: 500,
        margin: "0 auto 40px",
    },
    stepsRow: {
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        gap: 12,
        marginBottom: 40,
        flexWrap: "wrap",
    },
    step: {
        background: "rgba(255,255,255,0.02)",
        border: "1px solid rgba(255,255,255,0.05)",
        borderRadius: 12,
        padding: "16px 18px",
        maxWidth: 180,
        textAlign: "center",
    },
    stepNum: {
        width: 28,
        height: 28,
        borderRadius: "50%",
        background: "rgba(99,102,241,0.15)",
        color: "#a5b4fc",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 13,
        fontWeight: 600,
        marginBottom: 8,
        fontFamily: "'JetBrains Mono', monospace",
    },
    stepText: {
        fontSize: 12,
        color: "rgba(255,255,255,0.4)",
        lineHeight: 1.5,
    },
    stepArrow: {
        color: "rgba(255,255,255,0.1)",
        fontSize: 20,
        marginTop: 28,
    },
    ctaBtn: {
        padding: "12px 28px",
        background: "linear-gradient(135deg, rgba(99,102,241,0.25), rgba(139,92,246,0.2))",
        border: "1px solid rgba(99,102,241,0.3)",
        borderRadius: 12,
        color: "#c7d2fe",
        fontSize: 14,
        fontWeight: 600,
        cursor: "pointer",
        transition: "all 0.2s",
        letterSpacing: "0.01em",
    },

    /* Add Job */
    addSection: {
        padding: "24px 0 8px",
    },
    addRow: {
        display: "flex",
        gap: 10,
    },
    addInput: {
        flex: 1,
        background: "rgba(255,255,255,0.03)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 12,
        padding: "12px 16px",
        color: "rgba(255,255,255,0.85)",
        fontSize: 14,
        fontFamily: "'Inter', sans-serif",
        outline: "none",
        transition: "border 0.2s",
    },
    addBtn: {
        padding: "12px 22px",
        borderRadius: 12,
        fontSize: 13,
        fontWeight: 600,
        cursor: "pointer",
        border: "1px solid rgba(99,102,241,0.25)",
        transition: "all 0.2s",
        whiteSpace: "nowrap",
    },
    addBtnActive: {
        background: "rgba(99,102,241,0.2)",
        color: "rgba(165,168,255,0.9)",
    },
    addBtnDim: {
        background: "rgba(255,255,255,0.03)",
        color: "rgba(255,255,255,0.2)",
        cursor: "not-allowed",
    },

    /* Job Cards */
    jobsList: {
        display: "flex",
        flexDirection: "column",
        gap: 20,
        padding: "20px 0 40px",
        flex: 1,
    },
    jobCard: {
        background: "rgba(255,255,255,0.01)",
        border: "1px solid rgba(255,255,255,0.04)",
        borderRadius: 18,
        padding: 24,
        transition: "border-color 0.2s",
    },
    jobHeader: {
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        marginBottom: 16,
    },
    jobTitle: {
        fontSize: 16,
        fontWeight: 600,
        color: "rgba(255,255,255,0.85)",
        letterSpacing: "-0.01em",
    },
    jobMeta: {
        fontSize: 11,
        color: "rgba(255,255,255,0.15)",
        fontFamily: "'JetBrains Mono', monospace",
        marginTop: 2,
        display: "block",
    },
    removeBtn: {
        background: "rgba(239,68,68,0.08)",
        border: "1px solid rgba(239,68,68,0.15)",
        borderRadius: 8,
        color: "rgba(252,165,165,0.6)",
        width: 30,
        height: 30,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "pointer",
        fontSize: 12,
        transition: "all 0.15s",
    },

    /* Footer */
    footer: {
        padding: "20px 0 30px",
        borderTop: "1px solid rgba(255,255,255,0.03)",
        textAlign: "center",
    },
    footerText: {
        fontSize: 11,
        color: "rgba(255,255,255,0.12)",
        fontFamily: "'JetBrains Mono', monospace",
    },
};
