# backend/scripts/qdrant_index_bootstrap.py
from __future__ import annotations
import os
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

COLLECTION = os.getenv("VECTOR_NAMESPACE", "prod")
DIM = int(os.getenv("EMBED_DIM", "1536"))

def ensure_collection(client: QdrantClient, collection: str, dim: int):
    try:
        client.get_collection(collection)
        return
    except Exception:
        pass
    client.create_collection(
        collection_name=collection,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
    )

def ensure_indexes(client: QdrantClient, collection: str):
    # All the payload keys you filter on should be indexed here:
    index_specs = [
        ("__ns",       "keyword"),
        ("user_email", "keyword"),
        ("session_id", "keyword"),  # stored as string in app code
        ("user_id",    "keyword"),  # if you use it as string; change to "integer" if truly numeric
        ("owner",      "keyword"),
        ("is_public",  "bool"),
        ("doc_id",     "keyword"),
        ("chunk_id",   "keyword"),
    ]
    for field, schema in index_specs:
        try:
            client.create_payload_index(collection_name=collection, field_name=field, field_schema=schema)
            print(f"[ok] created index {field} ({schema})")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"[skip] index {field} exists")
            else:
                raise

def main():
    url = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")
    if url:
        client = QdrantClient(url=url, api_key=api_key, prefer_grpc=False)
    else:
        host = os.getenv("QDRANT_HOST", "localhost")
        port = int(os.getenv("QDRANT_PORT", "6333"))
        client = QdrantClient(host=host, port=port)

    ensure_collection(client, COLLECTION, DIM)
    ensure_indexes(client, COLLECTION)
    print("[done] Qdrant collection & indexes ensured.")

if __name__ == "__main__":
    main()
