import json
from pathlib import Path
import re


configPath = Path(__file__).resolve().with_name("config.json")


def load_bot_config() -> dict:
    config = json.loads(configPath.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"{configPath} must contain a JSON object")
    return config


def load_embed_color() -> int:
    embedColor = load_bot_config().get("embed_color")
    if not isinstance(embedColor, str) or not re.fullmatch(
        r"#[0-9a-fA-F]{6}", embedColor
    ):
        raise ValueError("config.json 'embed_color' must be a hex color like '#CC0000'")
    return int(embedColor[1:], 16)
