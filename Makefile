.PHONY: help install start stop restart logs wipe

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
	@echo "  make logs     - Посмотреть логи в реальном времени"
	@echo "  make wipe     - ⚠️ ВНИМАНИЕ: Удалить все контейнеры и очистить все базы данных (Volumes)"

install:
	@if [ ! -f .env ]; then \
		if [ -f .env.example ]; then \
			echo "[*] Создаю .env из .env.example..."; \
			cp .env.example .env; \
		else \
			echo "[!] Внимание: отсутствует файл .env.example. Создаю пустой .env..."; \
			touch .env; \
		fi \
	else \
		echo "[*] Файл .env уже существует. Пропускаю..."; \
	fi
	@echo "[*] Запускаю сборку и старт сервисов..."
	docker compose up -d --build

start:
	@echo "[*] Запуск сервисов..."
	docker compose up -d

stop:
	@echo "[*] Остановка сервисов..."
	docker compose down

restart: stop start

logs:
	docker compose logs -f

wipe:
	@echo "[!] Удаляю все сервисы и сохраненную базу данных..."
	docker compose down -v
	@echo "[*] Готово. Окружение полностью сброшено до нуля."
