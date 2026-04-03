.PHONY: lint test build publish-pypi publish-npm docs bench clean install dev

install:
	pip install -e ".[dev]"

dev:
	pip install -e ".[dev]"
	cd relay-js && npm install

lint:
	ruff check relay/ tests/ benchmarks/
	mypy relay/
	black --check relay/ tests/ benchmarks/

format:
	black relay/ tests/ benchmarks/
	ruff check --fix relay/ tests/ benchmarks/

test:
	pytest tests/ --cov=relay --cov-report=term-missing --cov-fail-under=70

test-fast:
	pytest tests/ -x -q

build:
	python -m build
	cd relay-js && npm run build

publish-pypi:
	twine upload dist/*

publish-npm:
	cd relay-js && npm publish

docs:
	mkdocs build

docs-serve:
	mkdocs serve

bench:
	python benchmarks/bench_vs_json.py > benchmarks/results/latest.json
	@echo "Benchmark results written to benchmarks/results/latest.json"

bench-full:
	python benchmarks/bench_encode.py
	python benchmarks/bench_decode.py
	python benchmarks/bench_vs_json.py
	python benchmarks/bench_vs_msgpack.py

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	cd relay-js && rm -rf dist/ node_modules/ 2>/dev/null || true
