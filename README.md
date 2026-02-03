# S3 Load Testing with fio + Network Bandwidth Testing

A Python-based load testing tool that uses `fio` to benchmark S3-compatible storage (MinIO) and `iperf3` for network baseline measurement, providing comprehensive analytical reports.

## Quick Start

```bash
# Docker (recommended for all platforms)

# Start minio server
make minio
# Run S3 load testing only
make loadgen
# Or with network baseline testing
make loadgen-net
```

## Features

- **Parallel Load Profiles**: Runs two different fio profiles concurrently (write + read)
- **S3 Traffic**: Generates real S3 API traffic (PUT/GET) using fio's HTTP/S3 engine
- **Network Baseline**: Optional iperf3 test to measure raw network bandwidth
- **JSON Output**: Captures fio and iperf3 results in JSON format for parsing
- **Metrics Report**: Provides throughput (MB/s), latency (P95/P99), IOPS, and network efficiency

## Development Options

### Docker Environment (Recommended)
Works on all platforms (macOS, Linux, Windows)
Consistent fio build with HTTP/S3 engine support
No dependency issues

```bash
# Start minio server
make minio
# Run S3 load testing only
make loadgen
# Or with network baseline testing
make loadgen-net
```

### Linux IDE Development
**Linux only** - requires fio with HTTP engine support

```bash
# 1. Install dependencies (Ubuntu/Debian)
sudo apt update
sudo apt install -y build-essential git libcurl4-openssl-dev libssl-dev zlib1g-dev iperf3

# 2. Build fio with HTTP engine support
cd /tmp
git clone --depth 1 --branch fio-3.36 https://github.com/axboe/fio.git
cd fio
./configure
make -j$(nproc)
sudo make install

# 3. Verify HTTP engine is available
fio --enghelp | grep http

# 4. Setup Python environment
cd app
pip install -r requirements.txt

# 5. Start MinIO and run
docker compose up -d minio
python runner.py
```

### Important Notes
- **macOS**: Use Docker only (fio HTTP engine deprecated/unavailable)
- **Windows**: Use Docker only (WSL2 + Docker recommended)
- **Linux**: Both Docker and local IDE development supported

## Running Tests

### Docker Commands (Recommended)
```bash
make help        # Show available commands
make minio       # Start only MinIO container (for local IDE development)"
make run         # Start MinIO and loadgen, show results in terminal"
make loadgen     # Start only loadgen container (requires MinIO running) for S3 tests only"
make loadgen-net # Start loadgen with iperf3 network baseline test (S3 tests + network baseline)"
make stop        # Stop all containers"
make clean       # Stop and remove all containers, volumes"
make logs        # Show logs from all containers"
```

### Linux IDE Commands

**Prerequisites:** fio with HTTP engine, MinIO running (`make minio`)

```bash
cd app
pip install -r requirements.txt

# Basic S3 test
python runner.py

# S3 test + network baseline
IPERF3_ENABLED=true python runner.py
```

# Custom configuration
export S3_ENDPOINT="http://localhost:9000"
export IPERF3_ENABLED=true
export FIO_RUNTIME=60
export FIO_NUMJOBS_A=4
export FIO_NUMJOBS_B=4
python runner.py
```

**Auto-detection features:**
- **Environment**: Docker vs Host detection
- **S3 endpoint**: `minio:9000` (Docker) vs `localhost:9000` (Host)
- **iperf3 server**: Uses container (Docker) vs starts local daemon (Host)
- **Cleanup**: Automatically stops local iperf3 server after tests

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_ENDPOINT` | `http://minio:9000` | S3 endpoint URL |
| `S3_ACCESS_KEY` | `minioadmin` | S3 access key |
| `S3_SECRET_KEY` | `minioadmin` | S3 secret key |
| `S3_BUCKET` | `fio-bench` | Target bucket name |
| `S3_REGION` | `us-east-1` | S3 region |
| `FIO_RUNTIME` | `60` | Test runtime in seconds |
| `FIO_RAMP_TIME` | `5` | Ramp-up time in seconds |
| `FIO_OBJECT_SIZE` | `4M` | Object size for tests |
| `FIO_PROFILE_A` | `profiles/profile_write.ini` | Write profile path |
| `FIO_PROFILE_B` | `profiles/profile_read.ini` | Read profile path |
| `FIO_NUMJOBS_A` | `4` | Number of parallel jobs for profile A |
| `FIO_NUMJOBS_B` | `4` | Number of parallel jobs for profile B |
| `IPERF3_ENABLED` | `false` | Enable network baseline test |
| `IPERF3_SERVER` | `iperf3-server` (Docker), `localhost` (host) | iperf3 server hostname |
| `IPERF3_DURATION` | `10` | iperf3 test duration in seconds |

