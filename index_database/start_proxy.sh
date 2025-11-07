#!/bin/bash

# Madison County Title Plant - Cloud SQL Auth Proxy Helper Script
# Starts the Cloud SQL Auth Proxy for local database connections

set -e  # Exit on error

# ============================================================================
# Configuration
# ============================================================================

PROJECT_ID="madison-county-title-plant"
REGION="us-south1"
INSTANCE_NAME="madison-county-title-plant"
CONNECTION_NAME="$PROJECT_ID:$REGION:$INSTANCE_NAME"

# Proxy configuration
PROXY_BINARY="./cloud-sql-proxy"
PROXY_PORT=5432
LOG_FILE="./cloud-sql-proxy.log"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
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

check_proxy_binary() {
    if [ ! -f "$PROXY_BINARY" ]; then
        print_error "Cloud SQL Auth Proxy not found at $PROXY_BINARY"
        echo ""
        echo "To download the proxy, run:"
        echo "  curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.19.0/cloud-sql-proxy.linux.amd64"
        echo "  chmod +x cloud-sql-proxy"
        echo ""
        exit 1
    fi
}

check_authentication() {
    print_step "Checking gcloud authentication..."

    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
        print_error "Not authenticated with gcloud"
        echo ""
        echo "Please run one of:"
        echo "  gcloud auth login                        # For user credentials"
        echo "  gcloud auth application-default login    # For application default credentials"
        echo ""
        exit 1
    fi

    # Check if ADC is set up
    if [ ! -f "$HOME/.config/gcloud/application_default_credentials.json" ]; then
        print_warning "Application Default Credentials (ADC) not found"
        echo ""
        echo "The proxy will use your user credentials, but for production,"
        echo "it's recommended to set up ADC:"
        echo "  gcloud auth application-default login"
        echo ""
    fi

    print_step "Authentication check passed ✓"
}

check_existing_proxy() {
    # Check if proxy is already running
    if lsof -Pi :$PROXY_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        print_warning "Port $PROXY_PORT is already in use"
        echo ""
        echo "A proxy or database server may already be running."
        echo "To stop existing processes:"
        echo "  pkill -f cloud-sql-proxy"
        echo ""
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 0
        fi
    fi
}

start_proxy() {
    print_step "Starting Cloud SQL Auth Proxy..."
    echo ""
    echo "Connection: $CONNECTION_NAME"
    echo "Port:       $PROXY_PORT"
    echo "Log file:   $LOG_FILE"
    echo ""

    # Start proxy in background with logging
    $PROXY_BINARY "$CONNECTION_NAME" \
        --port=$PROXY_PORT \
        > "$LOG_FILE" 2>&1 &

    PROXY_PID=$!

    # Wait a moment for startup
    sleep 2

    # Check if proxy is running
    if kill -0 $PROXY_PID 2>/dev/null; then
        print_step "Cloud SQL Auth Proxy started successfully! ✓"
        echo ""
        echo "PID: $PROXY_PID"
        echo ""
        echo "Connection details for your application:"
        echo "  Host:     127.0.0.1"
        echo "  Port:     $PROXY_PORT"
        echo "  Database: madison_county_index"
        echo "  User:     madison_index_app (or postgres)"
        echo ""
        echo "To stop the proxy:"
        echo "  kill $PROXY_PID"
        echo "  # OR"
        echo "  pkill -f cloud-sql-proxy"
        echo ""
        echo "To view logs:"
        echo "  tail -f $LOG_FILE"
        echo ""

        # Save PID to file
        echo $PROXY_PID > .proxy.pid
    else
        print_error "Failed to start Cloud SQL Auth Proxy"
        echo ""
        echo "Check the log file for details:"
        echo "  cat $LOG_FILE"
        echo ""
        exit 1
    fi
}

display_test_connection() {
    echo "To test the connection:"
    echo ""
    echo "  # Using psql (if installed)"
    echo "  psql -h 127.0.0.1 -p $PROXY_PORT -U postgres -d madison_county_index"
    echo ""
    echo "  # Using Python"
    echo "  python3 -c \"import psycopg2; conn = psycopg2.connect(host='127.0.0.1', port=$PROXY_PORT, database='madison_county_index', user='postgres'); print('Connected!'); conn.close()\""
    echo ""
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    echo "============================================================================"
    echo "Madison County Title Plant - Cloud SQL Auth Proxy"
    echo "============================================================================"
    echo ""

    check_proxy_binary
    check_authentication
    check_existing_proxy
    start_proxy
    display_test_connection
}

# Run main function
main
