# OpenCart Product Pipeline & Huppa Studio

An end-to-end data pipeline, AI enrichment suite, and weekly inventory synchronization system built for OpenCart ecommerce stores (specifically `huppa.com.ua`).

The system automates the ingestion of supplier price lists (Excel/CSV), normalizes disparate product schemas, aggregates variants into parent-child entities, generates dual-language (Ukrainian & Russian) SEO content using LLMs, resolves image galleries, and synchronizes stock levels and prices directly to MySQL/MariaDB or via SQL migration scripts.

---

## Key Features

- **Supplier Adapters (`adapters/`)**
  - **Huppa Adapter:** Ingests complex Huppa Excel catalogs with multi-level codes, size ranges, temperatures, and materials.
  - **Reima Adapter:** Normalizes Reima inventory sheets into standard canonical schemas.
  - **Auto-Detection Registry:** Automatically selects the correct parser based on spreadsheet column signatures.

- **Entity Aggregation (`core/aggregator.py`)**
  - Groups individual variant rows (SKUs) into unified `ParentProduct` models by model code and color.
  - Normalizes prices, stock quantities, barcodes, and OpenCart option values.

- **AI Copywriting & Enrichment (`core/enrichment_graph.py`, `core/copywriter.py`)**
  - Dual-agent LangGraph workflow powered by OpenAI.
  - Produces compliant Ukrainian and Russian store titles, HTML product descriptions, meta titles, meta descriptions, and keywords.
  - Automatically extracts and maps product attributes (season, material, temperature limits, gender) to OpenCart filter structures.

- **Weekly Stock & Price Sync (`sync_weekly.py`)**
  - Compares fresh supplier spreadsheets against existing store data.
  - Detects price increases/decreases, stock level changes, newly introduced items, and discontinued products.
  - Generates patch reports and applies updates directly to the OpenCart database.

- **Direct Database Execution (`core/db_sync_executor.py`)**
  - Transaction-safe database execution for OpenCart MySQL/MariaDB databases.
  - Updates `oc_product`, `oc_product_option_value`, and special pricing tables.
  - Built-in connection testing and error reporting.

- **Automated Cache Backups (`core/cache_backup.py`)**
  - Rotational backup system that stores up to the 10 most recent cache snapshots.
  - Automatically tags backups with ISO timestamps and operation types (baseline, weekly sync, manual).
  - One-click restore available directly from the web interface.

- **Image Management & SFTP Audit (`core/image_resolver.py`, `core/photo_uploader.py`)**
  - Matches disk images (`opencart_images/`) to product SKUs and model colors.
  - Generates `oc_product_image` gallery entries.
  - Remote SFTP auditing and batch image upload utilities.

- **Streamlit Web Dashboard (`app.py`)**
  - Interactive UI for uploading supplier files, reviewing inventory diffs, inspecting cache backups, and triggering synchronization.

---

## Repository Structure

