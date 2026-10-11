# AI Knowledge Assistant

<p align="left">
  <img src="docs/badges/python.svg" alt="Python 3.12" height="28">
  <img src="docs/badges/fastapi.svg" alt="FastAPI API" height="28">
  <img src="docs/badges/react.svg" alt="React Frontend" height="28">
  <img src="docs/badges/typescript.svg" alt="TypeScript Frontend" height="28">
  <img src="docs/badges/vite.svg" alt="Vite Build" height="28">
  <br>
  <img src="docs/badges/docker.svg" alt="Docker Enabled" height="28">
  <img src="docs/badges/sqlite.svg" alt="SQLite Database" height="28">
  <img src="docs/badges/chromadb.svg" alt="ChromaDB Vector Store" height="28">
  <img src="docs/badges/sentence-transformers.svg" alt="Sentence Transformers Embeddings" height="28">
  <img src="docs/badges/openrouter.svg" alt="OpenRouter LLM API" height="28">
  <br>
  <img src="docs/badges/jwt.svg" alt="JWT Authentication" height="28">
  <img src="docs/badges/argon2.svg" alt="Argon2 Password Hashing" height="28">
  <img src="docs/badges/alembic.svg" alt="Alembic Migrations" height="28">
  <img src="docs/badges/sqlalchemy.svg" alt="SQLAlchemy Async" height="28">
  <br>
  <img src="docs/badges/rag.svg" alt="RAG Hybrid Retrieval" height="28">
  <img src="docs/badges/llm-wiki.svg" alt="LLM Wiki Generation" height="28">
  <img src="docs/badges/architecture.svg" alt="Architecture Clean Architecture" height="28">
  <img src="docs/badges/citations.svg" alt="Answers Grounded Citations" height="28">
  <br>
  <img src="docs/badges/vercel.svg" alt="Vercel Frontend" height="28">
  <img src="docs/badges/railway.svg" alt="Railway Backend Tested" height="28">
  <br>
</p>

A full-stack AI platform that transforms uploaded documents into a structured internal Wiki and provides grounded answers with traceable citations.

The application combines document processing, multilingual semantic retrieval, generative AI, authentication, persistent storage, and a modern React interface in a complete end-to-end workflow.

## Live Demo

**Frontend:**  
https://enterprise-ai-knowledge.vercel.app

**GitHub Repository:**  
https://github.com/AfroditiTzama/Enterprise-AI_Knowledge

> The frontend is deployed on Vercel.  
> The complete AI pipeline can be run locally. Free cloud instances may not provide enough memory to load the Sentence Transformer model together with FastAPI, PyTorch, and ChromaDB reliably.

---

## Overview

The Enterprise AI Knowledge Assistant allows authenticated users to:

1. Upload PDF, DOCX, and TXT documents.
2. Extract and clean their textual content.
3. Divide the extracted content into overlapping chunks.
4. Generate semantic embeddings for every chunk.
5. Store vectors and document metadata persistently.
6. Transform each document into an LLM-generated internal Wiki.
7. Browse and search structured Wiki pages.
8. Ask questions across both the generated Wiki and original document chunks.
9. Receive grounded answers with citations and traceable sources.

This project is not implemented as a simple RAG chatbot.

In addition to document retrieval, it introduces a persistent **LLM Wiki layer** that organizes unstructured document content into structured pages, summaries, sources, and internal links.

---

## Key Features

### Authentication and Security

- User registration and login
- Argon2 password hashing
- JWT Bearer authentication
- Protected API endpoints
- User-specific documents and Wiki pages
- Owner-based retrieval filtering
- Environment-based secret management
- Protection against storage path traversal

### Document Management

- Upload PDF, DOCX, and TXT files
- Persistent document metadata
- Document processing status
- File type and size tracking
- User-isolated document access

### Text Extraction

- PDF extraction using `pypdf`
- DOCX extraction using `python-docx`
- Paragraph and table extraction
- TXT decoding with multiple encoding fallbacks
- Page-level metadata where available
- Unicode cleaning before LLM requests

