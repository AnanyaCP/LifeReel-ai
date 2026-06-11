"""
services/ai_engine.py
─────────────────────
AI orchestration layer for text (typed) diary entries in LifeReel AI.

Pipeline
────────
  Raw text
      │
      ▼
  Step 1 – Gemini 2.5 Flash (REST, JSON mode)
      Produces: title, story, emotion, characters, scene_prompt
      │
      ▼
  Step 2 – Hugging Face Stable Diffusion XL
      Produces: image_url  (graceful null fallback on failure)
      │
      ▼
  Merged payload dict  ──►  returned to the FastAPI route

Error handling
──────────────
- NLP step raises RuntimeError on failure (bubbles up as HTTP 502).
- Image generation failure is logged but does NOT fail the request —
  image_url is set to None and processing continues.
"""

import json
import logging
import uuid
import httpx

from config.settings import settings, STATIC_ROOT

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Gemini 2.5 Flash REST endpoint
# ──────────────────────────────────────────────────────────────────────────────

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.1-flash-lite:generateContent"
)

_SYSTEM_PROMPT = """
You are LifeReel AI, a compassionate and poetic journaling companion.
Transform the person's raw diary entry into a structured JSON object.

You MUST respond with ONLY a valid JSON object – no markdown fences, no
explanatory text, no trailing comments. The object must contain exactly
these five keys:

{
  "title": "A poetic, comforting 3-5 word title that captures the soul of the entry.",
  "story": "An elegant, comforting 3-sentence summary. Reframe the person's raw text into a beautiful, affirming story written in the third person. Each sentence must be warm and literary.",
  "emotion": "Exactly one word chosen from this fixed set: Joy, Calm, Melancholy, Productive, Anxious. Choose the emotion that most truthfully represents the overall tone.",
  "characters": ["Array of names/relationships of people or characters mentioned in the entry. Empty array if none."],
  "scene_prompt": "A vivid, artistic scene description optimised for Stable Diffusion XL. Evoke the dominant emotion and core memory. Specify soft golden or ambient lighting, a comforting painterly atmosphere. ABSOLUTELY NO text, letters, words, or typography of any kind."
}

Rules:
- Return ONLY the JSON object.
- Every key must be present.
- emotion must be one of: Joy, Calm, Melancholy, Productive, Anxious.
- scene_prompt must explicitly avoid text/letters in the scene.
""".strip()

# ──────────────────────────────────────────────────────────────────────────────
# Public orchestration function
# ──────────────────────────────────────────────────────────────────────────────

def process_voice_diary(raw_text: str) -> dict:
    """
    Full AI pipeline for typed text: NLP analysis + image generation.

    Parameters
    ----------
    raw_text:
        The unprocessed diary entry from the user.

    Returns
    -------
    dict containing: title, story, emotion, characters, scene_prompt, image_url

    Raises
    ------
    RuntimeError
        If the Gemini NLP call fails.
    """
    nlp_payload = _run_gemini_nlp(raw_text)
    image_url = _run_hf_image_generation(nlp_payload["scene_prompt"], nlp_payload["emotion"])

    result = {
        **nlp_payload,
        "transcript": raw_text,
        "image_url": image_url,
    }

    logger.info(
        "AI pipeline (text) completed successfully.",
        extra={
            "title": result.get("title"),
            "emotion": result.get("emotion"),
            "image_url": image_url,
        },
    )

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 – Gemini 2.5 Flash NLP Analysis (direct HTTP REST)
# ──────────────────────────────────────────────────────────────────────────────

