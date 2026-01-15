SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

.PHONY: help lint lint-ruff lint-pyright ruff-fix fmt test reqs dev-reqs \
        build up up-profile debug down restart logs status ps \
        profiles active create use switch edit \
        port doctor smoke smoke-chat smoke-llm load

PYTHON ?= python
IMAGE ?= llm-proxy:dev
CLI ?= ./cli/llm-proxy

# если указан PROFILE=..., используем его
# иначе берём активный из llm-proxy (команда должна просто печатать имя профиля)
PROFILE ?= $(shell ./cli/llm-proxy active 2>/dev/null || true)
# fallback если active пустой
ifeq ($(strip $(PROFILE)),)
PROFILE := default
endif

PORT ?= 8002

# Detect profile dir (XDG)
PROFILE_DIR := $(shell if [ -n "$$XDG_CONFIG_HOME" ]; then echo "$$XDG_CONFIG_HOME/llm-proxy/profiles"; else echo "$$HOME/.config/llm-proxy/profiles"; fi)
COMPOSE_ENV := $(PROFILE_DIR)/$(PROFILE).env
RUNTIME_ENV := $(PROFILE_DIR)/$(PROFILE).llm.env

# Read LLM_PORT from profile compose env if present; fallback to PORT var.
PORT_FROM_PROFILE := $(shell if [ -f "$(COMPOSE_ENV)" ]; then grep -E '^LLM_PORT=' "$(COMPOSE_ENV)" | tail -n1 | cut -d= -f2; fi)
EFFECTIVE_PORT := $(if $(PORT_FROM_PROFILE),$(PORT_FROM_PROFILE),$(PORT))

BASE_URL ?= http://localhost:$(EFFECTIVE_PORT)

# Endpoints (defaults)
CHAT_ENDPOINT ?= /v1/chat/completions
LLM_ENDPOINT  ?= /llm

