# Argus — top-level developer commands.
#
# Quickstart:
#   make demo     # one-command demo (no API key required)
#   make stop     # tear it all down
#
# Day-to-day:
#   make up       # start full stack with your own .env
#   make logs     # tail backend + worker logs
#   make seed     # re-seed demo engagements into a running stack
#   make test     # run backend tests
#   make smoke    # smoke-check Redis, API, worker
#   make clean    # tear down + remove volumes

COMPOSE      = docker compose
DEMO_COMPOSE = docker compose -f docker-compose.yml -f docker-compose.demo.yml

.PHONY: demo up stop down clean logs seed test smoke help

help:
	@echo "Argus targets:"
	@echo "  make demo    - boot the stack with seeded demo engagements (no API key needed)"
	@echo "  make up      - boot full stack (requires OPENAI_API_KEY in .env)"
	@echo "  make stop    - stop containers"
	@echo "  make clean   - stop + remove volumes (DELETES Postgres data)"
	@echo "  make logs    - tail backend + worker logs"
	@echo "  make seed    - re-run the demo seeder against a running stack"
	@echo "  make test    - run backend pytest suite"
	@echo "  make smoke   - smoke-check Redis, API, worker"

demo:
	@echo ">>> Argus demo — booting with seeded engagements (no API key required)"
	$(DEMO_COMPOSE) up --build -d
	@echo ">>> Waiting for backend + db to come up..."
	@sleep 6
	@echo ">>> Demo running. Open http://localhost:3000"
	@echo "    Three seeded engagements should be visible on the homepage."
	@echo "    Tail logs:    make logs"
	@echo "    Stop:         make stop"

up:
	$(COMPOSE) up --build -d
	@echo ">>> Argus running. Open http://localhost:3000"

stop:
	$(COMPOSE) down

down: stop

clean:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f backend worker

seed:
	$(COMPOSE) exec backend python scripts/seed_demo.py

test:
	$(COMPOSE) exec backend pytest tests -q

smoke:
	bash tools/smoke_check.sh
