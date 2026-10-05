"""Load plain or base64-prefixed values from the shared .env file."""

import base64
import os
from pathlib import Path

from dotenv import dotenv_values


def load_project_env(path: Path | None = None, override: bool = False) -> None:
    if path is None or not path.exists():
        p1 = Path(__file__).resolve().parent / ".env"
        p2 = Path(__file__).resolve().parent / "env"
        path = p1 if p1.exists() else p2 if p2.exists() else path

    if path is None or not path.exists():
        return

    for key, value in dotenv_values(path).items():
        if value is None:
            continue
        if not override and key in os.environ and os.environ[key]:
            continue
        if value.startswith("base64:"):
            try:
                value = base64.b64decode(value[7:], validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError(f"Invalid base64 value for {key} in {path}") from exc
        os.environ[key] = value