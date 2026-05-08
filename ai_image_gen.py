import os
import re
import uuid
from urllib.parse import quote

import requests


_POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/"


def _normalize_prompt(prompt: str) -> str:
    if prompt is None:
        return ""
    prompt = str(prompt).strip()
    # Remove leading/trailing quotes that users might paste.
    if (prompt.startswith('"') and prompt.endswith('"')) or (prompt.startswith("'") and prompt.endswith("'")):
        prompt = prompt[1:-1].strip()
    return prompt


def build_pollinations_url(prompt: str) -> str:
    """Build the pollinations prompt URL for the given prompt."""
    prompt = _normalize_prompt(prompt)
    if not prompt:
        raise ValueError("Prompt is empty")
    # Pollinations endpoint is path-based, so URL-encode to keep spaces/symbols safe.
    return _POLLINATIONS_BASE + quote(prompt, safe="")


def download_image(prompt: str, out_path: str, timeout: float = 30.0) -> str:
    """Download an image for `prompt` and save to `out_path`.

    Returns the saved path.
    """
    url = build_pollinations_url(prompt)

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(resp.content)

    return out_path


def generate_image(prompt: str, output_dir: str = "generated_images", filename_prefix: str = "aipic") -> str:
    """Generate an image from prompt and save it to output_dir.

    Returns the full output file path.
    """
    prompt = _normalize_prompt(prompt)
    if not prompt:
        raise ValueError("Prompt is empty")

    # Try to preserve common image formats; pollinations typically returns png.
    # We'll save as .png by default.
    out_dir = output_dir
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{filename_prefix}_{uuid.uuid4().hex[:10]}.png"
    out_path = os.path.join(out_dir, fname)

    return download_image(prompt, out_path)