### Text Chunking

- Recursive text splitting
- Configurable chunk size
- Configurable chunk overlap
- Preservation of page numbers
- Persistent chunk storage in SQLite

### Ingestion Consistency

- ChromaDB vectors are staged and verified under a processing-job generation.
- SQLite activates the matching chunks and vector generation in one commit.
- Retrieval filters vectors through the active generation stored on the document.
- Failed or interrupted attempts retain the last successful generation.
- The local worker requeues interrupted jobs and removes inactive vector generations.
- A partial SQLite unique index permits only one queued or running job per document.

### Embeddings and Vector Search

- Multilingual Sentence Transformer embeddings
- Normalized semantic vectors
- Persistent ChromaDB collection
- Cosine similarity search
- User-based vector filtering
- Traceable chunk metadata

### LLM Wiki Generation

- Document-to-Wiki compilation
- OpenRouter LLM integration
- Structured Wiki pages
- Wiki page titles
- Page summaries
- Markdown content
- Wiki source associations
- Internal Wiki links
- Persistent storage in SQLite

### Knowledge Assistant

- Retrieval from original document chunks
- Retrieval from generated Wiki pages
- Hybrid knowledge context
- Grounded LLM answers
- Inline citations such as `[S1]`
- Source identifiers
- Similarity scores
- Page and chunk metadata
- Markdown response rendering

### Frontend

- React and TypeScript
- Vite
- Responsive dark interface
- Login and registration
- Protected routes
- Document dashboard
- Upload and processing controls
- Wiki browser
- Wiki search
- Knowledge Assistant chat
- Loading states
- Success and error messages
- Vercel SPA routing

---

## System Architecture

```mermaid
flowchart LR
    USER[User] --> WEB[React Web Application]

    WEB -->|JWT REST Requests| API[FastAPI Backend]

    API --> AUTH[Authentication]
    API --> DOCUMENTS[Document Processing]
    API --> WIKI[LLM Wiki Compiler]
    API --> CHAT[Knowledge Assistant]

    AUTH --> DATABASE[(SQLite)]

    DOCUMENTS --> FILES[Persistent File Storage]
    DOCUMENTS --> EXTRACTORS[PDF / DOCX / TXT Extractors]
    EXTRACTORS --> CHUNKER[Recursive Text Chunker]
    CHUNKER --> EMBEDDINGS[Sentence Transformer]
    EMBEDDINGS --> VECTOR_DB[(ChromaDB)]

    DOCUMENTS --> DATABASE

    WIKI --> OPENROUTER[OpenRouter API]
    WIKI --> DATABASE

    CHAT --> EMBEDDINGS
    CHAT --> VECTOR_DB
    CHAT --> DATABASE
    CHAT --> OPENROUTER
```

---

## End-to-End Workflow

```text
User registration or login
        ↓
JWT access token
        ↓
Document upload
        ↓
Persistent file and metadata storage
        ↓
PDF, DOCX, or TXT text extraction
        ↓
Recursive overlapping chunk creation
        ↓
Sentence Transformer embedding generation
        ↓
SQLite chunk persistence
        ↓
ChromaDB vector persistence
        ↓
LLM Wiki compilation
        ↓
Wiki page, source, and link persistence
        ↓
Hybrid Wiki and document retrieval
        ↓
Grounded answer generation
        ↓
Answer with traceable citations
```

---

## Technology Stack

### Backend

- Python 3.12
- FastAPI
- Pydantic v2
- SQLAlchemy Async
- Alembic
- SQLite
- Aiosqlite
- JWT
- Argon2
- HTTPX

### Artificial Intelligence

- Sentence Transformers
- PyTorch
- OpenRouter API
- Gemini through OpenRouter
- Multilingual semantic embeddings
- Retrieval-Augmented Generation
- LLM-generated Wiki compilation
- Prompt engineering

### Vector Storage

- ChromaDB
- Persistent vector collections
- Cosine similarity retrieval
- Metadata filtering

