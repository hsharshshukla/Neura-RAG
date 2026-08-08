# Neura-RAG

A full-stack Retrieval-Augmented Generation (RAG) application for document-based knowledge retrieval and conversational access to information.

## Overview

Neura-RAG explores how a production-style AI application can combine document ingestion, semantic retrieval, vector search, backend APIs, authentication, analytics, and a user-facing chat experience.

The project goes beyond a basic chatbot by combining a Python backend, vector infrastructure, relational data, application-level controls, and a React frontend.

## Core Capabilities

- Document ingestion and knowledge retrieval
- Retrieval-Augmented Generation (RAG)
- Semantic search using vector embeddings
- Conversational question answering
- User authentication and protected routes
- Chat/session management
- Vector-store abstraction and Qdrant integration
- PostgreSQL-backed application data
- Database migrations with Alembic
- Usage, latency, cost, and RAG analytics
- Admin-facing functionality
- Billing/subscription-oriented application flows
- OpenTelemetry-based observability
- React-based frontend

## High-Level Architecture

```text
User
  │
  ▼
React Frontend
  │
  ▼
FastAPI Backend
  │
  ├── Authentication / User Management
  ├── Chat & Session APIs
  ├── Document Upload / Processing
  ├── Search / Retrieval
  ├── Billing / Usage
  └── Analytics / Admin APIs
          │
          ├──────────────► PostgreSQL
          │
          └──────────────► Vector Store
                              │
                              ▼
                            Qdrant
                              │
                              ▼
                        Relevant Context
                              │
                              ▼
                              LLM
                              │
                              ▼
                         Final Response
```

## RAG Flow

```text
Documents
   │
   ▼
Ingestion / Processing
   │
   ▼
Chunking + Metadata
   │
   ▼
Embeddings
   │
   ▼
Vector Store
   │
User Query
   ▼
Semantic Retrieval
   │
   ▼
Relevant Context
   │
   ▼
LLM Generation
   │
   ▼
Conversational Response
```

## Technology

### Backend
- Python
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL

### AI / Retrieval
- Retrieval-Augmented Generation (RAG)
- OpenAI embeddings / LLM integration
- Qdrant
- Vector search
- Metadata-filtered retrieval

### Frontend
- React
- JavaScript
- React Router
- Axios
- Tailwind-style utility classes

### Observability & Platform
- OpenTelemetry
- Application logging
- API instrumentation
- Docker / deployment-oriented configuration

## Engineering Areas Explored

The project focuses on the engineering around AI applications, including:

- API design
- vector-database initialization and indexing
- retrieval metadata and filtering
- application lifecycle management
- database schema evolution
- authentication and authorization
- usage and cost tracking
- RAG quality signals
- latency monitoring
- admin workflows
- error handling
- frontend/backend integration
- production-oriented configuration

## Analytics

The application includes data structures for measuring operational and RAG-specific signals such as:

- message and session counts
- model/provider usage
- input and output tokens
- response latency
- retrieval latency
- estimated cost
- RAG hit rate
- user feedback / CSAT
- response codes

This was added to make the RAG system measurable rather than treating LLM output as a black box.

## Project Status

**Active technical project / evolving platform**

Neura-RAG is a hands-on engineering project used to explore the design of a complete AI-enabled application. It is not presented as a finished commercial SaaS product, and individual components may continue to evolve.

## Why This Project Matters

This project brings together several areas of my current engineering focus:

- Python backend development
- REST APIs
- relational and vector databases
- system design
- RAG and Generative AI
- application security
- observability
- full-stack integration

It reflects my broader direction toward backend, AI-platform, and enterprise-scale software systems.
