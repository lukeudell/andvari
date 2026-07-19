FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# SECURITY: non-root. /app is chowned so the generator can write generated/.
RUN useradd -m -u 1000 -s /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser . .
RUN chmod +x seed.sh

CMD ["./seed.sh"]