### Document Processing

- pypdf
- python-docx
- PDF page extraction
- DOCX paragraph and table extraction
- TXT encoding fallbacks
- Recursive text chunking

### Frontend

- React
- TypeScript
- Vite
- Axios
- React Router
- React Markdown
- Lucide React
- CSS

### Infrastructure

- Docker
- Railway
- Vercel
- GitHub
- Persistent filesystem storage

---

## Project Structure

```text
Enterprise-AI_Knowledge/
├── apps/
│   ├── api/
│   │   ├── migrations/
│   │   │   └── versions/
│   │   ├── scripts/
│   │   ├── src/
│   │   │   └── knowledge_assistant/
│   │   │       ├── application/
│   │   │       │   ├── auth/
│   │   │       │   ├── chat/
│   │   │       │   ├── documents/
│   │   │       │   └── wiki/
│   │   │       ├── bootstrap/
│   │   │       │   └── dependencies/
│   │   │       ├── core/
│   │   │       ├── domain/
│   │   │       │   ├── embeddings/
│   │   │       │   ├── users/
│   │   │       │   ├── documents/
│   │   │       │   ├── vector_store/
│   │   │       │   └── wiki/
│   │   │       ├── infrastructure/
│   │   │       │   ├── database/
│   │   │       │   ├── documents/
│   │   │       │   ├── embeddings/
│   │   │       │   ├── security/
│   │   │       │   ├── storage/
│   │   │       │   ├── vector_store/
│   │   │       │   └── wiki/
│   │   │       ├── presentation/
│   │   │       │   └── api/
│   │   │       └── main.py
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   ├── .dockerignore
│   │   ├── alembic.ini
│   │   └── pyproject.toml
│   │
│   └── web/
│       ├── public/
│       ├── src/
│       │   ├── api/
│       │   ├── components/
│       │   ├── pages/
│       │   ├── App.tsx
│       │   ├── index.css
│       │   └── main.tsx
│       ├── package.json
│       ├── vercel.json
│       └── vite.config.ts
│
├── docs/
├── docker-compose.yml
├── Makefile
├── .gitignore
└── README.md
```

---

## Backend Architecture

The backend follows **Clean Architecture** and **Domain-Driven Design** principles.

### Domain Layer

The domain layer contains the core business entities and abstractions.

Examples include:

- User
- Document
- Document status
- Document chunk
- Wiki page
- Wiki page source
- Wiki page link
- Repository interfaces
- File storage interface
- Text extractor interface
- Text chunker interface
- Embedding service interface
- Vector store interface

The domain layer does not depend on FastAPI, SQLAlchemy, ChromaDB, or OpenRouter.

### Application Layer

The application layer contains use cases and orchestration logic.

Examples include:

- Register user
- Authenticate user
- Upload document
- List user documents
- Process document
- Extract text
- Generate chunks
- Generate embeddings
- Persist vector records
- Compile document Wiki
- List Wiki pages
- Retrieve a Wiki page
- Ask the Knowledge Assistant

### Infrastructure Layer

The infrastructure layer contains technical implementations.

Examples include:

- SQLAlchemy database models
- SQLAlchemy repositories
- SQLite database configuration
- Alembic migrations
- Local file storage
- PDF extractor
- DOCX extractor
- TXT extractor
- Recursive text chunker
- Sentence Transformer embedding service
- ChromaDB vector store
- OpenRouter Wiki compiler
- OpenRouter answer generator
- JWT implementation
- Argon2 password hashing

### Presentation Layer

The presentation layer contains:

- FastAPI routers
- Request schemas
- Response schemas
- Authentication dependencies
- API exception handling
- HTTP status management

### Bootstrap Layer

The bootstrap layer connects interfaces to concrete infrastructure implementations through FastAPI dependency injection.

---

## API Endpoints

### Authentication

```http
POST /auth/register
POST /auth/login
GET  /auth/me
```

### Documents

```http
POST /documents
GET  /documents
POST /documents/{document_id}/process
```