# Pretty output (colors)
RESET := \033[0m
BOLD  := \033[1m
DIM   := \033[2m
RED   := \033[31m
GRN   := \033[32m
YEL   := \033[33m
BLU   := \033[34m
CYN   := \033[36m

define HR
	@printf "$(DIM)─────────────────────────────────────────────────────────────────────────────$(RESET)\n"
endef

define TITLE
	$(call HR)
	@printf "$(BOLD)%s$(RESET)\n" '$(1)'
endef

define KV
	@printf "  %-13s %s\n" '$(1)' '$(2)'
endef

define INFO
	@printf "$(CYN)ℹ$(RESET) %s\n" '$(1)'
endef

define OK
	@printf "$(GRN)✔$(RESET) %s\n" '$(1)'
endef

define WARN
	@printf "$(YEL)⚠$(RESET) %s\n" '$(1)'
endef

define ERR
	@printf "$(RED)✖$(RESET) %s\n" '$(1)'
endef


help:
	$(call TITLE,Команды Makefile)
	@printf "$(BOLD)Dev$(RESET)\n"
	@printf "  make reqs | dev-reqs\n"
	@printf "  make lint | fmt | test\n"
	@printf "  make build | rebulid\n"
	@printf "\n$(BOLD)Команды начальной установки$(RESET)\n"
	@printf "  make cli-install | cli-uninstall | cli-reinstall\n"
	@printf "  make cli-where\n"	
	@printf "\n$(BOLD)Runtime (через CLI профили)$(RESET)\n"
	@printf "  make up PROFILE=default\n"
	@printf "  make down PROFILE=default\n"
	@printf "  make port PROFILE=default PORT=8002\n"
	@printf "  make doctor | status | ps | logs\n"
	@printf "\n$(BOLD)Проверки$(RESET)\n"
	@printf "  make smoke\n"
	@printf "  CONCURRENCY=30 REQUESTS=300 make load\n"
	$(call HR)


# -----------------------
# Python quality targets
# -----------------------
lint: lint-ruff lint-pyright

lint-ruff:
	$(PYTHON) -m ruff check src tests

lint-pyright:
	pyright

ruff-fix:
	$(PYTHON) -m ruff check src tests --fix

fmt:
	$(PYTHON) -m ruff format src tests

test:
	pytest -q

PIP_COMPILE ?= pip-compile

requirements.txt: requirements.in
	pip install -q pip-tools
	$(PIP_COMPILE) -o $@ $<

requirements-dev.txt: requirements-dev.in
	pip install -q pip-tools
	$(PIP_COMPILE) -o $@ $<

compile-reqs: requirements.txt
compile-dev-reqs: requirements-dev.txt

reqs: requirements.txt
	pip install -r requirements.txt

dev-reqs: requirements-dev.txt
	pip install -r requirements-dev.txt

# -----------------------
# Docker image
# -----------------------
build:
	$(call TITLE,Сборка Docker image)
	$(call KV,Image:, $(IMAGE))
	$(call HR)
	docker build -t $(IMAGE) .
	$(call OK,Готово)

rebuild:
	$(call TITLE,Сборка Docker image)
	$(call KV,Image:, $(IMAGE))
	$(call HR)
	docker build --no-cache -t $(IMAGE) .
	$(call OK,Готово)

# ---------------------------
# CLI install settings
# ---------------------------
PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin

CLI_SRC := ./cli/llm-proxy
CLI_BIN := $(BINDIR)/llm-proxy
COMPLETION_BASH_DIR ?= $(HOME)/.bash_completion.d
COMPLETION_ZSH_DIR  ?= $(HOME)/.zsh/completions
COMPLETION_FISH_DIR ?= $(HOME)/.config/fish/completions

.PHONY: cli-install cli-uninstall cli-reinstall cli-where install-completion completion

## Install CLI into ~/.local/bin/llm-proxy
cli-install:
	./cli/llm-proxy install --project-dir $(PWD)
	@echo "PATH check: run 'make cli-where'"

cli-reinstall:
	./cli/llm-proxy reinstall --project-dir $(PWD)
	@echo "PATH check: run 'make cli-where'"

## Remove installed CLI binary
cli-uninstall:
	@rm -f "$(CLI_BIN)"
	@echo "Removed: $(CLI_BIN)"

## Reinstall CLI (uninstall + install)
cli-reinstall: cli-uninstall cli-install

## Print where llm-proxy resolves from, and warn if not in PATH
cli-where:
	@echo "Expected: $(CLI_BIN)"
	@command -v llm-proxy >/dev/null 2>&1 && echo "which llm-proxy: $$(command -v llm-proxy)" || echo "which llm-proxy: NOT FOUND"
	@echo "PATH: $$PATH"
	@if ! echo "$$PATH" | tr ':' '\n' | grep -Fxq "$(BINDIR)"; then \
		echo "WARNING: $(BINDIR) is not in PATH. Add this to your shell rc:"; \
		echo '  export PATH="$(BINDIR):$$PATH"'; \
	fi

## Install shell completions (bash|zsh|fish)
completion install-completion:
	@mkdir -p "$(COMPLETION_BASH_DIR)" "$(COMPLETION_ZSH_DIR)" "$(COMPLETION_FISH_DIR)"
	@$(CLI_SRC) completion bash > "$(COMPLETION_BASH_DIR)/llm-proxy"
	@$(CLI_SRC) completion zsh  > "$(COMPLETION_ZSH_DIR)/_llm-proxy"
	@$(CLI_SRC) completion fish > "$(COMPLETION_FISH_DIR)/llm-proxy.fish"
	@echo "Bash completion: $(COMPLETION_BASH_DIR)/llm-proxy"
	@echo "  To enable now: source $(COMPLETION_BASH_DIR)/llm-proxy"
	@echo "  If directory not in bash_completion path, add to ~/.bashrc:"
	@echo "    if [ -d \"$(COMPLETION_BASH_DIR)\" ]; then . \"$(COMPLETION_BASH_DIR)/llm-proxy\"; fi"
	@echo "Zsh completion:  $(COMPLETION_ZSH_DIR)/_llm-proxy (ensure this dir is in fpath; e.g. fpath+=($(COMPLETION_ZSH_DIR)))"
	@echo "  To enable now: fpath=($(COMPLETION_ZSH_DIR) $$fpath); autoload -Uz compinit; compinit"
	@echo "  Add permanently to ~/.zshrc:"
	@echo "    fpath=($(COMPLETION_ZSH_DIR) \$$fpath)"
	@echo "    autoload -Uz compinit"
	@echo "    compinit"
	@echo "Fish completion: $(COMPLETION_FISH_DIR)/llm-proxy.fish"
	@echo "Restart your shell or source the completion file for it to take effect."

# -----------------------
# CLI-driven lifecycle
# -----------------------
profiles:
	$(call TITLE,Профили)
	$(CLI) list || true

active:
	$(call TITLE,Активный профиль)
	$(CLI) active || true

create:
	@mkdir -p "$(PROFILE_DIR)"
	@if [ -f "$(COMPOSE_ENV)" ] || [ -f "$(RUNTIME_ENV)" ]; then \
		printf "$(DIM)Профиль уже существует: %s (%s)$(RESET)\n" "$(PROFILE)" "$(PROFILE_DIR)"; \
	else \
		$(CLI) create "$(PROFILE)"; \
	fi

use:
	$(CLI) use "$(PROFILE)"

switch: create use

edit:
	$(call TITLE,Редактирование профиля)
	$(call KV,Profile:, $(PROFILE))
	$(call KV,Runtime env:, $(RUNTIME_ENV))
	$(call HR)
	$(CLI) edit "$(PROFILE)"

port: create
	$(call TITLE,Настройка порта профиля)
	$(call KV,Profile:, $(PROFILE))
	$(call KV,LLM_PORT:, $(PORT))
	$(call HR)
	@if [ -f "$(COMPOSE_ENV)" ]; then \
		if grep -qE '^LLM_PORT=' "$(COMPOSE_ENV)"; then \
			sed -i.bak -E 's/^LLM_PORT=.*/LLM_PORT=$(PORT)/' "$(COMPOSE_ENV)"; \
		else \
			printf "\nLLM_PORT=$(PORT)\n" >> "$(COMPOSE_ENV)"; \
		fi; \
		rm -f "$(COMPOSE_ENV).bak"; \
	fi
	@if [ -f "$(RUNTIME_ENV)" ]; then \
		if grep -qE '^LLM_PORT=' "$(RUNTIME_ENV)"; then \
			sed -i.bak -E 's/^LLM_PORT=.*/LLM_PORT=$(PORT)/' "$(RUNTIME_ENV)"; \
		else \
			printf "\nLLM_PORT=$(PORT)\n" >> "$(RUNTIME_ENV)"; \
		fi; \
		rm -f "$(RUNTIME_ENV).bak"; \
	fi
	$(call OK,Готово)
	@printf "$(DIM)compose env: %s$(RESET)\n" "$(COMPOSE_ENV)"
	@printf "$(DIM)runtime env: %s$(RESET)\n" "$(RUNTIME_ENV)"

up:
	$(call TITLE,Запуск сервиса)
	$(call KV,Profile:, $(PROFILE))
	$(call KV,Compose env:, $(COMPOSE_ENV))
	$(call KV,Runtime env:, $(RUNTIME_ENV))
	$(call KV,Port:, $(EFFECTIVE_PORT))
	$(call KV,BASE_URL:, $(BASE_URL))
	$(call HR)
	$(CLI) up "$(PROFILE)"
	$(call OK,Запущено)

up-profile: use
	$(call TITLE,Запуск сервиса)
	$(call KV,Profile:, $(PROFILE))
	$(call KV,Compose env:, $(COMPOSE_ENV))
	$(call KV,Runtime env:, $(RUNTIME_ENV))
	$(call KV,Port:, $(EFFECTIVE_PORT))
	$(call KV,BASE_URL:, $(BASE_URL))
	$(call HR)
	$(CLI) up "$(PROFILE)"
	$(call OK,Запущено)

debug:
	$(call TITLE,Debug (debugpy + attach))
	$(call KV,Profile:, $(PROFILE))
	$(call HR)
	$(CLI) debug "$(PROFILE)"

down:
	$(call TITLE,Остановка сервиса)
	$(call KV,Profile:, $(PROFILE))
	$(call HR)
	@sh -c '$(CLI) down "$(PROFILE)" || $(CLI) down || true'
	$(call OK,Остановлено (best-effort))

restart: down up

logs:
	$(call TITLE,Логи)
	$(call KV,Profile:, $(PROFILE))
	$(call HR)
	$(CLI) logs "$(PROFILE)" || true

ps:
	$(call TITLE,Контейнеры Docker)
	docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}"

status:
	$(call TITLE,Статус профиля)
	$(call KV,Profile:, $(PROFILE))
	$(call KV,Profiles dir:, $(PROFILE_DIR))
	$(call KV,Compose env:, $(COMPOSE_ENV))
	$(call KV,Runtime env:, $(RUNTIME_ENV))
	$(call KV,Port:, $(EFFECTIVE_PORT))
	$(call KV,BASE_URL:, $(BASE_URL))
	$(call HR)
	$(CLI) active || true
	$(CLI) list || true
	$(call HR)
	$(CLI) status "$(PROFILE)" || true
	$(call HR)
	docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}" || true

doctor:
	$(call TITLE,Doctor: проверка окружения)
	$(call KV,Profile:, $(PROFILE))
	$(call KV,BASE_URL:, $(BASE_URL))
	$(call KV,Port:, $(EFFECTIVE_PORT))
	$(call HR)
	$(call INFO,Кто держит порт $(EFFECTIVE_PORT):)
	@docker ps --format "{{.Names}} {{.Image}} {{.Ports}}" | grep -E "0.0.0.0:$(EFFECTIVE_PORT)->|:::$(EFFECTIVE_PORT)->" || true
	$(call HR)
	$(call INFO,Если порт занят — останови контейнер:)
	@printf "  docker stop <name>\n"
	$(call INFO,Или:)
	@printf "  make down PROFILE=$(PROFILE)\n"
	$(call HR)


# -----------------------
# Smoke tests
# -----------------------
smoke: smoke-chat smoke-llm
	$(call OK,Smoke tests: OK)

smoke-chat:
	$(call TITLE,Smoke test: Chat API)
	$(call KV,BASE_URL:, $(BASE_URL))
	$(call KV,Endpoint:, $(CHAT_ENDPOINT))
	$(call HR)
	$(call INFO,Проверяю /health...)
	@tmp="$$(mktemp)"; code="$$(curl -sS -o "$$tmp" -w "%{http_code}" "$(BASE_URL)/health" || echo 000)"; \
	if [[ "$$code" =~ ^[23][0-9][0-9]$$ ]]; then \
		printf "$(GRN)✔$(RESET) GET /health (HTTP %s)\n" "$$code"; \
	else \
		printf "$(RED)✖$(RESET) GET /health (HTTP %s)\n" "$$code"; \
		printf "$(YEL)⚠$(RESET) Ответ сервера:\n"; sed -n '1,160p' "$$tmp" || true; rm -f "$$tmp"; exit 1; \
	fi; rm -f "$$tmp"

	$(call INFO,Проверяю /metrics...)
	@tmp="$$(mktemp)"; code="$$(curl -sS -o "$$tmp" -w "%{http_code}" "$(BASE_URL)/metrics" || echo 000)"; \
	if [[ "$$code" =~ ^[23][0-9][0-9]$$ ]]; then \
		printf "$(GRN)✔$(RESET) GET /metrics (HTTP %s)\n" "$$code"; \
	else \
		printf "$(RED)✖$(RESET) GET /metrics (HTTP %s)\n" "$$code"; \
		printf "$(YEL)⚠$(RESET) Ответ сервера:\n"; sed -n '1,160p' "$$tmp" || true; rm -f "$$tmp"; exit 1; \
	fi; rm -f "$$tmp"

	$(call INFO,Проверяю POST $(CHAT_ENDPOINT)...)
	@payload="$$(mktemp)"; \
	printf '%s' '{"messages":[{"role":"user","content":"hi"}]}' >"$$payload"; \
	tmp="$$(mktemp)"; \
	code="$$(curl -sS -o "$$tmp" -w "%{http_code}" \
		-H "Content-Type: application/json" \
		--data-binary "@$$payload" \
		"$(BASE_URL)$(CHAT_ENDPOINT)" || echo 000)"; \
	rm -f "$$payload"; \
	if [[ "$$code" =~ ^[23][0-9][0-9]$$ ]]; then \
		printf "$(GRN)✔$(RESET) POST $(CHAT_ENDPOINT) (HTTP %s)\n" "$$code"; \
	else \
		printf "$(RED)✖$(RESET) POST $(CHAT_ENDPOINT) (HTTP %s)\n" "$$code"; \
		printf "$(YEL)⚠$(RESET) Ответ сервера:\n"; sed -n '1,200p' "$$tmp" || true; rm -f "$$tmp"; exit 1; \
	fi; rm -f "$$tmp"

	$(call HR)
	$(call INFO,Метрики (срез):)
	@curl -fsS "$(BASE_URL)/metrics" | egrep "llm_proxy_(requests_total|queue_overflow_total|queue_length|in_flight)" || true
	$(call OK,Smoke chat: OK)

smoke-llm:
	$(call TITLE,Smoke test: /llm endpoint)
	$(call KV,BASE_URL:, $(BASE_URL))
	$(call KV,Endpoint:, $(LLM_ENDPOINT))
	$(call HR)
	$(call INFO,Проверяю POST $(LLM_ENDPOINT)...)
	@payload="$$(mktemp)"; \
	printf '%s' '{"method":"generate","kwargs":{"messages":[{"role":"user","content":"hi"}]}}' >"$$payload"; \
	tmp="$$(mktemp)"; \
	code="$$(curl -sS -o "$$tmp" -w "%{http_code}" \
		-H "Content-Type: application/json" \
		--data-binary "@$$payload" \
		"$(BASE_URL)$(LLM_ENDPOINT)" || echo 000)"; \
	rm -f "$$payload"; \
	if [[ "$$code" =~ ^[23][0-9][0-9]$$ ]]; then \
		printf "$(GRN)✔$(RESET) POST $(LLM_ENDPOINT) (HTTP %s)\n" "$$code"; \
	else \
		printf "$(RED)✖$(RESET) POST $(LLM_ENDPOINT) (HTTP %s)\n" "$$code"; \
		printf "$(YEL)⚠$(RESET) Ответ сервера:\n"; sed -n '1,200p' "$$tmp" || true; rm -f "$$tmp"; exit 1; \
	fi; rm -f "$$tmp"
	$(call OK,Smoke llm: OK)


# -----------------------
# Load test
# -----------------------
load:
	$(call TITLE,Load test)
	$(call KV,BASE_URL:, $(BASE_URL))
	$(call KV,Endpoint:, $(CHAT_ENDPOINT))
	$(call KV,CONCURRENCY:, $${CONCURRENCY:-20})
	$(call KV,REQUESTS:, $${REQUESTS:-200})
	$(call HR)
	$(call INFO,Отправляю запросы... (статистика по HTTP-кодам ниже))
	@CONCURRENCY="$${CONCURRENCY:-20}"; REQUESTS="$${REQUESTS:-200}"; \
	payload="$$(mktemp)"; \
	printf '%s' '{"messages":[{"role":"user","content":"hi"}]}' >"$$payload"; \
	; \
	seq 1 "$$REQUESTS" | xargs -n1 -P"$$CONCURRENCY" -I{} \
	  bash -lc 'curl -sS -o /dev/null -w "%{http_code}\n" -H "Content-Type: application/json" -H "X-Request-Id: loadtest-{}" --data-binary "@'$$payload'" "$(BASE_URL)$(CHAT_ENDPOINT)" || echo 000' \
	| tee /tmp/llm_proxy_load_codes.$$$$ | sort | uniq -c; \
	rm -f "$$payload"; \
	$(call HR); \
	$(call INFO,Проверяю наличие ошибок...); \
	if grep -Eq '(^|[[:space:]])(000|4[0-9][0-9]|5[0-9][0-9])$$' /tmp/llm_proxy_load_codes.$$$$; then \
		printf "$(YEL)⚠$(RESET) В выдаче есть 4xx/5xx/000. Это не всегда плохо (например, overflow), но стоит посмотреть метрики/логи.\n"; \
	fi; \
	rm -f /tmp/llm_proxy_load_codes.$$$$; \
	$(call HR); \
	$(call INFO,Метрики (после нагрузки):); \
	curl -fsS "$(BASE_URL)/metrics" | egrep "llm_proxy_(requests_total|queue_overflow_total|queue_length|in_flight|provider_latency_seconds|queue_wait_seconds)" || true; \
	$(call OK,Load test завершён)
