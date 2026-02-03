.PHONY: minio run loadgen stop clean logs help

# NOTE: Using --no-cache for all builds to rebuild from scratch every time.
# This is useful for learning/debugging. Remove --no-cache for faster builds in production.

# Default target
help:
	@echo "Available commands:"
	@echo "  make minio       - Start only MinIO container (for local IDE development)"
	@echo "  make run         - Start MinIO and loadgen, show results in terminal"
	@echo "  make loadgen     - Start only loadgen container (requires MinIO running)"
	@echo "  make loadgen-net - Start loadgen with iperf3 network baseline test"
	@echo "  make stop        - Stop all containers"
	@echo "  make clean       - Stop and remove all containers, volumes"
	@echo "  make logs        - Show logs from all containers"

# 1. Start only MinIO container (for running runner.py from IDE)
minio:
	@echo "Starting MinIO container..."
	docker compose up -d minio
	@echo ""
	@echo "MinIO is running:"
	@echo "  S3 API:    http://localhost:9000"
	@echo "  Console:   http://localhost:9001"
	@echo "  Credentials: minioadmin / minioadmin"
	@echo ""
	@echo "You can now run runner.py from your IDE"

# 2. Start both MinIO and loadgen, show results in terminal (no cache)
run:
	@echo "Starting MinIO and loadgen (building without cache)..."
	docker compose build --no-cache loadgen
	docker compose up

# 3. Start only loadgen container (MinIO must be running, no cache)
loadgen:
	@echo "Starting loadgen container (building without cache)..."
	@docker compose ps minio --status running > /dev/null 2>&1 || (echo "ERROR: MinIO is not running. Run 'make minio' first." && exit 1)
	docker compose build --no-cache loadgen
	docker compose up loadgen

# 4. Start loadgen with iperf3 network baseline test enabled
loadgen-net:
	@echo "Starting loadgen with iperf3 network baseline test (building without cache)..."
	@docker compose ps minio --status running > /dev/null 2>&1 || (echo "ERROR: MinIO is not running. Run 'make minio' first." && exit 1)
	docker compose build --no-cache loadgen
	@echo "Starting iperf3 server..."
	docker compose up -d iperf3-server
	@echo "Running loadgen with network test..."
	IPERF3_ENABLED=true docker compose run --rm loadgen
	@echo "Stopping iperf3 server..."
	docker compose stop iperf3-server

# Stop all containers
stop:
	@echo "Stopping all containers..."
	docker compose stop

# Stop and remove all containers, volumes
clean:
	@echo "Stopping and removing all containers and volumes..."
	docker compose down -v

# Show logs
logs:
	docker compose logs -f