### Wiki

```http
POST /wiki/documents/{document_id}/compile
GET  /wiki/pages
GET  /wiki/pages/{slug}
```

### Knowledge Assistant

```http
POST /chat/ask
```

Interactive API documentation is available locally at:

```text
http://127.0.0.1:8000/docs
```

---

## Example Workflow

### 1. Register an account

Create a user account with:

- Full name
- Email
- Password

### 2. Upload a document

Supported file formats:

```text
.pdf
.docx
.txt
```

### 3. Process the document

The processing pipeline:

- Reads the uploaded file
- Extracts text
- Creates overlapping chunks
- Generates embeddings
- Stores chunks in SQLite
- Stores vectors in ChromaDB
- Marks the document as processed

### 4. Build the Wiki

The Wiki compiler:

- Reads the processed chunks
- Sends grounded context to the LLM
- Generates structured Wiki pages
- Creates titles and summaries
- Produces Markdown content
- Stores page sources and links

### 5. Ask the Assistant

The Assistant:

- Embeds the user question
- Searches document chunks
- Searches Wiki knowledge
- Builds a grounded context
- Requests an LLM-generated answer
- Returns the answer with sources and citations

---

## Local Installation

### Prerequisites

Install:

- Python 3.12
- Node.js 20 or later
- npm
- Git
- An OpenRouter API key

---

### 1. Clone the repository

```bash
git clone \
https://github.com/AfroditiTzama/Enterprise-AI_Knowledge.git

cd Enterprise-AI_Knowledge
```

---

### 2. Configure the backend

```bash
cd apps/api

python3.12 -m venv .venv

source .venv/bin/activate

python -m pip install --upgrade pip

pip install -e .
```

---

### 3. Create the backend environment file

Create:

```text
apps/api/.env
```

Example:

```env
APP_ENV=development
APP_DEBUG=false

DATABASE_URL=sqlite+aiosqlite:///./knowledge_assistant.db

DOCUMENTS_STORAGE_DIRECTORY=storage/documents
DOCUMENT_MAX_UPLOAD_BYTES=26214400
DOCUMENT_UPLOAD_CHUNK_BYTES=1048576
DOCUMENT_MAX_PDF_PAGES=500
DOCUMENT_MAX_EXTRACTED_TEXT_CHARACTERS=5000000
DOCUMENT_MAX_DOCX_UNCOMPRESSED_BYTES=104857600
DOCUMENT_MAX_DOCX_ARCHIVE_ENTRIES=2048
DOCUMENT_MAX_DOCX_COMPRESSION_RATIO=100
CHROMA_STORAGE_DIRECTORY=storage/chroma

# This placeholder is rejected at startup. Replace it using the command below.
JWT_SECRET_KEY=replace-with-a-secret-of-at-least-32-characters
JWT_ALGORITHM=HS256

ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

OPENROUTER_API_KEY=replace-with-your-openrouter-api-key
OPENROUTER_MODEL=google/gemini-2.5-flash

CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Leave empty for direct local connections. Configure only known reverse proxies.
TRUSTED_PROXY_CIDRS=
```

Do not commit the `.env` file.

The document limits above default to a 25 MiB upload, 500 PDF pages,
5,000,000 extracted characters, and 100 MiB of decompressed DOCX content.
DOCX archives are also limited to 2,048 entries and a 100:1 per-entry
compression ratio. The API reads multipart uploads in bounded 1 MiB chunks
and returns HTTP 413 when the upload limit is exceeded.

Generate a JWT secret with:

```bash
openssl rand -hex 32
```

---

### 4. Run database migrations

From `apps/api`:

```bash
alembic upgrade head
```

---

### 5. Start the backend

```bash
uvicorn knowledge_assistant.main:app \
  --reload \
  --no-proxy-headers \
  --host 127.0.0.1 \
  --port 8000
```

