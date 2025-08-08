# vector_store.py — Handles vector embedding and metadata-filtered retrieval
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from typing import List, Dict, Optional
import os
from dotenv import load_dotenv

load_dotenv()

CHROMA_DIR = "vector_store"
embeddings = OpenAIEmbeddings()

def embed_and_store(user_email: str, text: str, metadata: Optional[Dict] = None):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.create_documents([text])

    # Attach metadata to each chunk
    metadata = metadata or {}
    for chunk in chunks:
        chunk.metadata.update(metadata)

    vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    vectordb.add_documents(chunks)
    vectordb.persist()

def query_user_docs(
    user_email: str,
    question: str,
    top_k: int = 4,
    filter_by_user: bool = True,
    extra_filters: Optional[Dict] = None
) -> List[Document]:
    vectordb = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    
    filters = extra_filters or {}
    if filter_by_user:
        filters["user_email"] = user_email

    return vectordb.similarity_search(question, k=top_k, filter=filters)
