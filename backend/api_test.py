"""
api_test.py — Quick connectivity test for all LifeReel AI integrations.
Run with: .venv\Scripts\python api_test.py
"""
import os
import sys
import json
import httpx
from dotenv import load_dotenv

load_dotenv()

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

results = {}

# ──────────────────────────────────────────────────────────────────────────────
# TEST 1: Gemini 3.1 Flash-Lite API
# ──────────────────────────────────────────────────────────────────────────────
print("=" * 55)
print("TEST 1: Gemini 3.1 Flash-Lite API")
print("=" * 55)
try:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={GEMINI_KEY}"
    body = {
        "contents": [{"parts": [{"text": "Say hello in one sentence."}]}],
        "generationConfig": {"maxOutputTokens": 60}
    }
    r = httpx.post(url, json=body, timeout=25)
    print(f"  HTTP Status : {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"  Response    : {text[:100]}")
        print("  RESULT      : ✓ PASS")
        results["Gemini API"] = "PASS"
    else:
        err = r.json().get("error", {})
        print(f"  Error       : {err.get('message', r.text[:200])}")
        print("  RESULT      : ✗ FAIL")
        results["Gemini API"] = f"FAIL — {err.get('message','')}"
except Exception as e:
    print(f"  Exception   : {e}")
    print("  RESULT      : ✗ FAIL")
    results["Gemini API"] = f"FAIL — {e}"

print()

# ──────────────────────────────────────────────────────────────────────────────
# TEST 2: Full Gemini NLP (diary entry test)
# ──────────────────────────────────────────────────────────────────────────────
print("=" * 55)
print("TEST 2: Gemini NLP — Full diary pipeline")
print("=" * 55)
SYSTEM_PROMPT = """You are LifeReel AI. Transform the diary entry into JSON with exactly these keys:
{"title":"...", "story":"...", "emotion":"Joy", "characters":[], "scene_prompt":"..."}
Return ONLY valid JSON."""
try:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={GEMINI_KEY}"
    body = {
        "contents": [{"parts": [{"text": SYSTEM_PROMPT + "\n\nDiary: Today I went for a walk in the park with my friend Sara. It was beautiful."}]}],
        "generationConfig": {"maxOutputTokens": 400, "responseMimeType": "application/json"}
    }
    r = httpx.post(url, json=body, timeout=25)
    print(f"  HTTP Status : {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        parsed = json.loads(raw)
        print(f"  Title       : {parsed.get('title','')}")
        print(f"  Emotion     : {parsed.get('emotion','')}")
        print(f"  Characters  : {parsed.get('characters','')}")
        print(f"  Story       : {parsed.get('story','')[:80]}...")
        print("  RESULT      : ✓ PASS")
        results["Gemini NLP"] = "PASS"
    else:
        print(f"  Error       : {r.text[:300]}")
        print("  RESULT      : ✗ FAIL")
        results["Gemini NLP"] = "FAIL"
except Exception as e:
    print(f"  Exception   : {e}")
    print("  RESULT      : ✗ FAIL")
    results["Gemini NLP"] = f"FAIL — {e}"

print()

# ──────────────────────────────────────────────────────────────────────────────
# TEST 3: Hugging Face Token Validation
# ──────────────────────────────────────────────────────────────────────────────
print("=" * 55)
print("TEST 3: Hugging Face Token")
print("=" * 55)
try:
    r = httpx.get(
        "https://huggingface.co/api/whoami-v2",
        headers={"Authorization": f"Bearer {HF_TOKEN}"},
        timeout=10
    )
    print(f"  HTTP Status : {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Username    : {data.get('name','unknown')}")
        print(f"  Type        : {data.get('type','unknown')}")
        print("  RESULT      : ✓ PASS")
        results["Hugging Face"] = "PASS"
    else:
        print(f"  Error       : {r.text[:200]}")
        print("  RESULT      : ✗ FAIL")
        results["Hugging Face"] = "FAIL"
except Exception as e:
    print(f"  Exception   : {e}")
    print("  RESULT      : ✗ FAIL")
    results["Hugging Face"] = f"FAIL — {e}"

print()

# ──────────────────────────────────────────────────────────────────────────────
# TEST 4: MongoDB Connection
# ──────────────────────────────────────────────────────────────────────────────
print("=" * 55)
print("TEST 4: MongoDB Connection")
print("=" * 55)
try:
    from pymongo import MongoClient
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    info = client.admin.command("ping")
    print(f"  Ping result : {info}")
    print(f"  URI         : {MONGO_URI}")
    print("  RESULT      : ✓ PASS")
    results["MongoDB"] = "PASS"
    client.close()
except Exception as e:
    print(f"  Exception   : {e}")
    print("  RESULT      : ✗ FAIL")
    results["MongoDB"] = f"FAIL — {e}"

print()

# ──────────────────────────────────────────────────────────────────────────────
# TEST 5: Whisper library check
# ──────────────────────────────────────────────────────────────────────────────
print("=" * 55)
print("TEST 5: Whisper Library")
print("=" * 55)
try:
    import whisper
    print(f"  Version     : openai-whisper installed OK")
    print("  RESULT      : ✓ PASS")
    results["Whisper"] = "PASS"
except ImportError as e:
    print(f"  Not installed: {e}")
    print("  RESULT      : ✗ FAIL (install openai-whisper)")
    results["Whisper"] = "FAIL — not installed"

# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────
print()
print("=" * 55)
print("SUMMARY")
print("=" * 55)
all_pass = True
for name, status in results.items():
    icon = "✓" if status == "PASS" else "✗"
    print(f"  {icon}  {name:20s}  {status}")
    if status != "PASS":
        all_pass = False

print()
if all_pass:
    print("  🎉 ALL TESTS PASSED — Ready to launch!")
else:
    print("  ⚠  Some tests FAILED — check the errors above.")
print("=" * 55)
