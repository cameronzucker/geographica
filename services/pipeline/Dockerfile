FROM python:3.12-slim

# Install GDAL, rasterio build deps, and ogr2ogr (for NOAA tile index)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    python3-gdal \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# Scripts are bind-mounted at runtime, not copied (allows live updates)
WORKDIR /scripts