```text
pipeline_opencart/
├── app.py                      # Streamlit interactive dashboard
├── sync_weekly.py              # Weekly catalog synchronization engine
├── run_batch_pipeline.py       # CLI batch processing & AI enrichment pipeline
├── start_app.bat               # Windows 1-click launcher (auto-installs Python & venv)
├── requirements.txt            # Python package dependencies
├── .env.example                # Template for environment configuration
├── .gitignore                  # Git exclusions (credentials, large caches, media)
├── adapters/                   # Supplier-specific spreadsheet parsers
│   ├── base.py                 # Abstract BaseAdapter interface
│   ├── huppa.py                # Huppa Excel catalog adapter
│   ├── reima.py                # Reima catalog adapter
│   └── registry.py             # Automatic parser registry
├── core/                       # Core pipeline modules
│   ├── aggregator.py           # SKU-to-parent entity aggregation
│   ├── cache_backup.py         # 10-slot rotational backup manager
│   ├── category_matcher.py     # OpenCart category tree matching
│   ├── copywriter.py           # Async LLM copywriting engine
│   ├── db_sync_executor.py     # MySQL/MariaDB sync runner
│   ├── enrichment_graph.py     # LangGraph dual-agent workflow
│   ├── graph_schemas.py        # LangGraph state definitions
│   ├── image_resolver.py       # Local image matching engine
│   ├── models.py               # Pydantic data schemas
│   ├── photo_uploader.py       # SFTP photo uploader
│   ├── sftp_auditor.py         # Remote image verification
│   └── sql_exporter.py         # OpenCart SQL migration generator
├── data/                       # Working datasets & cache
│   ├── enriched_cache.jsonl    # Active enriched product cache
│   └── cache_backups/          # Automated cache backup archive
├── tests/                      # Integration and pipeline tests
│   ├── test_adapters.py        # Adapter normalization verification
│   ├── test_batch_enrich.py    # Batch LLM enrichment test
│   ├── test_dual_enrich.py     # Dual-language generation test
│   ├── test_five_items.py      # End-to-end multi-category sample test
│   ├── test_pipeline.py        # Aggregation pipeline test
│   ├── test_single_item.py     # Single SKU end-to-end test
│   └── test_sql_export.py      # SQL export verification
├── tools/                      # Diagnostic and catalog inspection utilities
│   ├── check_catalog_colors.py # Color mapping & DB consistency check
│   ├── check_catalog_photos.py # Photo coverage audit
│   ├── check_catalog_sizes.py  # Size option mapping check
│   ├── check_missing_photos.py # Missing image diagnostics
│   ├── download_images.py      # Batch photo downloader from image bank
│   └── image_insertion_sql_generator.py # Image SQL generator
└── extra/                      # Auxiliary files, XML modifiers, and scratch scripts
```

---

## Installation & Setup

### Prerequisites
- Python 3.10, 3.11, or 3.12
- MySQL or MariaDB instance (OpenCart 3.x)
- OpenAI API Key (optional, required only for generating new AI descriptions)

### 1. Clone the Repository
```bash
git clone https://github.com/OliverNicks/huppa-studio.git
cd huppa-studio
```

### 2. Configure Environment Variables
Copy the template file to `.env`:
```bash
copy .env.example .env
```
Edit `.env` and fill in your credentials:
```ini
# OpenAI API Key
OPENAI_API_KEY=your_openai_api_key_here

# OpenCart Database Connection
DB_HOST=your_db_host
DB_PORT=3306
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASS=your_db_password
DB_PREFIX=oc_

# Remote SFTP (Optional, for image uploads)
MIROHOST_SFTP_HOST=your_sftp_host
MIROHOST_SFTP_PORT=21
MIROHOST_SFTP_USER=your_sftp_user
MIROHOST_SFTP_PASS=your_sftp_password
MIROHOST_SFTP_DIR=image/catalog/product
```

### 3. Install Dependencies
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

## Running the Application

### Option A: Windows 1-Click Launcher
Double-click `start_app.bat`.  
On a fresh Windows machine without Python, the script will automatically download official Python 3.11, set up the virtual environment, install requirements, and open the Streamlit interface in your browser.

### Option B: Docker & Docker Compose (Recommended for isolated deployment)
Ensure Docker is installed and running, then:
```bash
# Build and start container in background
docker compose up -d

# View logs
docker compose logs -f

# Stop container
docker compose down
```
Open `http://localhost:8501` in your browser. Data and outputs are mounted to `./data` and `./output` on the host machine.

### Option C: Manual Command Line
Activate your virtual environment and start Streamlit:
```bash
streamlit run app.py
```
Open `http://localhost:8501` in your browser.

---

## Command-Line Usage

### Weekly Inventory Synchronization
Run comparison analysis or apply updates directly from the CLI:
```bash
python sync_weekly.py --help
```

### Batch AI Enrichment & SQL Migration
Process large catalogs with rate-limiting and intermediate checkpoints:
```bash
python run_batch_pipeline.py --catalog data/huppa.xlsx --batch-size 50 --concurrency 5
```

### Diagnostic Tools
Inspect catalog mappings before applying updates:
```bash
# Check size coverage against database options
python tools/check_catalog_sizes.py

# Check color names against existing OpenCart values
python tools/check_catalog_colors.py

# Audit photo coverage across catalog rows
python tools/check_catalog_photos.py
```

### Running Tests
Verify adapter parsing and data models:
```bash
python tests/test_adapters.py
python tests/test_single_item.py
```
