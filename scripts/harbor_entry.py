"""Run unmodified Harbor with its cache paths scoped to this benchmark folder."""
from pathlib import Path
import harbor.constants as constants

root = Path(__file__).resolve().parents[1]
constants.CACHE_DIR = root / '.cache/harbor'
constants.TASK_CACHE_DIR = constants.CACHE_DIR / 'tasks'
constants.PACKAGE_CACHE_DIR = constants.TASK_CACHE_DIR / 'packages'
constants.DATASET_CACHE_DIR = constants.CACHE_DIR / 'datasets'
constants.NOTIFICATIONS_PATH = constants.CACHE_DIR / 'notifications.json'

from harbor.cli.main import app

if __name__ == '__main__':
    app()