The authentication rate limiter stores a bounded set of counters in each API
process. It is suitable for local and single-process deployments, but it is not
a shared distributed limiter. Multi-process or multi-instance deployments need
a shared limiter in a future deployment phase. Forwarded client IPs are used
only when the immediate peer matches `TRUSTED_PROXY_CIDRS`; keep it empty for
direct connections and list only proxy IP addresses or CIDR ranges you control.

The API will be available at:

```text
http://127.0.0.1:8000
```

Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

---

### 6. Configure the frontend

Open another terminal:

```bash
cd apps/web

npm install
```

Create:

```text
apps/web/.env
```

Add:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

---

### 7. Start the frontend

```bash
npm run dev
```

Open:

```text
http://localhost:5173
```

---

## Production Build

### Backend checks

```bash
cd apps/api

source .venv/bin/activate

python -m compileall src

alembic upgrade head
```

### Frontend build

```bash
cd apps/web

npm install

npm run build
```

The frontend production output is created in:

```text
apps/web/dist
```

---

## Docker

The backend includes a Dockerfile based on Python 3.12.

### Build the backend image

From the repository root:

```bash
docker build \
  -t enterprise-ai-knowledge-api \
  apps/api
```

### Run the container

```bash
docker run \
  --env-file apps/api/.env \
  -p 8000:8000 \
  enterprise-ai-knowledge-api
```

### Run with persistent storage

```bash
docker run \
  --env-file apps/api/.env \
  -p 8000:8000 \
  -v knowledge-ai-data:/data \
  enterprise-ai-knowledge-api
```

---

## Data Persistence

The system stores different types of application data.

| Data | Storage |
|---|---|
| Users | SQLite |
| Authentication data | SQLite |
| Document metadata | SQLite |
| Document processing status | SQLite |
| Extracted text chunks | SQLite |
| Wiki pages | SQLite |
| Wiki sources | SQLite |
| Wiki links | SQLite |
| Uploaded files | Filesystem |
| Semantic vectors | ChromaDB |

Production deployments require persistent storage for:

```text
/data/knowledge_assistant.db
/data/storage/documents
/data/storage/chroma
```

---

## Deployment

### Frontend

The React frontend is deployed on Vercel.

Production URL:

```text
https://enterprise-ai-knowledge.vercel.app
```

Vercel configuration:

```text
Root Directory: apps/web
Framework Preset: Vite
Build Command: npm run build
Output Directory: dist
```

Frontend production variable:

```env
VITE_API_BASE_URL=https://your-backend-domain
```

The project includes `vercel.json` for React Router SPA rewrites.

### Backend

The backend includes a production Dockerfile and can be deployed to any platform supporting:

- Docker
- Persistent volumes
- Environment variables
- At least approximately 2 GB of memory for the complete local embedding stack

The backend was tested with Railway deployment and persistent volume storage.

### Cloud Memory Note

The Sentence Transformer, PyTorch, ChromaDB, FastAPI, and application dependencies can exceed the memory limit of small free cloud instances.

For that reason, the complete AI pipeline is most reliable when:

- Run locally
- Deployed to a service with sufficient memory
- Or adapted to use an external embedding API

---

## Security

The project includes the following security practices:

- Argon2 password hashing
- JWT access tokens
- Protected API routes
- Owner-based document filtering
- Owner-based Wiki filtering
- Owner-based vector search
- Secrets loaded from environment variables
- No API keys in the frontend
- No secrets committed to Git
- Storage path validation
- Persistent data excluded from Git
- Uploaded files excluded from Git
- ChromaDB files excluded from Git
- SQLite database files excluded from Git
- CORS origin configuration

---

## Error Handling

The application handles:

- Invalid login credentials
- Duplicate registrations
- Unauthorized requests
- Missing documents
- Unsupported file types
- Failed text extraction
- Empty extracted documents
- Processing failures
- Embedding failures
- Vector-store failures
- Wiki compilation failures
- OpenRouter request errors
- Invalid LLM output
- Network failures
- Frontend validation errors

Documents can have one of the following statuses:

```text
UPLOADED
PROCESSING
PROCESSED
FAILED
```
