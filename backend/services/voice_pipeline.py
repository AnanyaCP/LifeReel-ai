"""
services/voice_pipeline.py
──────────────────────────
Full audio memory pipeline for LifeReel AI.

Pipeline
────────
  Uploaded audio file
      │
      ▼
  Step 1 – Local Whisper (base model) transcription
      │
      ▼
  Step 2 – Gemini 2.5 Flash (REST, JSON mode)
      Produces: title, story, emotion, characters, scene_prompt
      │
      ▼
  Step 3 – Hugging Face Stable Diffusion XL (graceful null fallback)
      Produces: image_url
      │
      ▼
  Step 4 – MongoDB persistence
      Returns the full document dict

Design notes
────────────
- Video and audio narration (MoviePy, gTTS) are completely removed.
- Only a single image is generated per memory.
- If image generation fails, processing continues with image_url = None.
- Whisper model is loaded lazily on first use and cached globally.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import UploadFile

from config.database import journal_entries
from config.settings import settings, STATIC_ROOT

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Whisper model – loaded lazily, cached at module level
# ──────────────────────────────────────────────────────────────────────────────

_whisper_model = None


def _get_whisper_model():
    """Load and cache the Whisper 'base' model on first use."""
    global _whisper_model
    if _whisper_model is None:
        try:
            logger.info("Loading local Whisper 'base' model …")
            import whisper
            _whisper_model = whisper.load_model("base")
            logger.info("Whisper 'base' model loaded successfully.")
        except ImportError:
            raise RuntimeError(
                "openai-whisper is not installed. "
                "Run: .venv\\Scripts\\pip install openai-whisper"
            )
    return _whisper_model


# ──────────────────────────────────────────────────────────────────────────────
# Gemini 2.5 Flash REST endpoint
# ──────────────────────────────────────────────────────────────────────────────

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.1-flash-lite:generateContent"
)

_SYSTEM_PROMPT = """
You are LifeReel AI, a compassionate and poetic journaling companion.
Transform the person's diary transcript into a structured JSON object.

You MUST respond with ONLY a valid JSON object – no markdown fences, no
explanatory text. The object must contain exactly these five keys:

{
  "title": "A poetic, comforting 3-5 word title that captures the soul of the entry.",
  "story": "An elegant, comforting 3-sentence summary. Reframe the transcript into a beautiful, affirming story written in the third person. Each sentence must be warm and literary.",
  "emotion": "Exactly one word chosen from this fixed set: Joy, Calm, Melancholy, Productive, Anxious.",
  "characters": ["Array of names/relationships of people mentioned. Empty array if none."],
  "scene_prompt": "A vivid, artistic scene description for Stable Diffusion XL. Soft golden or ambient lighting, painterly atmosphere. ABSOLUTELY NO text, letters, words, or typography of any kind."
}

