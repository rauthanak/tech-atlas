# ── tech-atlas · API image ────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# a crash inside native code (a C library) prints where it happened, so the log says why the process died
ENV PYTHONFAULTHANDLER=1

# Dependencies first, so code edits don't re-run the slow layers.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Chromium + its system libraries for the Playwright-based crawler.
RUN python -m playwright install --with-deps chromium

COPY . .
RUN pip install --no-cache-dir -e .

EXPOSE 8100
CMD ["./docker-entrypoint.sh"]
