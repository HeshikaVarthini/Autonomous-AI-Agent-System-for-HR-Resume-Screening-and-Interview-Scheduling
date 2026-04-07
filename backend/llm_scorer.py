"""
backend/llm_scorer.py
=====================
Score resume against job description using an LLM.
Uses Groq Cloud (free tier, fast). Set GROQ_API_KEY in environment.
Falls back to keyword extraction when no key or API fails.
"""
import json
import os
import re
import logging

logger = logging.getLogger(__name__)

# Truncate resume/job text to stay within model context
MAX_RESUME_CHARS = 6000
MAX_JD_CHARS = 2000

# Groq: free tier, OpenAI-compatible API. Get key at https://console.groq.com
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# 70B follows instructions better for role-fit scoring; 8b is faster but often ignores "fit only"
GROQ_MODEL = "llama-3.3-70b-versatile"


def _extract_keywords_from_jd(job_description: str, max_keywords: int = 15) -> list[str]:
    """Simple heuristic: take significant words (skip common stop words)."""
    if not job_description or not job_description.strip():
        return []
    stop = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
        "by", "from", "as", "is", "was", "are", "were", "been", "be", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should", "may", "might", "must",
        "this", "that", "these", "those", "it", "its", "we", "our", "you", "your",
        "years", "year", "experience", "required", "preferred", "ability", "skills",
    }
    words = re.findall(r"\b[a-zA-Z]{3,}\b", job_description.lower())
    seen = set()
    out = []
    for w in words:
        if w not in stop and w not in seen:
            seen.add(w)
            out.append(w)
            if len(out) >= max_keywords:
                break
    return out


def score_resume_with_llm(
    job_description: str,
    resume_text: str,
    threshold: float = 50,
    api_key: str = None,
) -> dict:
    """
    Use Groq API to score how well the resume matches the job description.
    Returns: {"score": 0-100, "above_threshold": bool, "reasoning": str, "source": "llm"|"keyword_fallback"}
    """
    api_key = api_key or os.environ.get("GROQ_API_KEY")
    jd = (job_description or "").strip()[:MAX_JD_CHARS]
    resume = (resume_text or "").strip()[:MAX_RESUME_CHARS]

    if not resume:
        return {
            "score": 0,
            "above_threshold": False,
            "reasoning": "Resume text could not be extracted.",
            "source": "none",
        }

    if api_key and jd:
        try:
            import openai
            client = openai.OpenAI(
                base_url=GROQ_BASE_URL,
                api_key=api_key,
            )
            system_msg = """You are a strict HR screener. You score ONLY how well the candidate fits the given role.

CRITICAL: Score = fit to the role, NOT resume quality. If the role is "Creator" (content, storytelling, video, design, branding) and the resume is only Python/SQL/data — give a LOW score (e.g. 15-35). If the role is "Data Engineer" and the resume is content/writing — also LOW. Never give a high score when the resume's main focus does not match the role's main focus. Your reasoning must state whether the resume matches the role or not (e.g. "Poor fit: role requires X, resume emphasizes Y.")."""

            user_msg = f"""JOB/ROLE:
{jd}

RESUME:
{resume}

Output ONLY valid JSON, no other text:
{{"score": <0-100 fit to role only>, "above_threshold": <true if score >= {threshold}>, "reasoning": "<1-2 sentences: does resume match this role? Why or why not?>"}}"""

            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
            )
            raw = (resp.choices[0].message.content or "").strip()
            # Strip markdown code block if present
            if raw.startswith("```"):
                raw = re.sub(r"^```\w*\n?", "", raw).strip()
                raw = re.sub(r"\n?```$", "", raw).strip()
            data = json.loads(raw)
            return {
                "score": int(data.get("score", 0)),
                "above_threshold": bool(data.get("above_threshold", False)),
                "reasoning": str(data.get("reasoning", ""))[:500],
                "source": "llm",
            }
        except Exception as e:
            logger.warning("LLM scoring failed, using keyword fallback: %s", e)
            print(f"  [LLM skipped] Groq API failed: {e} → using keyword match instead.")

    # Fallback: extract keywords from job description and score by presence in resume
    if not api_key and jd:
        print("  [LLM skipped] No GROQ_API_KEY in environment → using keyword match.")
    elif api_key and not jd:
        print("  [LLM skipped] No job skills text → using keyword match.")
    keywords = _extract_keywords_from_jd(jd) if jd else []
    if not keywords:
        return {
            "score": 100,
            "above_threshold": True,
            "reasoning": "No job description provided; no keyword check.",
            "source": "keyword_fallback",
        }
    resume_lower = resume.lower()
    matched = [k for k in keywords if k in resume_lower]
    score = round(100 * len(matched) / len(keywords))
    above = score >= threshold
    return {
        "score": score,
        "above_threshold": above,
        "reasoning": f"Matched {len(matched)}/{len(keywords)} terms from job description." + (
            f" Matched: {', '.join(matched[:10])}." if matched else ""
        ),
        "source": "keyword_fallback",
        "matched_keywords": matched,
        "missing_keywords": [k for k in keywords if k not in resume_lower],
    }
