FROM mcr.microsoft.com/playwright/python:v1.51.0-noble

WORKDIR /app

# Install pip packages first (before apt installs system Python packages)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browsers already in base image; sync to match installed version
RUN playwright install chromium

# Virtual display + VNC + noVNC for captcha solving via browser
RUN apt-get update && apt-get install -y \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN chmod +x start.sh

ENV PORT=8000
ENV SCRAPER_DEBUG=0
ENV DISPLAY=:99

EXPOSE 8000
EXPOSE 6080

CMD ["./start.sh"]
