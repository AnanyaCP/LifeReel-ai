"""
main.py
───────
LifeReel AI – FastAPI application entry point.

Startup sequence
────────────────
  1. Logging is configured (structured to stdout).
  2. The lifespan context manager runs startup diagnostics:
       - MongoDB ping
       - Gemini API ping
       - Hugging Face token check
       - Whisper library check + model warmup
     Each check logs PASS/FAIL status.
  3. CORSMiddleware is registered to allow the React frontend all origins.

Routes
──────
  POST /api/entries/generate   – Text AI pipeline + MongoDB persistence
  POST /api/memory/create      – Audio upload + full AI pipeline + persistence
  GET  /api/entries/timeline   – All entries sorted newest-first
  GET  /api/entries/{entry_id} – Single entry by ID
  DELETE /api/entries/{entry_id} – Delete entry by ID
  GET  /health                 – Liveness probe
"""

import logging
import logging.config
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os

from bson import ObjectId
from fastapi import FastAPI, HTTPException, status, File, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import httpx

from config.database import journal_entries, verify_connection, users
from config.settings import settings, STATIC_ROOT
from models.schemas import DiaryInput, EntryResponse, UserRegister, UserLogin, TokenResponse, UserResponse
from services.ai_engine import process_voice_diary
from services.voice_pipeline import process_full_memory
from services.auth import get_current_user, hash_password

# ──────────────────────────────────────────────────────────────────────────────
# Logging configuration
# ──────────────────────────────────────────────────────────────────────────────

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
            "stream": "ext://sys.stdout",
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "pymongo": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Startup diagnostics
# ──────────────────────────────────────────────────────────────────────────────