def _run_gemini_nlp(raw_text: str) -> dict:
    """
    Send raw_text to Gemini 2.5 Flash via REST and parse the structured JSON.
    """
    logger.info(
        "Step 1 – Sending entry to Gemini 2.5 Flash for NLP analysis.",
        extra={"raw_text_length": len(raw_text)},
    )

    request_body = {
        "contents": [
            {
                "parts": [
                    {"text": _SYSTEM_PROMPT + "\n\nDiary entry:\n" + raw_text}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.75,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
        },
    }

    try:
        response = httpx.post(
            _GEMINI_URL,
            params={"key": settings.GEMINI_API_KEY},
            json=request_body,
            timeout=45.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Gemini API call failed.",
            extra={"status_code": exc.response.status_code, "body": exc.response.text},
        )
        raise RuntimeError(
            f"NLP analysis failed – Gemini returned HTTP {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error calling Gemini API.", extra={"error": str(exc)})
        raise RuntimeError(f"NLP analysis failed – request error: {exc}") from exc

    # Parse the response
    try:
        resp_json = response.json()
        raw_content = resp_json["candidates"][0]["content"]["parts"][0]["text"]
        # Strip markdown fences if present
        raw_content = raw_content.strip()
        if raw_content.startswith("```"):
            raw_content = raw_content.split("```")[1]
            if raw_content.startswith("json"):
                raw_content = raw_content[4:]
        parsed: dict = json.loads(raw_content.strip())
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        logger.error(
            "Failed to parse Gemini JSON response.",
            extra={"raw_response": response.text[:500], "error": str(exc)},
        )
        raise RuntimeError("NLP analysis failed – model returned malformed JSON.") from exc

    # Validate required keys
    required_keys = {"title", "story", "emotion", "characters", "scene_prompt"}
    missing = required_keys - parsed.keys()
    if missing:
        logger.error(
            "Gemini response is missing required keys.",
            extra={"missing_keys": list(missing), "parsed": parsed},
        )
        raise RuntimeError(f"NLP analysis failed – model response missing keys: {missing}")

    # Validate/normalise emotion
    valid_emotions = {"Joy", "Calm", "Melancholy", "Productive", "Anxious"}
    if parsed["emotion"] not in valid_emotions:
        logger.warning(
            "emotion value not in allowed set; defaulting to 'Calm'.",
            extra={"received": parsed["emotion"]},
        )
        parsed["emotion"] = "Calm"

    # Ensure characters is a list
    if not isinstance(parsed.get("characters"), list):
        parsed["characters"] = []

    logger.info(
        "Step 1 complete – Gemini NLP analysis successful.",
        extra={"title": parsed.get("title"), "emotion": parsed.get("emotion")},
    )

    return parsed


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 – Hugging Face Stable Diffusion XL Image Generation (graceful fallback)
# ──────────────────────────────────────────────────────────────────────────────

def _run_hf_image_generation(scene_prompt: str, emotion: str = "Calm") -> str | None:
    """
    Generate an image via Hugging Face Inference API (SDXL) and save locally.
    Returns the relative static URL on success, or a curated Unsplash fallback URL if generation fails.
    """
    safety_suffix = (
        " No text, letters, words, numbers, watermarks, or typography of any "
        "kind must appear anywhere in the image."
    )
    final_prompt = scene_prompt + safety_suffix

    logger.info(
        "Step 2 – Sending image prompt to Hugging Face Inference API.",
        extra={"prompt_length": len(final_prompt)},
    )

    API_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {settings.HF_TOKEN}"}
    payload = {"inputs": final_prompt}

    # Curated premium fallback images matching journal entry emotions
    fallback_images = {
        "Joy": "https://images.unsplash.com/photo-1506126613408-eca07ce68773?auto=format&fit=crop&w=800&q=80",
        "Calm": "https://images.unsplash.com/photo-1473081556163-2a17de81fc97?auto=format&fit=crop&w=800&q=80",
        "Melancholy": "https://images.unsplash.com/photo-1437419764061-2473afe69fc2?auto=format&fit=crop&w=800&q=80",
        "Productive": "https://images.unsplash.com/photo-1497032628192-86f99bcd76bc?auto=format&fit=crop&w=800&q=80",
        "Anxious": "https://images.unsplash.com/photo-1508247967583-7d982ea00926?auto=format&fit=crop&w=800&q=80"
    }
    fallback_url = fallback_images.get(emotion, fallback_images["Calm"])

    try:
        response = httpx.post(
            API_URL,
            headers=headers,
            json=payload,
            timeout=90.0,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "HF image generation failed – using premium Unsplash fallback.",
            extra={"error": str(exc)},
        )
        return fallback_url

    # Save image locally
    filename = f"{uuid.uuid4()}.png"
    dest_path = STATIC_ROOT / "images" / filename

    try:
        with open(dest_path, "wb") as f:
            f.write(response.content)
        logger.info(
            "Step 2 complete – image saved locally.",
            extra={"dest_path": str(dest_path)},
        )
    except Exception as exc:
        logger.warning(
            "Failed to write generated image to disk – using premium Unsplash fallback.",
            extra={"error": str(exc)},
        )
        return fallback_url

    return f"/static/images/{filename}"
