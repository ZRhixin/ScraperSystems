FROM mcr.microsoft.com/playwright/python:v1.51.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browsers already installed in base image; install only chromium
RUN playwright install chromium

COPY . .

ENV PORT=8000
ENV SCRAPER_DEBUG=0

EXPOSE 8000

CMD ["python", "server.py"]
