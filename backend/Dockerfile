FROM python:3.11-slim

WORKDIR /app

# System deps required by Playwright's Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgtk-3-0 libx11-xcb1 libxss1 wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8001", "--workers", "1", \
     "--no-server-header", "--no-date-header"]
