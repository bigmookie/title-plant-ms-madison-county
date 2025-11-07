# Index Database - Quick Start Guide

> **What is this?** This is the **Index Database** that stores pre-existing DuProcess indexes and Historic Deeds data. It's separate from the production database and used for download queue management and validation.

## 🚀 Setup (First Time Only)

### 1. Install Dependencies
```bash
# From project root directory
cd /path/to/title-plant-ms-madison-county
pip install -r requirements.txt
```

### 2. Download Cloud SQL Auth Proxy
```bash
# Navigate to index_database folder
cd index_database

# Download proxy
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.19.0/cloud-sql-proxy.linux.amd64
chmod +x cloud-sql-proxy
```

### 3. Install PostgreSQL Client (Required for Schema Setup)
```bash
# Update package list
sudo apt update

# Install PostgreSQL client
sudo apt install postgresql-client -y

# Verify installation
psql --version
```

### 4. Authenticate with Google Cloud
```bash
gcloud auth login --no-browser
gcloud components update
gcloud auth application-default login --no-browser
gcloud config set project madison-county-title-plant
```

### 5. Enable Cloud SQL Admin API
```bash
# This is required for the setup script to work
gcloud services enable sqladmin.googleapis.com --project=madison-county-title-plant
```
**Note**: This takes 1-2 minutes. Wait for "Operation finished successfully."

### 6. Set PostgreSQL Password (if not already set)
```bash
# Set a secure password for the postgres user
gcloud sql users set-password postgres \
  --instance=madison-county-title-plant \
  --prompt-for-password
```
**Remember this password** - you'll need it in the next step!

### 7. Create Database & Apply Schema
```bash
# Make sure you're in index_database/ folder
./setup_index_database.sh
```
**⚠️ Important**:
- You'll be prompted for the postgres password you just set
- Save the credentials displayed at the end to `.db_credentials` file!

---

## 📊 Daily Usage

### Import All Index Data (One-time Process)

**Terminal 1** (keep running):
```bash
cd index_database
./start_proxy.sh
```

**Terminal 2** (run import):
```bash
cd index_database
source .db_credentials
python3 import_index_data.py
```

**Expected Runtime**: 30-60 minutes to import ~1 million records from 1000+ Excel files.

### Connect to Database

```bash
# Via psql (after proxy is running)
psql -h 127.0.0.1 -p 5432 -U madison_index_app -d madison_county_index

# Via gcloud (direct connection, no proxy needed)
gcloud sql connect madison-county-title-plant --user=postgres --database=madison_county_index
```

---

## 📈 Useful Queries

### Check Import Status
```sql
SELECT source, COUNT(*) as count
FROM index_documents
GROUP BY source;

-- Expected output:
--   DuProcess  | ~1,000,000
--   Historical | ~100,000
```

### View Download Queue Summary
```sql
SELECT * FROM download_queue_summary;
```

### Find Pending Downloads (for document downloader)
```sql
SELECT book, page, instrument_type_parsed
FROM index_documents
WHERE download_status = 'pending'
ORDER BY book, page
LIMIT 100;
```

### Search by Party Name
```sql
SELECT book, page, grantor_party, grantee_party, file_date
FROM index_documents
WHERE grantor_party ILIKE '%SMITH%'
   OR grantee_party ILIKE '%SMITH%'
ORDER BY file_date DESC
LIMIT 20;
```

### Document Type Distribution
```sql
SELECT document_type, COUNT(*) as count
FROM index_documents
WHERE document_type IS NOT NULL
GROUP BY document_type
ORDER BY count DESC
LIMIT 20;
```

### Find Documents by Book Range
```sql
SELECT book, page, instrument_type_parsed, file_date
FROM index_documents
WHERE book BETWEEN 3000 AND 3100
  AND download_status = 'pending'
ORDER BY book, page
LIMIT 50;
```

---

## 🛑 Stopping the Proxy

```bash
# Kill by saved PID
kill $(cat .proxy.pid)

# Or kill all proxies
pkill -f cloud-sql-proxy
```

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| **"required file not found" on .sh script** | Windows line endings issue. Fix: `sed -i 's/\r$//' *.sh` |
| **"Psql client not found"** | Install PostgreSQL client: `sudo apt install postgresql-client -y` |
| **"API not enabled" or script hangs** | Enable Cloud SQL Admin API: `gcloud services enable sqladmin.googleapis.com --project=madison-county-title-plant` |
| **Can't connect to database** | 1. Check proxy is running: `ps aux \| grep cloud-sql-proxy`<br>2. Check logs: `tail -f cloud-sql-proxy.log`<br>3. Restart proxy: `pkill -f cloud-sql-proxy && ./start_proxy.sh` |
| **Permission denied** | Re-run setup script: `./setup_index_database.sh` |
| **Import script fails** | 1. Check logs: `tail -f index_import.log`<br>2. Verify Excel files exist in `madison_docs/DuProcess Indexes/`<br>3. Check database connection: test with psql |
| **Port 5432 in use** | Stop existing proxy: `pkill -f cloud-sql-proxy` |
| **Module not found (Python)** | Install dependencies: `cd .. && pip install -r requirements.txt` |
| **Excel file errors** | Some files may be empty (0 rows) - this is normal, script handles it |
| **Forgot postgres password** | Reset it: `gcloud sql users set-password postgres --instance=madison-county-title-plant --prompt-for-password` |

