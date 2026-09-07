# `make` on its own lists what's available.

SONDARO_HOST ?= you@your-vm
COMPOSE := docker compose -p sondaro -f ~/sondaro/docker-compose.yml

.PHONY: help deploy logs test build restart stop start

.DEFAULT_GOAL := help

help:  ## list available commands
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

deploy:  ## sync source to the server and rebuild
	@./deploy.sh

logs:  ## tail the running container
	@ssh $(SONDARO_HOST) '$(COMPOSE) logs -f'

restart:  ## restart the container without redeploying
	@ssh $(SONDARO_HOST) '$(COMPOSE) restart'

# restart: unless-stopped, so a stop sticks across a reboot until you start it
stop:  ## halt the container, and with it the worker and its spending
	@ssh $(SONDARO_HOST) '$(COMPOSE) stop'

start:  ## start it again after a stop
	@ssh $(SONDARO_HOST) '$(COMPOSE) start'

test:  ## run the python and component suites locally
	@python3 -m pytest -q && npm --prefix web test -- --run

build:  ## build the image locally without deploying
	@docker build -t sondaro:local .
