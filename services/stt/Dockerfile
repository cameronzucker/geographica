FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for faster-whisper (CTranslate2)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download and bake in the base.en CTranslate2 model (~140MB)
# This ensures the container works offline immediately
RUN python3 -c "\
from faster_whisper.utils import download_model; \
download_model('base.en', output_dir='/opt/models/faster-whisper-base.en')"

# Copy application code
COPY main.py ./
COPY backends/ ./backends/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
