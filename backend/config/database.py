"""
config/database.py
──────────────────
Manages the MongoDB Atlas connection lifecycle for LifeReel AI.

Responsibilities
----------------
- Initialise a single MongoClient from the MONGO_URI environment variable.
- Expose a `verify_connection()` coroutine that fires a ping command so the
  FastAPI startup event can confirm Atlas reachability before the first request
  is ever accepted.
- Export the target database and collection as module-level singletons so every
  route and service can import them without re-creating the client.
"""

import os
import json
import logging
from datetime import datetime
from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConfigurationError, ConnectionFailure, ServerSelectionTimeoutError

from config.settings import settings

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Client initialisation
# ──────────────────────────────────────────────────────────────────────────────

def _create_client() -> MongoClient:
    """
    Build and return a MongoClient.

    serverSelectionTimeoutMS is intentionally short (5 s) so a misconfigured
    MONGO_URI surfaces immediately at startup rather than blocking the first
    real request for 30 seconds.
    """
    try:
        client: MongoClient = MongoClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=5_000,
        )
        logger.info("MongoClient created successfully.")
        return client
    except ConfigurationError as exc:
        logger.critical(
            "MONGO_URI is malformed – cannot create MongoClient.",
            extra={"error": str(exc)},
        )
        raise


client: MongoClient = _create_client()

# ──────────────────────────────────────────────────────────────────────────────
# Database & collection exports
# ──────────────────────────────────────────────────────────────────────────────

class InsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id

class UpdateResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count

class DeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count

class MockCursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, key, direction=-1):
        reverse = (direction == -1)
        def get_val(doc):
            val = doc.get(key, "")
            return val
        self.documents.sort(key=get_val, reverse=reverse)
        return self

    def __iter__(self):
        return iter(self.documents)

class MockCollection:
    def __init__(self, name: str, filepath: str = "local_db.json"):
        self.name = name
        self.filepath = filepath

    def _load_data(self) -> list:
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(self.name, [])
        except Exception:
            return []

    def _save_data(self, docs: list):
        data = {}
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data[self.name] = docs
        class CustomEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, ObjectId):
                    return str(obj)
                if isinstance(obj, datetime):
                    return obj.isoformat()
                return super().default(obj)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, cls=CustomEncoder, indent=2)

    def find_one(self, filter_dict):
        docs = self._load_data()
        for doc in docs:
            if self._matches(doc, filter_dict):
                doc_copy = dict(doc)
                if "_id" in doc_copy:
                    doc_copy["_id"] = ObjectId(doc_copy["_id"])
                return doc_copy
        return None

    def find(self, filter_dict):
        docs = self._load_data()
        matched = []
        for doc in docs:
            if self._matches(doc, filter_dict):
                doc_copy = dict(doc)
                if "_id" in doc_copy:
                    doc_copy["_id"] = ObjectId(doc_copy["_id"])
                matched.append(doc_copy)
        return MockCursor(matched)

    def insert_one(self, doc):
        docs = self._load_data()
        doc_copy = dict(doc)
        if "_id" not in doc_copy:
            doc_copy["_id"] = ObjectId()
        inserted_id = doc_copy["_id"]
        docs.append(doc_copy)
        self._save_data(docs)
        doc["_id"] = inserted_id
        return InsertOneResult(inserted_id)

    def update_many(self, filter_dict, update_dict):
        docs = self._load_data()
        modified_count = 0
        set_fields = update_dict.get("$set", {})
        for doc in docs:
            doc_copy = dict(doc)
            if "_id" in doc_copy:
                doc_copy["_id"] = ObjectId(doc_copy["_id"])
            if self._matches(doc_copy, filter_dict):
                for k, v in set_fields.items():
                    doc[k] = v
                modified_count += 1
        if modified_count > 0:
            self._save_data(docs)
        return UpdateResult(modified_count)

    def delete_one(self, filter_dict):
        docs = self._load_data()
        new_docs = []
        deleted_count = 0
        for doc in docs:
            doc_copy = dict(doc)
            if "_id" in doc_copy:
                doc_copy["_id"] = ObjectId(doc_copy["_id"])
            if deleted_count == 0 and self._matches(doc_copy, filter_dict):
                deleted_count = 1
            else:
                new_docs.append(doc)
        if deleted_count > 0:
            self._save_data(new_docs)
        return DeleteResult(deleted_count)

    def _matches(self, doc, filter_dict) -> bool:
        for k, v in filter_dict.items():
            if isinstance(v, dict):
                if "$exists" in v:
                    exists = v["$exists"]
                    has_key = k in doc
                    if has_key != exists:
                        return False
                    continue
            doc_val = doc.get(k)
            def normalize(val):
                if isinstance(val, ObjectId):
                    return str(val)
                return val
            if normalize(doc_val) != normalize(v):
                return False
        return True

class MongoCollectionProxy:
    def __init__(self, collection_name: str):
        self._name = collection_name
        self._real_coll = None
        self._mock_coll = None
        self._use_fallback = False

    def _get_coll(self):
        if self._use_fallback:
            if self._mock_coll is None:
                self._mock_coll = MockCollection(self._name)
            return self._mock_coll
        else:
            if self._real_coll is None:
                self._real_coll = client["LifeReelAI_DB"][self._name]
            return self._real_coll

    def find_one(self, *args, **kwargs):
        return self._get_coll().find_one(*args, **kwargs)

    def insert_one(self, *args, **kwargs):
        return self._get_coll().insert_one(*args, **kwargs)

    def update_many(self, *args, **kwargs):
        return self._get_coll().update_many(*args, **kwargs)

    def delete_one(self, *args, **kwargs):
        return self._get_coll().delete_one(*args, **kwargs)

    def find(self, *args, **kwargs):
        return self._get_coll().find(*args, **kwargs)

db: Database = client["LifeReelAI_DB"]
journal_entries: Collection = MongoCollectionProxy("journal_entries")  # type: ignore
users: Collection = MongoCollectionProxy("users")  # type: ignore

# ──────────────────────────────────────────────────────────────────────────────
# Startup verification
# ──────────────────────────────────────────────────────────────────────────────

async def verify_connection() -> bool:
    """
    Ping MongoDB Atlas to confirm the connection is live.
    Falls back to local mock database if Atlas is unreachable.
    Returns True if connected to Atlas, False if using fallback.
    """
    try:
        client.admin.command("ping")
        logger.info(
            "MongoDB Atlas ping succeeded – database connection verified.",
            extra={"database": "LifeReelAI_DB"},
        )
        return True
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        logger.warning(
            "MongoDB Atlas ping FAILED – switching to local JSON database fallback.",
            extra={"error": str(exc)},
        )
        journal_entries._use_fallback = True  # type: ignore
        users._use_fallback = True  # type: ignore
        return False
