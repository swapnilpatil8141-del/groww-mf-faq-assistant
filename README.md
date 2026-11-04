# Groww Mutual Fund Facts-Only FAQ Assistant

A RAG prototype that answers factual questions using only the five approved Groww pages listed in `config/config.yaml`.

## Phase 1 status

- Project directory and folders created.
- Configuration and environment-variable template added.
- Configuration loader and validation added.
- Pipeline modules will be implemented in subsequent phases.

## Setup

### 1. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure the API key

Copy `.env.example` to `.env` and add your own Groq API key:

```text
GROQ_API_KEY=your_actual_key
```

Do not commit `.env` or share the key.

### 4. Verify Phase 1

```bash
python -m app.main
```

Expected output:

```text
Groww Mutual Fund Facts-Only FAQ Assistant
Configuration loaded successfully. Approved sources: 5
```

## Scope guardrails

- Only the five configured source URLs are approved.
- Internal links must not be crawled.
- Do not provide investment advice or personalized recommendations.
- Do not enter or store personal/account information.


## Phase 2 — Scrape approved source pages

Run from the project root after installing dependencies:

```bash
python -m app.scraper
```

The scraper fetches exactly the five URLs in `config/config.yaml`, after
checking them against a fixed allowlist in `app/scraper.py`. It disables
redirects and does not extract, discover, or follow page links.

Successful raw HTML files and `source_metadata.json` are written to `data/raw/`.
Failed requests are recorded and do not stop the remaining approved URLs.

Run the scraper tests with:

```bash
pytest -q
```


## Phase 3 — Load scraped documents

Run this only after Phase 2 has produced `data/raw/source_metadata.json` and
the raw HTML files:

```bash
python -m app.loader
```

The loader reads local files only. It does not make HTTP requests, parse or
clean HTML, or discover/follow links. It accepts only successful records for
the five hard-coded approved source IDs and exact URLs.

Outputs:

- `data/loaded/loaded_documents.jsonl` — one standardized document object per
  successfully loaded page. `page_content` contains the raw HTML at this stage.
  `metadata` contains source ID, title, URL, fetch timestamp, HTTP status,
  content hash, raw file reference, and load timestamp.
- `data/loaded/load_report.json` — counts and reasons for skipped sources.

Run all tests with:

```bash
pytest -q
```


## Phase 4 — Parse documents and create chunks

Run these commands in order, after Phase 3 has generated the loaded document
JSONL file:

```bash
python -m app.parser
python -m app.chunker
```

`app.parser` extracts semantic content from the saved HTML. It removes common
non-content elements (scripts, styles, navigation, footer, forms, etc.), keeps
headings, paragraphs, lists, and table rows, and writes section-aware records
to `data/parsed/parsed_documents.jsonl`.

`app.chunker` reads those parsed records and creates section-aware chunks in
`data/chunks/chunks.jsonl`. It keeps a heading with its content and keeps table
labels and values in the same block whenever possible. It does not combine
content from different source documents or sections.

Initial chunk configuration in `config/config.yaml`:

```yaml
chunking:
  max_chars: 1200
  overlap_chars: 0
```

These are starting settings, not final tuning values. Inspect the real parsed
pages and evaluate retrieval quality before changing chunk size or enabling
overlap. Character length is used for this first prototype; token-based tuning
can be considered after inspecting the actual content.

Outputs:
- `data/parsed/parsed_documents.jsonl`
- `data/parsed/parse_report.json`
- `data/chunks/chunks.jsonl`
- `data/chunks/chunk_report.json`

Run all tests with:

```bash
pytest -q
```


## Phase 5 — Generate embeddings

Run after Phase 4 has created `data/chunks/chunks.jsonl`:

```bash
python -m app.embeddings
```

The embedding module:
- Reads chunk text and metadata from the saved JSONL file.
- Uses the configured `sentence-transformers/all-MiniLM-L6-v2` model.
- Generates normalized vectors in batches.
- Preserves each vector's chunk ID and source metadata for ChromaDB.
- Writes `data/embeddings/embedding_manifest.json` with the model name,
  vector dimension, chunk IDs, checksums, and processing status.

The manifest intentionally does not duplicate the full vector arrays. The
`generate_embeddings()` function returns vector records in memory for Phase 6
to store in ChromaDB. Phase 6 should call this function or otherwise load
vectors using the same configured model and exact chunk IDs.

The first real run may download the sentence-transformers model. It requires
network access and enough local disk space. Later runs can reuse the cached
model. No embeddings should be generated from empty or missing chunk files.

Run all tests with:

```bash
pytest -q
```


## Phase 6 — Store vectors in ChromaDB

Run after Phase 5 has generated `data/embeddings/embedding_manifest.json`:

```bash
python -m app.vector_store
```

The vector-store stage:
- Reuses Phase 5's `generate_embeddings()` function when no in-memory
  embedding records are supplied, so it uses the same configured model.
- Creates/opens the persistent ChromaDB collection using
  `vector_db.persist_directory` and `vector_db.collection_name` in
  `config/config.yaml`.
- Stores each chunk's stable ID, text, embedding, and source metadata.
- Adds the embedding model name to each record and to collection metadata.
- Uses ChromaDB `upsert` with stable chunk IDs, so rerunning the stage updates
  existing records rather than creating duplicates.
