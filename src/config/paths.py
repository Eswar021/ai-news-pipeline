from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
CONFIG_DIR = SRC_DIR / "config"
OUTPUT_DIR = PROJECT_ROOT / "output"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

L0_CONFIG_PATH = CONFIG_DIR / "l0_config.yaml"
L1_CONFIG_PATH = CONFIG_DIR / "l1_config.yaml"
L3_CONFIG_PATH = CONFIG_DIR / "l3_config.yaml"
L4_CONFIG_PATH = CONFIG_DIR / "l4_config.yaml"
L5_CONFIG_PATH = CONFIG_DIR / "l5_config.yaml"

CURRENT_MANIFEST_PATH = OUTPUT_DIR / "current_manifest.json"
