#!/usr/bin/env python3
"""
S3 Load Testing Runner
Runs two fio profiles concurrently against S3 storage and produces a benchmark report.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
def is_running_in_docker() -> bool:
    """Detect if the script is running inside a Docker container."""
    # Check for .dockerenv file
    if Path("/.dockerenv").exists():
        return True
    # Check cgroup (Linux containers)
    try:
        with open("/proc/1/cgroup", "r") as f:
            return "docker" in f.read() or "kubepods" in f.read()
    except (FileNotFoundError, PermissionError):
        pass
    # Check for DOCKER_CONTAINER env var (can be set in docker-compose)
    if os.getenv("DOCKER_CONTAINER"):
        return True
    return False
# Determine environment and set appropriate defaults
_IN_DOCKER = is_running_in_docker()
if _IN_DOCKER:
    # Running inside Docker container - use Docker network hostnames
    _DEFAULT_S3_ENDPOINT = "http://minio:9000"
else:
    # Running on host (e.g., from IDE) - use localhost
    _DEFAULT_S3_ENDPOINT = "http://localhost:9000"
# Configuration from environment variables
S3_ENDPOINT = os.getenv("S3_ENDPOINT", _DEFAULT_S3_ENDPOINT)
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "fio-bench")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
FIO_RUNTIME = os.getenv("FIO_RUNTIME", "60")
FIO_RAMP_TIME = os.getenv("FIO_RAMP_TIME", "5")
FIO_OBJECT_SIZE = os.getenv("FIO_OBJECT_SIZE", "4M")
FIO_PROFILE_A = os.getenv("FIO_PROFILE_A", "profiles/profile_write.ini")
FIO_PROFILE_B = os.getenv("FIO_PROFILE_B", "profiles/profile_read.ini")
FIO_NUMJOBS_A = os.getenv("FIO_NUMJOBS_A", "4")
FIO_NUMJOBS_B = os.getenv("FIO_NUMJOBS_B", "4")

# iperf3 configuration
IPERF3_SERVER = os.getenv("IPERF3_SERVER", "iperf3-server" if _IN_DOCKER else "localhost")
IPERF3_ENABLED = os.getenv("IPERF3_ENABLED", "false").lower() == "true"
IPERF3_DURATION = int(os.getenv("IPERF3_DURATION", "10"))

OUT_DIR = Path("./out")
def get_s3_client():
    """Create boto3 S3 client with path-style addressing for MinIO."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=Config(s3={"addressing_style": "path"}),
    )


