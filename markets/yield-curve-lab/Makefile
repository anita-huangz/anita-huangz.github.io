.PHONY: help install test lint check serve api web up down

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

install:  ## Editable install with the dev and predict extras
	pip install -e ".[dev,predict]"
	cd api && npm install
	cd web && npm install

test:  ## The Python engine and the BFF. The browser port lives in site/ and is
       ## tested there, against fixtures this package generates.
	pytest -q --cov --cov-report=term-missing
	cd api && npm test

lint:  ## ruff plus both TypeScript projects
	ruff check .
	cd api && npx tsc -b --noEmit
	cd web && npx tsc -b --noEmit

check: lint test  ## Lint and test

serve:  ## The Python engine alone, on :8000
	uvicorn curve_lab.service.app:app --factory --reload --port 8000

api:  ## The BFF alone, on :8080. Needs `make serve` in another shell.
	cd api && npm run dev

web:  ## The Vite dev server on :5173, proxying /api to :8080
	cd web && npm run dev

up:  ## Everything, in Docker, on http://localhost:8080
	docker compose up --build

down:
	docker compose down -v
