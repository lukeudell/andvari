# ============================================================
#  file:       app/Dockerfile
#  purpose:    forecaster image: python 3.12 slim, non-root
#  owner:      Luke Udell
#  spdx:       MIT
#  std:        [STD-05]
#  adr:        none
#  ticket:     none
#  ticket-url: none
#  created:    2026-07-19
# ============================================================
FROM python:3.14-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# SECURITY: Run as non-root to limit container breakout blast radius
RUN useradd -m -u 1000 -s /bin/bash appuser
USER appuser

# Copy application code
COPY . .

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=30s \
  CMD python -c "import os,urllib.request; b=os.getenv('STREAMLIT_SERVER_BASE_URL_PATH','').strip('/'); p='/'+b if b else ''; urllib.request.urlopen('http://localhost:8501'+p+'/_stcore/health')" || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
