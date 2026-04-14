.PHONY: help install start stop restart logs wipe status seed update test

# Настройки по умолчанию
.DEFAULT_GOAL := help

help:
	@echo "MTS AI Workspace — Управление проектом"
	@echo ""
	@echo "Доступные команды:"
	@echo "  make install  - Первоначальная настройка (проверяет .env) и запуск проекта"
	@echo "  make start    - Запустить все сервисы в фоновом режиме"
	@echo "  make stop     - Безопасно остановить все сервисы"
	@echo "  make restart  - Перезапустить сервисы"
	@echo "  make status   - Проверить состояние всех контейнеров"
	@echo "  make logs     - Посмотреть логи в реальном времени"
	@echo "  make seed     - Пересобрать и перезапустить seed (обновить tools/functions)"
	@echo "  make update   - Обновить код (seed + open-webui) без пересборки остальных"
	@echo "  make test     - 🧪 Запустить smoke-тесты (проверить все компоненты)"
	@echo "  make wipe     - ⚠️ ВНИМАНИЕ: Удалить все контейнеры и очистить все базы данных (Volumes)"

install:
	@if [ ! -f .env ]; then \
		if [ -f .env.example ]; then \
			echo "[*] Создаю .env из .env.example..."; \
			cp .env.example .env; \
			echo "[!] ВАЖНО: Откройте .env и заполните MWS_API_KEY!"; \
		else \
			echo "[!] Внимание: отсутствует файл .env.example. Создаю пустой .env..."; \
			touch .env; \
		fi \
	else \
		echo "[*] Файл .env уже существует. Пропускаю..."; \
	fi
	@echo "[*] Запускаю сборку и старт сервисов..."
	docker compose up -d --build --remove-orphans

start:
	@echo "[*] Пересборка seed и open-webui (обновление tools/functions + JS)..."
	docker compose up -d --build --no-deps seed open-webui
	@echo "[*] Запуск остальных сервисов..."
	docker compose up -d --remove-orphans

stop:
	@echo "[*] Остановка сервисов..."
	docker compose down --remove-orphans

restart: stop start

status:
	@echo "[*] Статус сервисов:"
	@docker compose ps
	@echo ""
	@echo "[*] Использование ресурсов:"
	@docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null || true

logs:
	docker compose logs -f

seed:
	@echo "[*] Пересборка и перезапуск seed (обновление tools/functions)..."
	docker compose up -d --build --no-deps seed

update:
	@echo "[*] Обновление seed + open-webui..."
	docker compose up -d --build --no-deps seed open-webui

test:
	@echo "[*] Запуск smoke-тестов..."
	python3 scripts/smoke_test.py

wipe:
	@echo "[!] Удаляю все сервисы и сохраненную базу данных..."
	docker compose down -v --remove-orphans
	@echo "[*] Готово. Окружение полностью сброшено до нуля."

