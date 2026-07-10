FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Narrative is auto-enabled if GEMINI_API_KEY is set in environment.
# If key is absent, narrative is skipped gracefully — no crash.
CMD ["python", "main.py", "--firm", "firm_A"]
