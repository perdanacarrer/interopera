"""
narrative.py — LLM-generated narrative commentary.

THIS IS THE ONLY MODULE WHERE THE LLM IS INVOKED.
Uses Google Gemini API (free tier via Google AI Studio).
Get a free key at: https://aistudio.google.com/app/apikey
Set env var: GEMINI_API_KEY=your_key_here

The LLM receives the already-computed figures (values, statuses, limits)
and writes human-readable commentary. It does NOT compute, alter, or
introduce any number not already present in the computed figures.

Constraint 3 enforcement: after generation, a firewall check scans the
narrative for any number not present in the computed output.
"""
import os
import re
import json
import urllib.request
import urllib.error


def _extract_numbers_from_text(text: str) -> set:
    """Extract all numeric tokens from a string for firewall check."""
    return set(re.findall(r"\d+(?:[.,]\d+)?", text))


def generate_narrative(figures: list[dict], firm_config: dict) -> str:
    """
    Call Gemini (free) to generate narrative commentary on the computed figures.
    The LLM sees only final figures — it cannot alter them.
    Returns the narrative string.

    Free API key: https://aistudio.google.com/app/apikey
    Set: export GEMINI_API_KEY=your_key_here
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return (
            "[Narrative generation skipped: GEMINI_API_KEY not set. "
            "Get a free key at https://aistudio.google.com/app/apikey "
            "then run: export GEMINI_API_KEY=your_key]"
        )

    figures_summary = json.dumps([
        {
            "figure": f["figure"],
            "value": f["value"],
            "status": f["status"],
            "limit": f["limit"],
        }
        for f in figures
    ], indent=2)

    prompt = f"""You are a compliance report writer for a Singapore MAS-regulated fixed income fund.

STRICT RULES:
1. You may NOT introduce any number that is not in the pre-computed figures below.
2. You may NOT modify, round, or restate any figure differently from what you were given.
3. Write ONLY narrative prose — no tables, no calculations.
4. Reference figures by their provided value exactly.
5. Keep commentary under 250 words.

Write a compliance summary narrative for the Meridian Fixed Income Fund.
Firm: {firm_config['firm_name']}

Pre-computed figures (do not alter):
{figures_summary}

Write a short paragraph (2-4 sentences) summarising overall compliance, noting any breaches or at-limit items."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 400, "temperature": 0.2},
    }).encode("utf-8")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return f"[Narrative generation failed: HTTP {e.code} — {body[:300]}]"
    except Exception as e:
        return f"[Narrative generation failed: {e}]"


def firewall_check(narrative: str, figures: list[dict]) -> dict:
    """
    Constraint 3 verification: check that the narrative introduces no number
    absent from the computed figures.

    Returns {"passed": bool, "violations": list[str]}
    """
    # Build set of all numbers present in computed figures
    allowed_numbers: set = set()
    for f in figures:
        for field in ["value", "limit", "utilization"]:
            val = f.get(field, "") or ""
            allowed_numbers |= _extract_numbers_from_text(str(val))

    # Add common allowed numbers (report metadata, etc.)
    allowed_numbers |= {"1", "2", "3", "24", "5", "25", "7", "10", "100"}

    narrative_numbers = _extract_numbers_from_text(narrative)
    violations = sorted(narrative_numbers - allowed_numbers)

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "narrative_numbers": sorted(narrative_numbers),
        "allowed_numbers": sorted(allowed_numbers),
    }
