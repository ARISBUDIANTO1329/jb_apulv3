FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app (includes templates/ and static/)
COPY . .

# Create storage directories
RUN mkdir -p \
    storage/assets/video-raw \
    storage/assets/video \
    storage/assets/video-live \
    storage/assets/video-preview \
    storage/assets/upload_ready \
    storage/assets/livestream-ready \
    storage/assets/mp3 \
    storage/assets/sfx \
    storage/assets/intro \
    storage/assets/thumbnail \
    storage/assets/shorts \
    storage/assets/metadata \
    storage/tmp \
    storage/logs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
