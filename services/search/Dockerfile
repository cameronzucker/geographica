FROM python:3.12-slim

WORKDIR /app

# gdal-bin provides `ogr2ogr`, needed by refresh_noaa_catalog.py's
# fetch_tile_count() to count features in NOAA tile-index shapefiles.
RUN apt-get update && apt-get install -y --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py spatial.py geocode.py keyring_client.py ./

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
