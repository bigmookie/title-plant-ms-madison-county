#!/bin/bash

# Madison County Title Plant - Index Database Setup Script
# This script creates the index database in Google Cloud SQL and applies the schema

set -e  # Exit on error

# ============================================================================
# Configuration
# ============================================================================

PROJECT_ID="madison-county-title-plant"
REGION="us-south1"
INSTANCE_NAME="madison-county-title-plant"
DATABASE_NAME="madison_county_index"
SCHEMA_FILE="./schema/index_database_schema.sql"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# Helper Functions
# ============================================================================

print_step() {
    echo -e "${GREEN}==>${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}Warning:${NC} $1"
}

print_error() {
    echo -e "${RED}Error:${NC} $1"
}

check_prerequisites() {
    print_step "Checking prerequisites..."

    # Check if gcloud is installed
    if ! command -v gcloud &> /dev/null; then
        print_error "gcloud CLI is not installed. Please install it first:"
        echo "https://cloud.google.com/sdk/docs/install"
        exit 1
    fi

    # Check if authenticated
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
        print_error "Not authenticated with gcloud. Please run: gcloud auth login"
        exit 1
    fi

    # Check if schema file exists
    if [ ! -f "$SCHEMA_FILE" ]; then
        print_error "Schema file not found: $SCHEMA_FILE"
        exit 1
    fi

    print_step "Prerequisites check passed ✓"
}

set_project() {
    print_step "Setting active GCP project to $PROJECT_ID..."
    gcloud config set project "$PROJECT_ID"
}

check_instance() {
    print_step "Checking if Cloud SQL instance exists..."

    if gcloud sql instances describe "$INSTANCE_NAME" --format="value(name)" &> /dev/null; then
        print_step "Instance '$INSTANCE_NAME' found ✓"

        # Display instance info
        echo ""
        gcloud sql instances describe "$INSTANCE_NAME" \
            --format="table(name, databaseVersion, region, settings.tier, state)"
        echo ""
    else
        print_error "Instance '$INSTANCE_NAME' not found in project '$PROJECT_ID'"
        echo "Please verify the instance name and project ID."
        exit 1
    fi
}

create_database() {
    print_step "Creating database '$DATABASE_NAME'..."

    # Check if database already exists
    if gcloud sql databases describe "$DATABASE_NAME" \
        --instance="$INSTANCE_NAME" \
        --format="value(name)" &> /dev/null 2>&1; then

        print_warning "Database '$DATABASE_NAME' already exists."
        read -p "Do you want to continue and apply schema? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_step "Exiting without changes."
            exit 0
        fi
    else
        # Create the database
        gcloud sql databases create "$DATABASE_NAME" \
            --instance="$INSTANCE_NAME" \
            --charset=UTF8

        print_step "Database '$DATABASE_NAME' created successfully ✓"
    fi
}

apply_schema() {
    print_step "Applying schema from $SCHEMA_FILE..."

    # Use gcloud sql connect to run the schema file
    # This will prompt for the postgres password
    echo ""
    print_warning "You will be prompted for the 'postgres' user password."
    echo "If you don't have it set, you can set/reset it with:"
    echo "  gcloud sql users set-password postgres --instance=$INSTANCE_NAME --password=YOUR_PASSWORD"
    echo ""

    # Connect and execute schema
    gcloud sql connect "$INSTANCE_NAME" \
        --user=postgres \
        --database="$DATABASE_NAME" \
        < "$SCHEMA_FILE"

    print_step "Schema applied successfully ✓"
}

create_app_user() {
    print_step "Setting up application user..."

    DB_USER="madison_index_app"

    # Check if user exists
    if gcloud sql users list --instance="$INSTANCE_NAME" \
        --format="value(name)" | grep -q "^${DB_USER}$"; then

        print_warning "User '$DB_USER' already exists."
    else
        # Generate a random password
        DB_PASSWORD=$(openssl rand -base64 32)

        # Create user
        gcloud sql users create "$DB_USER" \
            --instance="$INSTANCE_NAME" \
            --password="$DB_PASSWORD"

        print_step "User '$DB_USER' created ✓"

        # Save credentials to file (secure)
        CREDS_FILE="./.db_credentials"
        echo "export DB_USER=$DB_USER" > "$CREDS_FILE"
        echo "export DB_PASSWORD=$DB_PASSWORD" >> "$CREDS_FILE"
        chmod 600 "$CREDS_FILE"

        print_step "Credentials saved to $CREDS_FILE (keep this secure!)"
    fi

    # Grant permissions
    print_step "Granting permissions to '$DB_USER'..."

    GRANT_SQL="
    GRANT ALL PRIVILEGES ON DATABASE $DATABASE_NAME TO $DB_USER;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_USER;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;
    GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO $DB_USER;
    "

    echo "$GRANT_SQL" | gcloud sql connect "$INSTANCE_NAME" \
        --user=postgres \
        --database="$DATABASE_NAME"

    print_step "Permissions granted ✓"
}

display_connection_info() {
    print_step "Setup complete! 🎉"
    echo ""
    echo "============================================================================"
    echo "Connection Information"
    echo "============================================================================"
    echo "Project:        $PROJECT_ID"
    echo "Instance:       $INSTANCE_NAME"
    echo "Region:         $REGION"
    echo "Database:       $DATABASE_NAME"
    echo "Connection:     $PROJECT_ID:$REGION:$INSTANCE_NAME"
    echo ""
    echo "To connect via Cloud SQL Auth Proxy:"
    echo ""
    echo "  1. Download proxy (if not already done):"
    echo "     curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.19.0/cloud-sql-proxy.linux.amd64"
    echo "     chmod +x cloud-sql-proxy"
    echo ""
    echo "  2. Start proxy:"
    echo "     ./cloud-sql-proxy $PROJECT_ID:$REGION:$INSTANCE_NAME"
    echo ""
    echo "  3. Connect from application:"
    echo "     Host: 127.0.0.1"
    echo "     Port: 5432"
    echo "     Database: $DATABASE_NAME"
    echo "     User: madison_index_app (or postgres)"
    echo ""
    echo "To connect via gcloud CLI:"
    echo "  gcloud sql connect $INSTANCE_NAME --user=postgres --database=$DATABASE_NAME"
    echo ""
    echo "============================================================================"
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    echo "============================================================================"
    echo "Madison County Title Plant - Index Database Setup"
    echo "============================================================================"
    echo ""

    check_prerequisites
    set_project
    check_instance
    create_database
    apply_schema
    create_app_user
    display_connection_info
}

# Run main function
main