---

## 📁 File Locations

```
index_database/
├── .db_credentials          # Database credentials (created by setup script)
├── .last_import_time       # Timestamp of last import (for auto-updates)
├── .proxy.pid              # Proxy process ID (created when proxy starts)
├── cloud-sql-proxy         # Proxy binary (download with setup steps)
├── cloud-sql-proxy.log     # Proxy logs
├── index_import.log        # Import script logs
├── index_update.log        # Update script logs
│
├── schema/
│   └── index_database_schema.sql
│
├── setup_index_database.sh
├── start_proxy.sh
├── import_index_data.py    # Initial import of all data
├── update_index_data.py    # Incremental updates with new files
├── README.md               # Full documentation
└── QUICKSTART.md           # This file
```

---

## 📞 Quick Help Commands

```bash
# View real-time logs
tail -f cloud-sql-proxy.log
tail -f index_import.log

# Test database connection (Python)
python3 -c "import psycopg2; conn = psycopg2.connect(host='127.0.0.1', port=5432, database='madison_county_index', user='postgres'); print('✅ Connected!'); conn.close()"

# Check database size in Cloud SQL
gcloud sql instances describe madison-county-title-plant --format="value(settings.dataDiskSizeGb)"

# List all databases in instance
gcloud sql databases list --instance=madison-county-title-plant

# Check proxy status
ps aux | grep cloud-sql-proxy

# Verify import progress (from psql)
SELECT COUNT(*) FROM index_documents;
```

---

## 🎯 Common Workflows

### First-Time Setup (Complete Flow)
```bash
# 1. Install Python dependencies
cd /path/to/title-plant-ms-madison-county
pip install -r requirements.txt

# 2. Install PostgreSQL client (required)
sudo apt update
sudo apt install postgresql-client -y
psql --version  # Verify installation

# 3. Set up Cloud SQL Auth Proxy
cd index_database
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.19.0/cloud-sql-proxy.linux.amd64
chmod +x cloud-sql-proxy

# 4. Authenticate with Google Cloud
gcloud auth login --no-browser
gcloud components update
gcloud auth application-default login --no-browser
gcloud config set project madison-county-title-plant

# 5. Enable required APIs
gcloud services enable sqladmin.googleapis.com --project=madison-county-title-plant
# Wait for "Operation finished successfully" (~1-2 minutes)

# 6. Set postgres password (if not already set)
gcloud sql users set-password postgres \
  --instance=madison-county-title-plant \
  --prompt-for-password
# Remember this password!

# 7. Create database and apply schema
./setup_index_database.sh
# Enter postgres password when prompted
# Save the credentials displayed at the end!

# 8. Import data (in new terminal session)
# Terminal 1: Start proxy
./start_proxy.sh

# Terminal 2: Run import
source .db_credentials
python3 import_index_data.py
# This takes 30-60 minutes for ~1 million records
```

### Query Documents (After Import)
```bash
# Start proxy if not running
cd index_database
./start_proxy.sh

# Connect via psql
psql -h 127.0.0.1 -p 5432 -U madison_index_app -d madison_county_index

# Run your queries...
```

### Update with New Files
```bash
# Import specific file
cd index_database
source .db_credentials
python3 update_index_data.py --file "madison_docs/DuProcess Indexes/2025-04-01.xlsx"

# Import files matching pattern
python3 update_index_data.py --pattern "2025-04-*.xlsx"

# Auto-import all new files (based on modification time)
python3 update_index_data.py --auto

# Dry run to preview changes
python3 update_index_data.py --auto --dry-run
```

### Re-import Data (if needed)
```bash
# This will skip existing records due to ON CONFLICT handling
cd index_database
source .db_credentials
python3 import_index_data.py
```

---

## 📚 Full Documentation

See [README.md](README.md) for:
- Complete architecture overview
- Detailed schema documentation
- Integration with document downloader
- Production database validation strategy
- Security best practices
- Backup and restore procedures

---

## ⚡ Quick Reference

**Database**: `madison_county_index`
**Instance**: `madison-county-title-plant`
**Region**: `us-south1`
**Table**: `index_documents` (1M+ rows)
**Sources**: DuProcess (1985-2025) + Historic Deeds
**Purpose**: Download queue + Validation reference
