# Index Database - Change Log

## 2025-11-06: Initial Setup and Folder Rename

### Changes Made

#### 1. Schema Validation ✅
- Reviewed DuProcess Excel files from **1985-2025** (9 samples across 40 years)
- **Result**: All files have identical **54-column schema**
- No schema changes needed - database design is compatible with all historical data

#### 2. Folder Renamed
- **Old**: `database/`
- **New**: `index_database/`
- **Reason**: Avoid confusion with production database (which will be built from OCR/AI processing)

#### 3. Dependencies Consolidated
- **Removed**: `index_database/requirements.txt` (duplicate)
- **Updated**: Main `/requirements.txt` with `psycopg2-binary==2.9.9`
- All Python dependencies now managed in single root requirements.txt

#### 4. File Updates
Updated all path references from `database/` to `index_database/`:
- ✅ `setup_index_database.sh`
- ✅ `import_index_data.py`
- ✅ `README.md`
- ✅ `QUICKSTART.md`

### Final Structure

```
madison-county-title-plant/
├── requirements.txt              # ← UPDATED (added psycopg2-binary)
│
└── index_database/               # ← RENAMED from "database/"
    ├── schema/
    │   └── index_database_schema.sql
    ├── setup_index_database.sh   # ← Path references updated
    ├── start_proxy.sh
    ├── import_index_data.py      # ← Path references updated
    ├── README.md                 # ← Path references updated
    ├── QUICKSTART.md             # ← Path references updated
    ├── .gitignore
    └── CHANGES.md                # ← This file
```

### What This Database Contains

**Index Database** (this database):
- Pre-existing DuProcess indexes (1985-2025)
- Historic Deeds checklist
- Download queue management
- Validation reference data

**Production Database** (separate, to be built later):
- OCR-extracted text
- AI-processed entities
- Parsed legal descriptions
- Title chains
- Will be validated against this index database

### Next Steps

To set up the index database:

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Download Cloud SQL Auth Proxy:
   ```bash
   cd index_database
   curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.19.0/cloud-sql-proxy.linux.amd64
   chmod +x cloud-sql-proxy
   ```

3. Create database:
   ```bash
   ./setup_index_database.sh
   ```

4. Import data:
   ```bash
   # Terminal 1
   ./start_proxy.sh

   # Terminal 2
   source .db_credentials
   python3 import_index_data.py
   ```

See `README.md` for complete documentation.
