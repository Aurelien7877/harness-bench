.PHONY: setup setup-python test check prune

setup-python:
	UV_CACHE_DIR="$(CURDIR)/.cache/uv" uv venv --allow-existing --python 3.13 .venv
	UV_CACHE_DIR="$(CURDIR)/.cache/uv" uv pip sync --python .venv/bin/python requirements.lock
	# Notebook kernel and widgets are not in the lockfile, and sync removes them. The venv has no pip, so install them here.
	UV_CACHE_DIR="$(CURDIR)/.cache/uv" uv pip install --python .venv/bin/python 'ipykernel>=6' 'ipywidgets>=8,<9' 'matplotlib>=3.9,<4'

setup: setup-python
	.venv/bin/python -c "import bench; print(bench.build_base_image())"
	./bench validate

test:
	.venv/bin/python -m pytest -q

check: test
	.venv/bin/python bench.py validate
	.venv/bin/python scripts/check_publication.py

# Frees Docker build cache older than a week; never touches runs/ or the base image.
prune:
	docker builder prune -f --filter until=168h