async def _run_startup_diagnostics():
    """
    Ping all external dependencies and print a PASS/FAIL report.
    A failed critical dependency (MongoDB, Gemini) raises an exception
    to abort startup.
    """
    logger.info("=" * 60)
    logger.info("LifeReel AI – Startup Diagnostics")
    logger.info("=" * 60)

    results = {}

    # 1. MongoDB ping
    try:
        connected = await verify_connection()
        if connected:
            results["MongoDB"] = "PASS"
        else:
            results["MongoDB"] = "PASS (Local Fallback)"
    except Exception as exc:
        results["MongoDB"] = f"FAIL – {exc}"

    # 2. Gemini API ping (simple request to check API key validity)
    try:
        gemini_url = (
            "https://generativelanguage.googleapis.com/v1beta/models?"
            f"key={settings.GEMINI_API_KEY}"
        )
        resp = httpx.get(gemini_url, timeout=10.0)
        if resp.status_code == 200:
            results["Gemini API"] = "PASS"
        else:
            results["Gemini API"] = f"FAIL – HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        results["Gemini API"] = f"FAIL – {exc}"

    # 3. Hugging Face token check (checks validity + inference permissions)
    try:
        hf_resp = httpx.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {settings.HF_TOKEN}"},
            timeout=10.0,
        )
        if hf_resp.status_code != 200:
            results["Hugging Face"] = f"FAIL – Invalid token (HTTP {hf_resp.status_code})"
        else:
            # Token is valid, test inference providers permission
            test_url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
            test_resp = httpx.post(
                test_url,
                headers={"Authorization": f"Bearer {settings.HF_TOKEN}"},
                json={"inputs": "startup test"},
                timeout=10.0
            )
            if test_resp.status_code in (200, 503):
                results["Hugging Face"] = "PASS"
            elif test_resp.status_code == 403:
                results["Hugging Face"] = "PASS (Inference Blocked - Token lacks 'Make calls to Inference Providers' permission)"
            else:
                results["Hugging Face"] = f"PASS (Inference Warning - HTTP {test_resp.status_code})"
    except Exception as exc:
        results["Hugging Face"] = f"PASS (Inference Error – {exc})"

    # 4. Whisper library check
    try:
        import whisper  # noqa: F401
        results["Whisper library"] = "PASS"
    except ImportError:
        results["Whisper library"] = "FAIL – openai-whisper not installed"

    # Print report
    logger.info("-" * 60)
    for name, status_str in results.items():
        icon = "[OK]" if status_str.startswith("PASS") else "[!!]"
        logger.info(f"  {icon} {name:25s} {status_str}")
    logger.info("=" * 60)

    # Abort if critical services are down (MongoDB + Gemini only)
    critical_failures = [
        name for name, s in results.items()
        if name in ("MongoDB", "Gemini API") and not s.startswith("PASS")
    ]
    if critical_failures:
        raise RuntimeError(
            f"Critical startup dependency checks failed: {critical_failures}. "
            "Please check your .env file and service availability."
        )

    if results.get("Whisper library") != "PASS":
        logger.warning(
            "Whisper not installed — audio upload (/api/memory/create) will be unavailable. "
            "Install with: .venv\\Scripts\\pip install openai-whisper"
        )
    
    hf_status = results.get("Hugging Face", "")
    if "FAIL" in hf_status:
        logger.warning(
            "Hugging Face token invalid — image generation will use curated fallback images. "
            "Update HF_TOKEN in .env with a valid token from huggingface.co/settings/tokens"
        )
    elif "Inference Blocked" in hf_status:
        logger.warning(
            "Hugging Face token lacks permissions to call Inference Providers. "
            "Please go to huggingface.co/settings/tokens, edit your token, "
            "and check the 'Make calls to Inference Providers' checkbox under Inference permissions. "
            "Until updated, image generation will automatically use curated Unsplash fallback images based on the entry's emotion."
        )
    elif hf_status != "PASS":
        logger.warning(
            f"Hugging Face inference warnings present: {hf_status}. "
            "Image generation will fall back to curated Unsplash fallback images if needed."
        )

    # 5. User DB and Memory Isolation Migration Setup
    try:
        demo_email = "demo@lifereel.ai"
        demo_user = users.find_one({"email": demo_email})
        if not demo_user:
            logger.info("Auto-creating default demo user: demo@lifereel.ai")
            demo_doc = {
                "username": "Demo User",
                "email": demo_email,
                "password_hash": hash_password("password"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "avatar": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&h=150&q=80",
                "streak": 5
            }
            users.insert_one(demo_doc)
            demo_user = users.find_one({"email": demo_email})
        
        demo_user_id = str(demo_user["_id"])
        
        # Migrate existing memories without user_id
        migrated = journal_entries.update_many(
            {"user_id": {"$exists": False}},
            {"$set": {"user_id": demo_user_id}}
        )
        if migrated.modified_count > 0:
            logger.info(
                f"Migration successful: assigned {migrated.modified_count} "
                f"unowned memories to default demo user ({demo_user_id})."
            )
    except Exception as exc:
        logger.error("Failed to run demo user setup and database migration.", extra={"error": str(exc)})


# ──────────────────────────────────────────────────────────────────────────────
# Lifespan – startup / shutdown
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs startup diagnostics before the server accepts connections."""
    logger.info("LifeReel AI – starting up …")
    await _run_startup_diagnostics()
    logger.info("LifeReel AI – ready to accept requests.")
    yield
    logger.info("LifeReel AI – shutting down.")


# ──────────────────────────────────────────────────────────────────────────────
# Application factory
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="LifeReel AI",
    description="Intelligent Visual Memory Diary – Backend API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _serialize_entry(doc: dict) -> EntryResponse:
    """
    Convert a raw MongoDB document into an EntryResponse.
    Handles both the new unified schema and old schema documents gracefully.
    """
    return EntryResponse(
        id=str(doc["_id"]),
        user_id=str(doc.get("user_id")) if doc.get("user_id") else None,
        title=doc.get("title", "Untitled"),
        transcript=doc.get("transcript", doc.get("raw_text", "")),
        story=doc.get("story", doc.get("narrative", "")),
        emotion=doc.get("emotion", doc.get("dominant_emotion", "Calm")),
        characters=doc.get("characters", []),
        scene_prompt=doc.get("scene_prompt", doc.get("image_prompt", "")),
        image_url=doc.get("image_url") or None,
        created_at=doc.get("created_at", doc.get("timestamp", "")),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.post(
    "/api/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user.",
    tags=["Authentication"],
)
async def register_user(payload: UserRegister):
    """
    Register a new user. Stores password securely hashed in the database.
    """
    # Check if user already exists
    if users.find_one({"email": payload.email.lower().strip()}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email is already registered.",
        )
    
    # Save user document
    now_str = datetime.now(tz=timezone.utc).isoformat()
    user_doc = {
        "username": payload.username.strip(),
        "email": payload.email.lower().strip(),
        "password_hash": hash_password(payload.password),
        "created_at": now_str,
        "avatar": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=150&h=150&q=80",
        "streak": 1
    }
    
    try:
        insert_res = users.insert_one(user_doc)
        user_doc["_id"] = insert_res.inserted_id
        logger.info("New user registered successfully.", extra={"email": user_doc["email"], "id": str(user_doc["_id"])})
    except Exception as exc:
        logger.exception("Failed to write new user to database.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete user registration."
        ) from exc
    
    return UserResponse(
        id=str(user_doc["_id"]),
        username=user_doc["username"],
        email=user_doc["email"],
        joined_date=datetime.now(timezone.utc).strftime("%B %d, %Y"),
        avatar=user_doc["avatar"],
        streak=user_doc["streak"]
    )


@app.post(
    "/api/auth/login",
    response_model=TokenResponse,
    summary="Log in user and return JWT.",
    tags=["Authentication"],
)
async def login_user(payload: UserLogin):
    """
    Authenticate user and return a signed JWT token containing their user ID.
    """
    from services.auth import verify_password, create_access_token

    email_clean = payload.email.lower().strip()
    user = users.find_one({"email": email_clean})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    
    access_token = create_access_token(user_id=str(user["_id"]))
    
    # Format joined date nicely for frontend compatibility
    try:
        joined_dt = datetime.fromisoformat(user.get("created_at"))
        joined_str = joined_dt.strftime("%B %d, %Y")
    except Exception:
        joined_str = "June 1, 2026"

    user_res = UserResponse(
        id=str(user["_id"]),
        username=user.get("username", "User"),
        email=user["email"],
        joined_date=joined_str,
        avatar=user.get("avatar", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&h=150&q=80"),
        streak=user.get("streak", 1)
    )
    
    logger.info("User logged in successfully.", extra={"email": email_clean})
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=user_res
    )


@app.post(
    "/api/entries/generate",
    response_model=EntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Process a typed diary entry through the AI pipeline and persist it.",
    tags=["Diary Entries"],
)
async def generate_entry(payload: DiaryInput, current_user: dict = Depends(get_current_user)):
    """
    Full pipeline for typed text entries:

    1. Validate the incoming raw_text.
    2. Hand off to ai_engine (Gemini NLP → HF image generation).
    3. Persist to MongoDB associated with the authenticated user ID.
    4. Return the saved document as EntryResponse.
    """
    logger.info(
        "POST /api/entries/generate – received entry.",
        extra={"raw_text_length": len(payload.raw_text), "user_id": str(current_user["_id"])},
    )

    # Step 1 & 2: AI orchestration
    try:
        ai_result: dict = process_voice_diary(payload.raw_text)
    except RuntimeError as exc:
        logger.error("AI pipeline error in generate_entry.", extra={"error": str(exc)})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during AI pipeline.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during AI processing.",
        ) from exc

    # Step 3: Build and persist the document
    now_utc = datetime.now(tz=timezone.utc)
    document = {
        "user_id": str(current_user["_id"]),
        "title": ai_result["title"],
        "transcript": payload.raw_text,
        "story": ai_result["story"],
        "emotion": ai_result["emotion"],
        "characters": ai_result.get("characters", []),
        "scene_prompt": ai_result["scene_prompt"],
        "image_url": ai_result.get("image_url"),
        "created_at": now_utc.isoformat(),
    }

    try:
        insert_result = journal_entries.insert_one(document)
        document["_id"] = insert_result.inserted_id
        logger.info(
            "Journal entry persisted to MongoDB.",
            extra={"inserted_id": str(insert_result.inserted_id), "user_id": str(current_user["_id"])},
        )
    except Exception as exc:
        logger.exception("Failed to write journal entry to MongoDB.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save the journal entry to the database.",
        ) from exc

    return _serialize_entry(document)


@app.post(
    "/api/memory/create",
    response_model=EntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload audio, run full AI pipeline, and persist memory.",
    tags=["Memory"],
)
async def create_memory(file: UploadFile = File(None), audio: UploadFile = File(None), current_user: dict = Depends(get_current_user)):
    """
    Full pipeline for audio voice entries:
    1. Accept audio file upload (key 'file' or 'audio').
    2. Transcribe with local Whisper.
    3. Gemini NLP analysis.
    4. HF image generation (graceful null fallback).
    5. Persist to MongoDB linked to the current user.
    6. Return EntryResponse.
    """
    uploaded_file = file or audio
    if not uploaded_file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file uploaded. Please upload a file with key 'file' or 'audio'.",
        )

    logger.info(
        "POST /api/memory/create – received file upload.",
        extra={"upload_filename": uploaded_file.filename, "user_id": str(current_user["_id"])},
    )

    try:
        doc = await process_full_memory(uploaded_file, str(current_user["_id"]))
    except RuntimeError as exc:
        logger.error("AI pipeline error in create_memory.", extra={"error": str(exc)})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during memory creation.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the memory.",
        ) from exc

    return _serialize_entry(doc)


@app.get(
    "/api/entries/timeline",
    response_model=dict,
    summary="Retrieve all journal entries, newest first.",
    tags=["Diary Entries"],
)
async def get_timeline(current_user: dict = Depends(get_current_user)):
    """Returns all persisted entries for the authenticated user, sorted by created_at descending."""
    user_id_str = str(current_user["_id"])
    logger.info("GET /api/entries/timeline – fetching entries for user.", extra={"user_id": user_id_str})

    try:
        cursor = journal_entries.find({"user_id": user_id_str}).sort("created_at", -1)
        entries = []
        for doc in cursor:
            try:
                entries.append(_serialize_entry(doc).model_dump())
            except Exception as exc:
                logger.warning(
                    "Skipping malformed document during timeline serialisation.",
                    extra={"doc_id": str(doc.get("_id")), "error": str(exc)},
                )

        logger.info("Timeline query complete.", extra={"entry_count": len(entries), "user_id": user_id_str})
        return {"timeline": entries}

    except Exception as exc:
        logger.exception("Failed to query MongoDB for timeline.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve the timeline from the database.",
        ) from exc


@app.get(
    "/api/entries/{entry_id}",
    response_model=EntryResponse,
    summary="Retrieve a single entry by ID.",
    tags=["Diary Entries"],
)
async def get_entry(entry_id: str, current_user: dict = Depends(get_current_user)):
    """Retrieve a single entry document from MongoDB by its stringified ID, verifying ownership."""
    user_id_str = str(current_user["_id"])
    try:
        doc = journal_entries.find_one({"_id": ObjectId(entry_id)})
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memory entry not found.",
            )
        
        # Verify ownership
        if doc.get("user_id") != user_id_str:
            logger.warning(
                "Access forbidden: User tried to view a memory they do not own.",
                extra={"user_id": user_id_str, "entry_id": entry_id, "owner_id": doc.get("user_id")}
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this memory.",
            )
            
        return _serialize_entry(doc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to query MongoDB for single entry.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve the entry from the database.",
        ) from exc


@app.delete(
    "/api/entries/{entry_id}",
    summary="Delete a memory entry by ID.",
    tags=["Diary Entries"],
)
async def delete_entry(entry_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a single entry document from MongoDB by its stringified ID, verifying ownership."""
    user_id_str = str(current_user["_id"])
    try:
        doc = journal_entries.find_one({"_id": ObjectId(entry_id)})
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memory entry not found.",
            )
        
        # Verify ownership
        if doc.get("user_id") != user_id_str:
            logger.warning(
                "Deletion forbidden: User tried to delete a memory they do not own.",
                extra={"user_id": user_id_str, "entry_id": entry_id, "owner_id": doc.get("user_id")}
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this memory.",
            )

        delete_result = journal_entries.delete_one({"_id": ObjectId(entry_id)})
        if delete_result.deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memory entry not found.",
            )
        return {"status": "success", "message": "Entry deleted successfully."}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to delete MongoDB entry.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete entry from database.",
        ) from exc


# ──────────────────────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"], summary="Liveness probe.")
async def health_check():
    """Returns 200 OK when the server is running."""
    return {"status": "ok", "service": "LifeReel AI", "version": "2.0.0"}


# ──────────────────────────────────────────────────────────────────────────────
# Dev runner – `python main.py`
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