**Note:** The script auto-detects the environment and sets appropriate defaults:
- **Docker**: `S3_ENDPOINT=http://minio:9000`, `IPERF3_SERVER=iperf3-server`
- **Host**: `S3_ENDPOINT=http://localhost:9000`, `IPERF3_SERVER=localhost`

## Example Output

```
============================================================
=== S3 Load Testing + Network Bandwidth Report ===
============================================================
Endpoint: http://minio:9000
Bucket: fio-bench
Block Size: 4M
Jobs: write=2, read=2

[Network Baseline - iperf3]
  Bandwidth (send): 9420.5 Mbps (1177.6 MB/s)
  Bandwidth (receive): 9420.5 Mbps (1177.6 MB/s)
  Test duration: 10s
  Data transferred: 11776.0 MB

[Profile A: write] ✓ Real S3 traffic
  HTTP PUT requests: 200
  Data transferred: 800.0 MB
  Runtime: 1573 ms
  Throughput: 508.58 MB/s
  IOPS: 127.15
  Latency P95: 17.96 ms
  Latency P99: 21.89 ms

[Profile B: read] ⚠ CACHED - not real S3 traffic
  HTTP GET requests: 100
  Data transferred: 400.0 MB
  Runtime: 18 ms
  Throughput: 22222.22 MB/s (FROM MEMORY CACHE)
  Estimated real throughput: ~763 MB/s
  IOPS: 5555.56
  Latency P95: 0.82 ms
  Latency P99: 3.56 ms

[Summary]
  Network capacity: 1177.6 MB/s
  S3 write efficiency: 43.2% of network capacity
  Total HTTP requests: 300
  Total data: 1200.0 MB
  Total IOPS: 5682.70
  Write throughput: 508.58 MB/s ✓
  Read throughput: CACHED (see note below)
  Latency P95 (worst): 17.96 ms
  Latency P99 (worst): 21.89 ms
============================================================
```

## Known Limitations

### fio HTTP Engine Caching

**Write operations** are accurate - each write is a real HTTP PUT request to S3.

**Read operations** show inflated throughput because fio HTTP engine caches data in memory after the first HTTP GET. Subsequent "reads" are from RAM, not from S3.

For accurate S3 **read** benchmarks, use specialized tools:
- [MinIO warp](https://github.com/minio/warp) - Official MinIO benchmark tool
- [s3-benchmark](https://github.com/wasabi-tech/s3-benchmark) - Wasabi S3 benchmark

### iperf3 Network Baseline

**Why include iperf3?** It helps diagnose performance bottlenecks:

- **Network bottleneck**: Low iperf3 + low S3 performance = network issue
- **S3/storage bottleneck**: High iperf3 + low S3 performance = storage issue
- **Efficiency measurement**: S3 write efficiency = (S3 throughput / network capacity) * 100%

**Note**: iperf3 is disabled by default. Enable with `IPERF3_ENABLED=true`.

## Project Structure

```
.
├── docker-compose.yml      # Docker Compose configuration
├── Makefile                # Build and run commands
├── README.md               # This file
├── GUIDELINES.md           # Development guidelines
├── out/                    # Output directory for fio JSON results
└── app/
    ├── Dockerfile          # Container build instructions
    ├── requirements.txt    # Python dependencies
    ├── runner.py           # Main application
    └── profiles/
        ├── profile_write.ini   # fio write profile
        └── profile_read.ini    # fio read profile
```

## Output Artifacts

Raw fio JSON outputs are saved to `./out/` directory for further analysis.

## MinIO Console

Access the MinIO web console at http://localhost:9001 (credentials: minioadmin/minioadmin)

## Notes

- **Write metrics are accurate** - real HTTP PUT requests
- **Read metrics show cache speed** - see "Known Limitations" above  
- **Auto-environment detection** - works seamlessly in Docker and on host
- **iperf3 auto-management** - starts/stops local server automatically when needed
- Results vary based on hardware, network, and storage performance
- For production benchmarks, increase `FIO_RUNTIME` and `FIO_NUMJOBS`

### Quick Examples

```bash
# Docker - S3 + network (recommended for all platforms)
make loadgen-net

# Docker - S3 only  
make loadgen

# Linux IDE - full S3 testing (requires fio with HTTP engine)
cd app && python runner.py

# Linux IDE - network only testing
cd app && IPERF3_ENABLED=true python runner.py
```

## Known Limitations

1. **Read Caching**: fio HTTP engine caches read data, showing memory speed rather than true S3 speed
2. **Platform Dependency**: Docker provides most consistent results across platforms
3. **S3 Engine Availability**: Platform-dependent; use Docker for guaranteed compatibility

For production S3 benchmarking, consider specialized tools:
- [minio/warp](https://github.com/minio/warp) - MinIO's official benchmarking tool
- [s3-benchmark](https://github.com/wasabi-tech/s3-benchmark) - Dedicated S3 performance testing

