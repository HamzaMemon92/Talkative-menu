# Talkative Menu

An India-first intelligent restaurant platform featuring **“Talk to the Menu”** for customers and **“Talk to the Restaurant”** for managers and owners, powered by local LLM and speech-to-text inference.

---

## Repository Structure

```text
talkative menu/
├── ainza-restaurant-ai-backend/   # Core FastAPI backend, Chainlit UI, database & AI pipelines
│   ├── src/ainza_restaurant/      # Application source code (AI, API, models, services)
│   ├── ui/                        # Chainlit UI application
│   ├── tests/                     # Unit, integration, and E2E test suites
│   ├── migrations/                # Alembic database migrations
│   └── scripts/                   # Local service launchers and utilities
├── models/                        # Local AI model weights (GGUF & Whisper)
└── runtimes/                      # Local inference runtimes (llama.cpp, whisper.cpp)
```

---

## Features

- **Talk to the Menu**: Conversational AI customer assistant capable of answering dish queries, dietary preferences, ingredients, and specials in natural language and Hinglish.
- **Dynamic Catalog & Availability**: Real-time availability tracking, specials, and merchandising.
- **Table QR & Multi-round Ordering**: QR-based table sessions, carts, and kitchen tickets (KOT).
- **Billing & Invoice Snapshots**: Deterministic bill calculation and checkout preview.
- **Local Privacy-First AI**: Runs locally using quantized GGUF LLMs (`llama.cpp`) and Whisper (`whisper.cpp`).

---

## Quickstart

### 1. Prerequisites

- Python 3.12+
- Docker & Docker Compose (for PostgreSQL)

### 2. Setup Environment

```powershell
cd ainza-restaurant-ai-backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
Copy-Item .env.example .env
docker compose up -d db
```

### 3. Start the API & Services

```powershell
# Run backend API
uvicorn ainza_restaurant.main:app --reload

# Start the interactive UI
chainlit run ui/chainlit_app.py
```

---

## License

Proprietary / All rights reserved.