- Rejects a collection tagged with a different embedding model. It also
  refuses to reuse a non-empty legacy collection that has no model metadata.
- Verifies a sample of stored IDs and writes an inspectable summary.

Outputs:
- Persistent ChromaDB files under `data/chroma/`.
- `data/embeddings/vector_store_manifest.json` — collection name, embedding
  model, vector dimension, upsert count, total collection count, source counts,
  and verified sample IDs.

Inspect the configured collection without running embeddings again:

```bash
python -m app.vector_store --inspect
```

Important:
- Keep `data/chunks/` and `data/embeddings/embedding_manifest.json`; ChromaDB
  is an additional searchable store, not the only copy of the pipeline data.
- Do not change the embedding model while reusing an existing collection.
  If you intentionally change models, use a new collection name or rebuild the
  collection from scratch.
- The first real run requires the `chromadb` dependency and a valid Phase 5
  chunk corpus. This development environment tests ChromaDB interactions with
  a deterministic in-memory test double; it does not claim a live persistent
  database was created here.

Run all tests with:

```bash
pytest -q
```


## Phase 7 — Retrieve evidence from ChromaDB

Run after Phase 6 has stored the vectors:

```bash
python -m app.retriever "What is the expense ratio of HDFC Large Cap Fund?"
```

You can also run it interactively:

```bash
python -m app.retriever
```

The retrieval module:
- Embeds the question using the same configured
  `sentence-transformers/all-MiniLM-L6-v2` model as ingestion.
- Opens the configured persistent ChromaDB collection and verifies its
  `embedding_model` metadata before querying.
- Uses `retrieval.top_k` (currently 4) and returns chunk ID, chunk text,
  source ID, source URL, scheme name/title, section, fetch timestamp,
  cosine distance, and a derived similarity score.
- Returns `status: no_evidence` when no records are available or all results
  are excluded by the optional distance threshold.
- Supports optional `retrieval.relevance_threshold` (cosine distance).
  It is `null` by default because a defensible cutoff must be tuned against
  real sample questions and the actual corpus.
- Appends a trace to `data/retrieval/retrieval_traces.jsonl`. Traces contain
  a generated/test trace ID and SHA-256 hash of the query, but deliberately
  do not store the raw question or other user-supplied text.

Example:

```json
{
  "status": "ok",
  "result_count": 4,
  "results": [
    {
      "chunk_id": "hdfc_large_cap_0001",
      "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
      "scheme_name": "HDFC Large Cap Fund Direct Growth",
      "distance": 0.18,
      "score": 0.82
    }
  ]
}
```

The numeric values above are illustrative only; actual results depend on the
locally ingested corpus and the embedding model. The similarity score is
`1 - cosine distance`, not a calibrated probability or confidence score.

Run all tests with:

```bash
pytest -q
```


## Phase 8 — LLM response generation, guardrails, and Streamlit UI

### Configure Groq

Copy `.env.example` to `.env` and set your own Groq API key:

```env
GROQ_API_KEY=your_actual_key
LLM_MODEL=qwen/qwen3.8-27b
```

The model ID can also be configured in `config/config.yaml`. The `.env`
value overrides the YAML value. The app checks the configured model against
the live model list returned by the Groq API before generating an answer.
The current default model is listed in Groq's supported-model documentation.

### Run the FAQ assistant

Make sure Phases 1–7 have completed successfully, including a populated
persistent ChromaDB collection. Then run:

```bash
streamlit run app/streamlit_app.py
```

### Phase 8 modules

- `app/llm/base.py` — provider-neutral interface.
- `app/llm/groq_provider.py` — Groq implementation and model health check.
- `app/llm/factory.py` — selects the configured provider.
- `app/guardrails.py` — PII, advice, scope, ambiguity, and response checks.
- `app/orchestrator.py` — coordinates classification, retrieval, generation,
  validation, and citation attachment.
- `app/streamlit_app.py` — chat interface with three sample questions,
  answer/source/date display, refusal/abstention messages, and retrieval trace
  details.

### Privacy and safety notes

- PII-bearing input is blocked before retrieval and is not added to Streamlit
  chat history. Do not enter PAN, Aadhaar, account numbers, OTPs, email
  addresses, or phone numbers.
- Retrieval traces store a SHA-256 query hash and result metadata, not the raw
  question. The hash is not a substitute for comprehensive privacy controls.
- Advice, buy/sell/hold, suitability, portfolio-allocation, and return-
  comparison requests are refused before retrieval.
- The model is instructed to use only retrieved evidence. The application
  attaches the citation from the selected retrieved source; model-supplied
  URLs are rejected.
- The validator enforces citation provenance, timestamp presence, a maximum
  of three sentences, and checks that numeric tokens appear in the supplied
  evidence. This is a conservative validation layer, not a guarantee of full
  semantic fact verification. Review real outputs before demo or production.

### Source-policy limitation

The current five configured URLs are on `groww.in`. The architecture document
states that factual answers should use official HDFC Mutual Fund, SEBI, or AMFI
sources and that Groww pages are discovery references only. The current
prototype preserves the five-page configuration already used by Phases 1–7
and displays this limitation in the UI; it does not silently claim Groww is an
official AMC/regulator source. Replace the source registry with verified
official URLs and re-run ingestion before treating the assistant as an
official-source-only product.

Run the complete test suite:

```bash
pytest -q
```
