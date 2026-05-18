from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
CONFIG_DIR = SRC_DIR / "config"
OUTPUT_DIR = PROJECT_ROOT / "output"

L0_CONFIG_PATH = CONFIG_DIR / "l0_config.yaml"
L1_CONFIG_PATH = CONFIG_DIR / "l1_config.yaml"

CURRENT_MANIFEST_PATH = OUTPUT_DIR / "current_manifest.json"
