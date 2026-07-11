"""
narrative.py — THE ONLY MODULE WHERE THE LLM IS INVOKED.

Uses Google Gemini (free tier).
Get a free key at: https://aistudio.google.com/app/apikey
Set: export GEMINI_API_KEY=your_key_here

Auto-detects available models from your API key at runtime.
Falls back gracefully if all models fail — no error text written to XLSX.
"""
import os, re, json, urllib.request, urllib.error

# Preferred order — best free-tier quota first
# Listed by preference; only models actually available for your key will be tried
PREFERRED_ORDER = [
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

def _numbers(text): return set(re.findall(r"\d+(?:[.,]\d+)?", text))

def _list_available_models(api_key: str) -> list[str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return [
            m["name"].replace("models/", "")
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
    except Exception as e:
        print(f"      [Gemini] Could not list models: {e}")
        return []

def _pick_models(available: list[str]) -> list[str]:
    """Return ordered list of models to try, filtered to what's available."""
    available_set = set(available)
    ordered = [m for m in PREFERRED_ORDER if m in available_set]
    # Also append any remaining flash/lite models not in our preferred list
    for m in available:
        if m not in ordered and ("flash" in m.lower() or "lite" in m.lower()):
            ordered.append(m)
    return ordered if ordered else available[:3]

def generate_narrative(figures: list[dict], firm_config: dict) -> str:
    """Returns narrative text, or '' on any failure. Never returns error strings."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return ""

    print("      Detecting available Gemini models...")
    available = _list_available_models(api_key)
    if not available:
        print("      No models found — narrative skipped.")
        return ""

    models_to_try = _pick_models(available)
    print(f"      Will try: {models_to_try[:3]}")

    summary = json.dumps([
        {"figure": f["figure"], "value": f["value"],
         "status": f["status"], "limit": f["limit"]}
        for f in figures
    ], indent=2)

    prompt = f"""You are a compliance report writer for a Singapore MAS-regulated fixed income fund.

STRICT RULES:
1. Do NOT introduce any number not already in the pre-computed figures below.
2. Do NOT modify or restate any figure differently from what you were given.
3. Write ONLY narrative prose — no tables, no calculations.
4. Reference figures by their exact provided value.
5. Keep commentary under 200 words.

Write a compliance summary narrative for the Meridian Fixed Income Fund.
Firm: {firm_config['firm_name']}

Pre-computed figures (do not alter):
{summary}

Write 3-4 sentences summarising overall compliance, noting any breaches or at-limit items."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 300, "temperature": 0.2},
    }).encode("utf-8")

    for model in models_to_try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={api_key}")
        try:
            req = urllib.request.Request(url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            print(f"      Narrative generated using {model} ✓")
            return text
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (404, 429, 503):
                print(f"      [{model}] HTTP {e.code} — trying next...")
                continue
            print(f"      [{model}] HTTP {e.code}: {body[:150]}")
            continue
        except Exception as e:
            print(f"      [{model}] Error: {e} — trying next...")
            continue

    print("      All Gemini models unavailable — narrative skipped.")
    return ""

def firewall_check(narrative: str, figures: list[dict]) -> dict:
    """Constraint 3: no number in narrative may be absent from computed figures."""
    if not narrative:
        return {"passed": True, "violations": [], "skipped": True}
    allowed = set()
    for f in figures:
        for field in ["value", "limit", "utilization"]:
            allowed |= _numbers(str(f.get(field) or ""))
    allowed |= {"1","2","3","4","5","7","10","24","25","100"}
    nums = _numbers(narrative)
    violations = sorted(nums - allowed)
    return {"passed": len(violations)==0, "violations": violations,
            "narrative_numbers": sorted(nums), "allowed_numbers": sorted(allowed)}
