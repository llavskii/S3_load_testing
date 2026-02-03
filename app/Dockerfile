FROM python:3.12-slim

# Install build dependencies for fio with HTTP/S3 support and iperf3
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    libcurl4-openssl-dev \
    libssl-dev \
    zlib1g-dev \
    curl \
    iperf3 \
    && rm -rf /var/lib/apt/lists/*

# Build fio from source with HTTP engine support
# HTTP engine is enabled automatically when libcurl is found
RUN git clone --depth 1 --branch fio-3.36 https://github.com/axboe/fio.git /tmp/fio \
    && cd /tmp/fio \
    && ./configure \
    && make -j$(nproc) \
    && make install \
    && rm -rf /tmp/fio

# Verify fio has http engine
RUN fio --enghelp | grep -q http || (echo "ERROR: fio http engine not available" && exit 1)

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p /app/out

CMD ["python", "runner.py"]

