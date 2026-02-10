FROM python:3.13-slim

WORKDIR /app

# Pillow için gerekli runtime dependencies
RUN apt-get update && apt-get install -y \
    libjpeg62-turbo \
    zlib1g \
    libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Requirements'ı kur
RUN pip install --no-cache-dir -r requirements.txt

# Pillow'u binary olarak kur
RUN pip install --no-cache-dir --only-binary :all: Pillow

COPY . .

# Railway $PORT'u kullan (default 8000)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
