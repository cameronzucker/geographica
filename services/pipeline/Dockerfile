FROM python:3.12-slim

# Install GDAL and build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    python3-gdal \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# Scripts are bind-mounted at runtime, not copied (allows live updates)
WORKDIR /scripts
