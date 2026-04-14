.PHONY: help install start stop restart logs wipe status seed update test

# Cross-platform commands
ifeq ($(OS),Windows_NT)
    COPY_CMD = copy
    TOUCH_CMD = type nul >
else
    COPY_CMD = cp
    TOUCH_CMD = touch
endif

# Default target
.DEFAULT_GOAL := help

help:
	@echo "MTS AI Workspace — Project Management"
	@echo ""
	@echo "Available commands:"
	@echo "  make install  - Initial setup (checks .env) and start the project"
	@echo "  make start    - Start all services in the background"
	@echo "  make stop     - Gracefully stop all services"
	@echo "  make restart  - Restart services"
	@echo "  make status   - Check the status of all containers"
	@echo "  make logs     - View logs in real time"
	@echo "  make seed     - Rebuild and restart seed (update tools/functions)"
	@echo "  make update   - Update code (seed + open-webui) without rebuilding the rest"
	@echo "  make test     - Run smoke tests (check all components)"
	@echo "  make wipe     - WARNING: Remove all containers and clear all databases (Volumes)"

# Check .env at make-parse time using $(wildcard), no shell needed
install:
ifeq ($(wildcard .env),)
ifeq ($(wildcard .env.example),)
	@echo "[!] Warning: .env.example not found. Creating empty .env..."
	@$(TOUCH_CMD) .env
else
	@echo "[*] Creating .env from .env.example..."
	@$(COPY_CMD) .env.example .env
	@echo "[!] IMPORTANT: Open .env and fill in MWS_API_KEY!"
endif
else
	@echo "[*] .env file already exists. Skipping..."
endif
	@echo "[*] Building and starting services..."
	docker compose up -d --build --remove-orphans

start:
	@echo "[*] Rebuilding seed and open-webui (updating tools/functions + JS)..."
	docker compose up -d --build --no-deps seed open-webui
	@echo "[*] Starting remaining services..."
	docker compose up -d --remove-orphans

stop:
	@echo "[*] Stopping services..."
	docker compose down --remove-orphans

restart: stop start

status:
	@echo "[*] Services status:"
	@docker compose ps
	@echo ""
	@echo "[*] Resource usage:"
ifeq ($(OS),Windows_NT)
	@docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>NUL || ver >NUL
else
	@docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null || true
endif

logs:
	docker compose logs -f

seed:
	@echo "[*] Rebuilding and restarting seed (updating tools/functions)..."
	docker compose up -d --build --no-deps seed

update:
	@echo "[*] Updating seed + open-webui..."
	docker compose up -d --build --no-deps seed open-webui

test:
	@echo "[*] Running smoke tests..."
ifeq ($(OS),Windows_NT)
	python scripts/smoke_test.py
else
	python3 scripts/smoke_test.py
endif

wipe:
	@echo "[!] Removing all services and stored databases..."
	docker compose down -v --remove-orphans
	@echo "[*] Done. Environment has been fully reset."
