FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run Firm A. Override with: docker compose run app python main.py --firm firm_B
CMD ["python", "main.py", "--firm", "firm_A", "--no-narrative"]
