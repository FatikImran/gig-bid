.PHONY: install api web worker test lint eval eval-sim demo seed compose-up compose-down

install:
	python -m pip install -e ".[dev]"
	cd apps/web && npm ci

api:
	uvicorn apps.api.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

worker:
	python -m worker.scout

test:
	python -m pytest -q

lint:
	ruff check .
	cd apps/web && npm run build

eval:
	python -m evals.runners.run_demo_eval
	python -m evals.runners.evaluate_gigsim
	python -m evals.runners.evaluate_failure_modes
	python -m evals.runners.evaluate_negotiation

eval-sim:
	python -m evals.runners.evaluate_gigsim

demo:
	python -m evals.runners.run_demo_eval

seed:
	python -m evals.runners.prepare_kaggle_data

compose-up:
	docker compose -f infra/docker-compose.yml up --build

compose-down:
	docker compose -f infra/docker-compose.yml down
