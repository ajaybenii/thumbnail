FROM python:3.10-slim

# Install system dependencies and chromium-browser
RUN apt-get update && apt-get install -y \
    chromium-browser \
    chromium-codecs-ffmpeg-extra \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-xcb1 \
    libxcb1-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext1 \
    libxfixes1 \
    libxi1 \
    libxrandr1 \
    libxrender1 \
    libxss1 \
    libxtst1 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/

# Set working directory
WORKDIR /app

# Copy application files
COPY requirements.txt .
COPY app.py .
COPY Procfile .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables
ENV PYPPETEER_EXECUTABLE_PATH=/usr/bin/chromium-browser
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE $PORT

# Start Streamlit
CMD ["streamlit", "run", "app.py", "--server.port", "$PORT", "--server.address", "0.0.0.0"]