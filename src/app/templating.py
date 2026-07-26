"""Jinja environment and filesystem-backed design-token integration."""

import re
from pathlib import Path

from fastapi.templating import Jinja2Templates

from .schemas import MAX_SHOUT_LENGTH, MIN_SHOUT_LENGTH

PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"
TEMPLATES_DIR = PACKAGE_DIR / "templates"


def theme_css_pair(token: str) -> dict[str, str]:
    """Read a design token's light and dark colors from ``theme.css``."""
    css = (STATIC_DIR / "css" / "theme.css").read_text(encoding="utf-8")
    hex_color = r"#[0-9a-fA-F]{6}"
    match = re.search(
        rf"--{token}:\s*light-dark\(({hex_color}),\s*({hex_color})\)", css
    )
    if match is None:
        raise RuntimeError(f"--{token}: light-dark(...) not found in css/theme.css")
    return {"light": match.group(1), "dark": match.group(2)}


def create_templates() -> Jinja2Templates:
    """Create a template environment owned by one application instance."""
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    templates.env.globals.update(
        theme_color=theme_css_pair("bg"),
        min_shout_length=MIN_SHOUT_LENGTH,
        max_shout_length=MAX_SHOUT_LENGTH,
    )
    return templates
