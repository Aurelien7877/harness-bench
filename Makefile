.PHONY: setup setup-python test check

setup-python:
	UV_CACHE_DIR="$(CURDIR)/.cache/uv" uv venv --allow-existing --python 3.13 .venv
	UV_CACHE_DIR="$(CURDIR)/.cache/uv" uv pip sync --python .venv/bin/python requirements.lock

setup: setup-python
	docker build -t harness-bench-base:1 docker
	./bench validate

test:
	.venv/bin/python -m pytest -q

check: test
	.venv/bin/python bench.py validate
	.venv/bin/python scripts/check_publication.py