Rules:
- Return ONLY the JSON object.
- Every key must be present.
- emotion must be one of: Joy, Calm, Melancholy, Productive, Anxious.
""".strip()


def _run_gemini_nlp(transcript: str) -> dict:
    """Send transcript to Gemini 2.5 Flash and return parsed structured JSON."""
    logger.info(
        "Running Gemini 2.5 Flash NLP on transcript.",
        extra={"transcript_length": len(transcript)},
    )

    request_body = {
        "contents": [
            {
                "parts": [
                    {"text": _SYSTEM_PROMPT + "\n\nTranscript:\n" + transcript}
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
    except Exception as exc:
        raise RuntimeError(f"Gemini NLP call failed: {exc}") from exc

    try:
        resp_json = response.json()
        raw_content = resp_json["candidates"][0]["content"]["parts"][0]["text"]
        raw_content = raw_content.strip()
        if raw_content.startswith("```"):
            raw_content = raw_content.split("```")[1]
            if raw_content.startswith("json"):
                raw_content = raw_content[4:]
        parsed: dict = json.loads(raw_content.strip())
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("Gemini returned malformed JSON.") from exc

    # Validate keys
    required_keys = {"title", "story", "emotion", "characters", "scene_prompt"}
    missing = required_keys - parsed.keys()
    if missing:
        raise RuntimeError(f"Gemini response missing required keys: {missing}")

    # Normalise emotion
    valid_emotions = {"Joy", "Calm", "Melancholy", "Productive", "Anxious"}
    if parsed.get("emotion") not in valid_emotions:
        parsed["emotion"] = "Calm"

    if not isinstance(parsed.get("characters"), list):
        parsed["characters"] = []

    logger.info(
        "Gemini NLP complete.",
        extra={"title": parsed.get("title"), "emotion": parsed.get("emotion")},
    )
    return parsed


# ──────────────────────────────────────────────────────────────────────────────
# Hugging Face image generation – graceful fallback on failure
# ──────────────────────────────────────────────────────────────────────────────

def _run_hf_image_generation(scene_prompt: str, emotion: str = "Calm") -> Optional[str]:
    """Generate one image via HF SDXL. Returns local URL or a curated Unsplash fallback URL on failure."""
    safety_suffix = (
        " No text, letters, words, numbers, watermarks, or typography of any kind."
    )
    final_prompt = scene_prompt + safety_suffix

    API_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {settings.HF_TOKEN}"}

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
            json={"inputs": final_prompt},
            timeout=90.0,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "HF image generation failed – using premium Unsplash fallback.",
            extra={"error": str(exc)},
        )
        return fallback_url

    filename = f"{uuid.uuid4()}.png"
    dest_path = STATIC_ROOT / "images" / filename
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(response.content)
        logger.info("Image saved locally.", extra={"path": str(dest_path)})
    except Exception as exc:
        logger.warning("Failed to write image to disk – using premium Unsplash fallback.", extra={"error": str(exc)})
        return fallback_url

    return f"/static/images/{filename}"


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

async def process_full_memory(audio: UploadFile, user_id: str) -> dict:
    """
    Full pipeline: audio → transcription → NLP → image → MongoDB persistence.

    Parameters
    ----------
    audio:
        Uploaded audio file from FastAPI.
    user_id:
        Stringified user ObjectId to establish ownership.

    Returns
    -------
    dict
        The complete document stored in MongoDB (including `_id`).

    Raises
    ------
    RuntimeError
        On transcription or NLP failure.
    """
    # ── Save uploaded audio to a temp file ────────────────────────────────────
    tmp_dir = Path("tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid.uuid4()}.wav"

    try:
        with tmp_path.open("wb") as f:
            while chunk := await audio.read(1024 * 64):
                f.write(chunk)
        logger.info("Audio saved to temp path.", extra={"path": str(tmp_path)})
    except Exception as exc:
        raise RuntimeError(f"Failed to save uploaded audio file: {exc}") from exc

    try:
        # ── Step 1: Transcription ──────────────────────────────────────────────
        try:
            whisper_model = _get_whisper_model()
            result = whisper_model.transcribe(str(tmp_path))
            transcript: str = result["text"].strip()
            logger.info(
                "Transcription complete.",
                extra={"transcript_length": len(transcript)},
            )
        except Exception as exc:
            raise RuntimeError(f"Whisper transcription failed: {exc}") from exc

        # ── Step 2: Gemini NLP ─────────────────────────────────────────────────
        nlp = _run_gemini_nlp(transcript)

        # ── Step 3: Image generation (graceful fallback) ───────────────────────
        image_url = _run_hf_image_generation(nlp["scene_prompt"], nlp["emotion"])

        # ── Step 4: Persist to MongoDB ─────────────────────────────────────────
        now_utc = datetime.now(tz=timezone.utc)
        doc = {
            "user_id": user_id,
            "title": nlp["title"],
            "transcript": transcript,
            "story": nlp["story"],
            "emotion": nlp["emotion"],
            "characters": nlp["characters"],
            "scene_prompt": nlp["scene_prompt"],
            "image_url": image_url,
            "created_at": now_utc.isoformat(),
        }

        insert_res = journal_entries.insert_one(doc)
        doc["_id"] = insert_res.inserted_id

        logger.info(
            "Memory persisted to MongoDB.",
            extra={"inserted_id": str(insert_res.inserted_id), "user_id": user_id},
        )
        return doc

    finally:
        # Always clean up the temp audio file
        tmp_path.unlink(missing_ok=True)
