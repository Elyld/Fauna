FROM python:3.12-slim
WORKDIR /srv/fauna
# ffmpeg: BirdNET (via librosa) needs it to read webm/mp4 phone recordings.
# tuc.cloud: allow the BirdNET model download (~230MB) at build time so the
# first Sound ID analysis is instant instead of downloading on first use.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from birdnet_analyzer.utils import ensure_model_exists; ensure_model_exists()" || \
    echo "WARNING: BirdNET model pre-download failed; it will download on first Sound ID use"
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