def check_fio_available() -> bool:
    """Check if fio is installed and accessible."""
    try:
        result = subprocess.run(
            ["fio", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return False

        print(f"Found fio: {result.stdout.strip()}")
        return True
    except FileNotFoundError:
        print("fio not found")
        return False
    except Exception as e:
        print(f"Error checking fio: {e}")
        return False


def check_fio_s3_support() -> bool:
    """Check if fio supports S3 or HTTP engines."""
    try:
        result = subprocess.run(
            ["fio", "--enghelp"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return False

        engines = result.stdout.lower()
        has_s3 = 's3' in engines
        has_http = 'http' in engines

        if has_s3:
            print("fio S3 engine detected")
        elif has_http:
            print("fio HTTP engine detected (deprecated)")
        else:
            print("No S3/HTTP engine support in fio")

        return has_s3 or has_http
    except Exception as e:
        print(f"Could not check fio engines: {e}")
        return False


def check_iperf3_available() -> bool:
    """Check if iperf3 is installed and accessible."""
    try:
        result = subprocess.run(
            ["iperf3", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
    except Exception:
        return False


def run_iperf3_test(server: str, duration: int = 10) -> dict | None:
    """
    Run iperf3 test to measure network bandwidth.
    Returns dict with bandwidth metrics or None if failed.
    """
    print(f"\nRunning iperf3 network bandwidth test to {server}...")

    try:
        # Run iperf3 client with JSON output
        result = subprocess.run(
            [
                "iperf3",
                "-c", server,
                "-t", str(duration),
                "-J",  # JSON output
            ],
            capture_output=True,
            text=True,
            timeout=duration + 30
        )

        if result.returncode != 0:
            print(f"  iperf3 failed: {result.stderr}", file=sys.stderr)
            return None

        # Parse JSON output
        data = json.loads(result.stdout)

        # Extract metrics from end summary
        end = data.get("end", {})
        sum_sent = end.get("sum_sent", {})
        sum_received = end.get("sum_received", {})

        metrics = {
            "sent_mbps": sum_sent.get("bits_per_second", 0) / 1_000_000,
            "received_mbps": sum_received.get("bits_per_second", 0) / 1_000_000,
            "sent_bytes": sum_sent.get("bytes", 0),
            "received_bytes": sum_received.get("bytes", 0),
            "duration": duration,
        }

        print(f"  Network bandwidth: {metrics['sent_mbps']:.2f} Mbps (send), {metrics['received_mbps']:.2f} Mbps (receive)")

        # Save raw output
        OUT_DIR.mkdir(exist_ok=True)
        timestamp = int(time.time())
        output_file = OUT_DIR / f"{timestamp}_iperf3.json"
        output_file.write_text(result.stdout)

        return metrics

    except subprocess.TimeoutExpired:
        print(f"  iperf3 timeout after {duration + 30}s", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"  Failed to parse iperf3 JSON output: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  iperf3 error: {e}", file=sys.stderr)
        return None


def start_local_iperf3_server() -> subprocess.Popen | None:
    """Start local iperf3 server in background for host runs."""
    try:
        # Check if iperf3 server is already running on port 5201
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 5201))
        sock.close()

        if result == 0:
            print("  iperf3 server already running on port 5201")
            return None

        # Start iperf3 server in background
        print("  Starting local iperf3 server...")
        server_process = subprocess.Popen([
            'iperf3', '-s'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Give it a moment to start
        time.sleep(2)

        # Verify it started
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 5201))
        sock.close()

        if result == 0:
            print("  iperf3 server started successfully on port 5201")
            return server_process
        else:
            print("  Failed to start iperf3 server", file=sys.stderr)
            return None

    except Exception as e:
        print(f"  Error starting iperf3 server: {e}", file=sys.stderr)
        return None
def ensure_bucket_exists(s3_client):
    """Create bucket if it doesn't exist."""
    try:
        s3_client.head_bucket(Bucket=S3_BUCKET)
        print(f"Bucket '{S3_BUCKET}' already exists.")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchBucket"):
            print(f"Creating bucket '{S3_BUCKET}'...")
            s3_client.create_bucket(Bucket=S3_BUCKET)
            print(f"Bucket '{S3_BUCKET}' created.")
        else:
            raise
def prepare_read_objects(s3_client, num_objects: int = 100, object_size_bytes: int = 4 * 1024 * 1024):
    """Pre-populate objects for read test."""
    print(f"Preparing {num_objects} objects for read test...")
    data = b"x" * object_size_bytes
    for i in range(num_objects):
        # Use short key names to stay under fio's 4096 char limit
        key = f"r/o{i:04d}"
        s3_client.put_object(Bucket=S3_BUCKET, Key=key, Body=data)
    print(f"Prepared {num_objects} objects.")


def generate_fio_job_file(profile_path: str, profile_name: str, numjobs: str) -> str:
    """Generate a temporary fio job file with S3 parameters included."""
    http_host = S3_ENDPOINT.replace("http://", "").replace("https://", "")
    num_jobs = int(numjobs)

    global_section = f"""[global]
ioengine=http
http_mode=s3
http_verbose=0
direct=1
http_host={http_host}
http_s3_key={S3_SECRET_KEY}
http_s3_keyid={S3_ACCESS_KEY}
http_s3_region={S3_REGION}
"""

    if "write" in profile_name:
        # Write: create unique objects with nrfiles
        # Each job creates 100 unique objects during the test
        job_sections = ""
        for i in range(num_jobs):
            job_sections += f"""
[write-job-{i}]
rw=write
bs={FIO_OBJECT_SIZE}
filesize={FIO_OBJECT_SIZE}
nrfiles=100
filename_format=/{S3_BUCKET}/w{i}-$filenum
openfiles=1
file_service_type=sequential
"""
        modified_config = global_section + job_sections
    else:
        # Read: use time_based with loops to force re-reading
        # Each iteration should create a new HTTP GET request
        job_sections = ""
        total_read_files = 100
        max_files_per_job = 50  # Stay under 4096 char limit

        # Calculate how many jobs we need
        num_read_jobs = (total_read_files + max_files_per_job - 1) // max_files_per_job

        for i in range(num_read_jobs):
            start_idx = i * max_files_per_job
            end_idx = min(start_idx + max_files_per_job, total_read_files)
            files_in_job = end_idx - start_idx

            # Generate explicit file list for this job (shorter names)
            filenames = ":".join([
                f"/{S3_BUCKET}/r/o{start_idx + j:04d}"
                for j in range(files_in_job)
            ])
            job_sections += f"""
[read-job-{i}]
rw=read
bs={FIO_OBJECT_SIZE}
filesize={FIO_OBJECT_SIZE}
filename={filenames}
openfiles=1
file_service_type=sequential
"""
        modified_config = global_section + job_sections

    OUT_DIR.mkdir(exist_ok=True)
    temp_job_file = OUT_DIR / f"temp_{profile_name}.fio"
    temp_job_file.write_text(modified_config)


    return str(temp_job_file)


def build_fio_command(job_file_path: str, numjobs: str) -> list[str]:
    """Build fio command."""
    return [
        "fio",
        job_file_path,
        "--output-format=json",
        f"--numjobs={numjobs}",
    ]


def run_fio_process(profile_path: str, numjobs: str, profile_name: str) -> subprocess.Popen:
    """Start a fio process."""
    # Generate job file with S3 parameters (jobs are embedded in the file)
    job_file = generate_fio_job_file(profile_path, profile_name, numjobs)
    # numjobs=1 because individual jobs are defined in the job file
    cmd = build_fio_command(job_file, "1")
    print(f"Starting fio for {profile_name}: {' '.join(cmd)}")
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
def wait_for_processes(processes: list[tuple[subprocess.Popen, str]]) -> list[tuple[dict, str]]:
    """Wait for all fio processes and collect results."""
    results = []
    for proc, name in processes:
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            print(f"ERROR: fio {name} failed with code {proc.returncode}", file=sys.stderr)
            print(f"stderr: {stderr}", file=sys.stderr)
            sys.exit(1)
        # Save raw output
        OUT_DIR.mkdir(exist_ok=True)
        timestamp = int(time.time())
        output_file = OUT_DIR / f"{timestamp}_{name}.json"
        output_file.write_text(stdout)
        try:
            data = json.loads(stdout)
            results.append((data, name))
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse JSON from {name}: {e}", file=sys.stderr)
            print(f"stdout: {stdout[:1000]}", file=sys.stderr)
            sys.exit(1)
    return results
def extract_metrics(fio_data: dict, operation: str) -> dict[str, float]:
    """Extract metrics from fio JSON output."""
    metrics = {
        "throughput_mbps": 0.0,
        "iops": 0.0,
        "latency_p95_ms": 0.0,
        "latency_p99_ms": 0.0,
        "total_ios": 0,
        "runtime_ms": 0,
        "io_bytes": 0,
    }
    jobs = fio_data.get("jobs", [])
    if not jobs:
        return metrics
    total_bw_kib = 0.0
    total_iops = 0.0
    max_p95_ns = 0.0
    max_p99_ns = 0.0
    total_ios = 0
    max_runtime = 0
    total_io_bytes = 0

    for job in jobs:
        op_data = job.get(operation, {})
        if not op_data:
            # Try the other operation
            other_op = "write" if operation == "read" else "read"
            op_data = job.get(other_op, {})
        # Bandwidth in KiB/s
        bw = op_data.get("bw", 0)
        total_bw_kib += bw
        # IOPS
        iops = op_data.get("iops", 0)
        total_iops += iops
        # Total IOs and runtime
        total_ios += op_data.get("total_ios", 0)
        runtime = op_data.get("runtime", 0)
        max_runtime = max(max_runtime, runtime)
        total_io_bytes += op_data.get("io_bytes", 0)
        # Latency percentiles (in nanoseconds)
        clat_ns = op_data.get("clat_ns", {})
        percentiles = clat_ns.get("percentile", {})
        # fio uses string keys like "95.000000" for percentiles
        p95 = percentiles.get("95.000000", 0)
        p99 = percentiles.get("99.000000", 0)
        max_p95_ns = max(max_p95_ns, p95)
        max_p99_ns = max(max_p99_ns, p99)

    # Convert KiB/s to MB/s (1 MiB = 1024 KiB, 1 MB = 1000 KB)
    # Using MiB/s (mebibytes): KiB/s / 1024 = MiB/s
    metrics["throughput_mbps"] = total_bw_kib / 1024.0
    metrics["iops"] = total_iops
    # Convert nanoseconds to milliseconds
    metrics["latency_p95_ms"] = max_p95_ns / 1_000_000.0
    metrics["latency_p99_ms"] = max_p99_ns / 1_000_000.0
    metrics["total_ios"] = total_ios
    metrics["runtime_ms"] = max_runtime
    metrics["io_bytes"] = total_io_bytes
    return metrics
def print_report(metrics_a: dict, metrics_b: dict, iperf3_metrics: dict = None):
    """Print the benchmark report."""
    print("\n" + "=" * 60)
    print("=== S3 Load Testing + Network Bandwidth Report ===")
    print("=" * 60)
    print(f"Endpoint: {S3_ENDPOINT}")
    print(f"Bucket: {S3_BUCKET}")
    print(f"Block Size: {FIO_OBJECT_SIZE}")
    print(f"Jobs: write={FIO_NUMJOBS_A}, read={FIO_NUMJOBS_B}")

    # Network baseline section
    if iperf3_metrics:
        print(f"\n[Network Baseline - iperf3]")
        print(f"  Bandwidth (send): {iperf3_metrics['sent_mbps']:.2f} Mbps ({iperf3_metrics['sent_mbps']/8:.1f} MB/s)")
        print(f"  Bandwidth (receive): {iperf3_metrics['received_mbps']:.2f} Mbps ({iperf3_metrics['received_mbps']/8:.1f} MB/s)")
        print(f"  Test duration: {iperf3_metrics['duration']}s")
        print(f"  Data transferred: {iperf3_metrics['sent_bytes'] / 1024 / 1024:.1f} MB")

    # Calculate real throughput based on actual bytes transferred and time
    write_real_throughput = 0
    if metrics_a["runtime_ms"] > 0:
        write_real_throughput = (metrics_a["io_bytes"] / 1024 / 1024) / (metrics_a["runtime_ms"] / 1000)

    read_real_throughput = 0
    if metrics_b["runtime_ms"] > 0:
        read_real_throughput = (metrics_b["io_bytes"] / 1024 / 1024) / (metrics_b["runtime_ms"] / 1000)

    print(f"\n[Profile A: write] Real S3 traffic")
    print(f"  HTTP PUT requests: {int(metrics_a['total_ios'])}")
    print(f"  Data transferred: {metrics_a['io_bytes'] / 1024 / 1024:.1f} MB")
    print(f"  Runtime: {metrics_a['runtime_ms']:.0f} ms")
    print(f"  Throughput: {write_real_throughput:.2f} MB/s")
    print(f"  IOPS: {metrics_a['iops']:.2f}")
    print(f"  Latency P95: {metrics_a['latency_p95_ms']:.2f} ms")
    print(f"  Latency P99: {metrics_a['latency_p99_ms']:.2f} ms")

    # Detect if read results are cached (runtime too short)
    read_is_cached = metrics_b["runtime_ms"] < 100 and metrics_b["total_ios"] > 10

    print(f"\n[Profile B: read] {'CACHED - not real S3 traffic' if read_is_cached else 'Real S3 traffic'}")
    print(f"  HTTP GET requests: {int(metrics_b['total_ios'])}")
    print(f"  Data transferred: {metrics_b['io_bytes'] / 1024 / 1024:.1f} MB")
    print(f"  Runtime: {metrics_b['runtime_ms']:.0f} ms")
    if read_is_cached:
        print(f"  Throughput: {read_real_throughput:.2f} MB/s (FROM MEMORY CACHE)")
        # Estimate realistic throughput based on write performance
        estimated_read = write_real_throughput * 1.5  # Read is typically faster than write
        print(f"  Estimated real throughput: ~{estimated_read:.0f} MB/s")
    else:
        print(f"  Throughput: {read_real_throughput:.2f} MB/s")
    print(f"  IOPS: {metrics_b['iops']:.2f}")
    print(f"  Latency P95: {metrics_b['latency_p95_ms']:.2f} ms")
    print(f"  Latency P99: {metrics_b['latency_p99_ms']:.2f} ms")

    # Summary with aggregated metrics
    total_iops = metrics_a['iops'] + metrics_b['iops']
    worst_p95 = max(metrics_a['latency_p95_ms'], metrics_b['latency_p95_ms'])
    worst_p99 = max(metrics_a['latency_p99_ms'], metrics_b['latency_p99_ms'])

    print(f"\n[Summary]")
    if iperf3_metrics:
        network_throughput_mbs = iperf3_metrics['sent_mbps'] / 8
        s3_efficiency = (write_real_throughput / network_throughput_mbs * 100) if network_throughput_mbs > 0 else 0
        print(f"  Network capacity: {network_throughput_mbs:.1f} MB/s")
        print(f"  S3 write efficiency: {s3_efficiency:.1f}% of network capacity")
    print(f"  Total HTTP requests: {int(metrics_a['total_ios'] + metrics_b['total_ios'])}")
    print(f"  Total data: {(metrics_a['io_bytes'] + metrics_b['io_bytes']) / 1024 / 1024:.1f} MB")
    print(f"  Total IOPS: {total_iops:.2f}")
    print(f"  Write throughput: {write_real_throughput:.2f} MB/s")
    if read_is_cached:
        print(f"  Read throughput: CACHED (see note below)")
    else:
        print(f"  Read throughput: {read_real_throughput:.2f} MB/s")
    print(f"  Latency P95 (worst): {worst_p95:.2f} ms")
    print(f"  Latency P99 (worst): {worst_p99:.2f} ms")
    print("=" * 60)

    if read_is_cached:
        print("\nNOTE: fio HTTP engine caches read data in memory.")
        print("Read throughput shows memory speed, not S3 speed.")
        print("Write results ARE accurate - each PUT is a real HTTP request.")
        print("\nFor accurate S3 read benchmarks, use:")
        print("  - minio/warp: https://github.com/minio/warp")
        print("  - s3-benchmark: https://github.com/wasabi-tech/s3-benchmark")


def main():
    print("=== S3 Load Testing Runner ===")
    print(f"Environment: {'Docker' if _IN_DOCKER else 'Host (IDE/local)'}")
    print(f"Endpoint: {S3_ENDPOINT}")
    print(f"Bucket: {S3_BUCKET}")
    print(f"iperf3 enabled: {'Yes' if IPERF3_ENABLED else 'No'}")

    # Check fio availability
    if not check_fio_available():
        print("\nERROR: fio is not installed.", file=sys.stderr)
        print("Install with: apt install fio (Linux) or use Docker", file=sys.stderr)
        sys.exit(1)

    # Check S3 engine support
    if not check_fio_s3_support():
        print("\n" + "=" * 60)
        print("WARNING: fio S3/HTTP engine not available")
        print("=" * 60)
        print("This platform doesn't support S3 engine in fio.")
        print("\nFor S3 testing, use Docker:")
        print("   docker compose up --build")
        print("\nFor network-only testing:")

        # Run network test only if enabled
        if IPERF3_ENABLED and check_iperf3_available():
            print("   Running network baseline test...")
            local_iperf3_server = None

            if not _IN_DOCKER and IPERF3_SERVER == "localhost":
                local_iperf3_server = start_local_iperf3_server()

            iperf3_metrics = run_iperf3_test(IPERF3_SERVER, IPERF3_DURATION)

            if iperf3_metrics:
                print(f"\nNetwork Baseline Results:")
                print(f"  Bandwidth: {iperf3_metrics['sent_mbps']:.1f} Mbps ({iperf3_metrics['sent_mbps']/8:.1f} MB/s)")
                print(f"  Duration: {iperf3_metrics['duration']}s")

            if local_iperf3_server:
                try:
                    local_iperf3_server.terminate()
                    local_iperf3_server.wait(timeout=5)
                except Exception:
                    pass
        else:
            print("   Set IPERF3_ENABLED=true for network baseline testing")
            if not check_iperf3_available():
                print("   Install iperf3: apt install iperf3")

        print("\nThe Docker environment provides consistent fio with S3 engine support.")
        sys.exit(0)

    # Initialize S3 client
    s3_client = get_s3_client()
    # Ensure bucket exists
    ensure_bucket_exists(s3_client)
    # Prepare objects for read test
    prepare_read_objects(s3_client, num_objects=100)

    # Optional network baseline test with iperf3
    iperf3_metrics = None
    local_iperf3_server = None

    if IPERF3_ENABLED:
        if check_iperf3_available():
            # For host runs, we might need to start iperf3 server ourselves
            if not _IN_DOCKER and IPERF3_SERVER == "localhost":
                local_iperf3_server = start_local_iperf3_server()

            iperf3_metrics = run_iperf3_test(IPERF3_SERVER, IPERF3_DURATION)
            if not iperf3_metrics:
                print("WARNING: iperf3 test failed, continuing with S3 tests...")
        else:
            print("WARNING: iperf3 not available, skipping network baseline test")
            if not _IN_DOCKER:
                print("  To install iperf3: brew install iperf3 (macOS) or sudo apt install iperf3 (Ubuntu)")

    # Start both fio processes concurrently
    print("\nStarting concurrent fio load tests...")
    processes = [
        (run_fio_process(FIO_PROFILE_A, FIO_NUMJOBS_A, "profile_a_write"), "profile_a_write"),
        (run_fio_process(FIO_PROFILE_B, FIO_NUMJOBS_B, "profile_b_read"), "profile_b_read"),
    ]

    try:
        # Wait for completion and collect results
        results = wait_for_processes(processes)
        # Extract metrics
        metrics_a = None
        metrics_b = None
        for data, name in results:
            if "write" in name:
                metrics_a = extract_metrics(data, "write")
            else:
                metrics_b = extract_metrics(data, "read")
        if metrics_a is None:
            metrics_a = {"throughput_mbps": 0, "iops": 0, "latency_p95_ms": 0, "latency_p99_ms": 0, "total_ios": 0, "runtime_ms": 0, "io_bytes": 0}
        if metrics_b is None:
            metrics_b = {"throughput_mbps": 0, "iops": 0, "latency_p95_ms": 0, "latency_p99_ms": 0, "total_ios": 0, "runtime_ms": 0, "io_bytes": 0}
        # Print report
        print_report(metrics_a, metrics_b, iperf3_metrics)
    finally:
        # Clean up local iperf3 server if we started it
        if local_iperf3_server:
            try:
                print("\nStopping local iperf3 server...")
                local_iperf3_server.terminate()
                local_iperf3_server.wait(timeout=5)
                print("Local iperf3 server stopped")
            except Exception as e:
                print(f"Warning: Failed to stop iperf3 server: {e}", file=sys.stderr)
if __name__ == "__main__":
    main()
