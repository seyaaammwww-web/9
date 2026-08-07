# Playwright base: Chromium + OS deps included
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

USER root
RUN mkdir -p /app /app/data && chown -R 1000:1000 /app

USER 1000
ENV PATH=/home/pwuser/.local/bin:/home/ubuntu/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV HOME=/home/pwuser

WORKDIR /app

COPY --chown=1000:1000 requirements.txt .
RUN pip install --no-cache-dir --default-timeout=1000 -r requirements.txt

# App sources only (see .dockerignore)
COPY --chown=1000:1000 . /app

# Health / webhook listener used by main.py
EXPOSE 7860

CMD ["python", "-u", "main.py"]
