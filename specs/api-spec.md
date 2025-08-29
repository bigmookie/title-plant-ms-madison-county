# API Design Specification

## Overview
This specification defines the RESTful API and GraphQL interfaces for the Madison County Title Plant system. The API provides programmatic access to title searches, document retrieval, and report generation capabilities.

## API Architecture

### Technology Stack
```python
API_STACK = {
    "framework": "FastAPI",  # Async Python framework
    "graphql": "Strawberry",  # GraphQL library
    "authentication": "OAuth2 with JWT",
    "rate_limiting": "Redis-based",
    "documentation": "OpenAPI 3.0 / Swagger",
    "versioning": "URL path versioning (/v1, /v2)",
    "caching": "Redis with CloudFlare CDN"
}
```

### Base Configuration
```python
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

app = FastAPI(
    title="Madison County Title Plant API",
    version="1.0.0",
    description="Comprehensive title search and document retrieval API",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://madison-title-plant.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
```

## Authentication & Authorization

### OAuth2 Implementation
```python
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext

class AuthenticationService:
    """Handle API authentication"""
    
    SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30
    REFRESH_TOKEN_EXPIRE_DAYS = 7
    
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    def create_access_token(self, data: dict) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
    
    def create_refresh_token(self, data: dict) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=self.REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
```

### API Key Authentication (Alternative)
```python
from fastapi.security import APIKeyHeader

class APIKeyAuth:
    """API key authentication for machine-to-machine access"""
    
    api_key_header = APIKeyHeader(name="X-API-Key")
    
    async def verify_api_key(self, api_key: str = Depends(api_key_header)):
        """Verify API key and return associated permissions"""
        key_data = await self.redis.get(f"api_key:{api_key}")
        
        if not key_data:
            raise HTTPException(
                status_code=403,
                detail="Invalid API key"
            )
        
        key_info = json.loads(key_data)
        
        # Check rate limits
        if not await self.check_rate_limit(api_key, key_info['rate_limit']):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded"
            )
        
        return key_info
```

### Permission Levels
```python
class PermissionLevel(Enum):
    READ_BASIC = "read:basic"  # Search, view summaries
    READ_FULL = "read:full"    # View full documents
    WRITE = "write"            # Create/update records
    ADMIN = "admin"            # Full system access

class Permissions:
    """Define API endpoint permissions"""
    
    ENDPOINT_PERMISSIONS = {
        "/api/v1/search": [PermissionLevel.READ_BASIC],
        "/api/v1/documents/{id}": [PermissionLevel.READ_FULL],
        "/api/v1/reports/generate": [PermissionLevel.READ_FULL],
        "/api/v1/admin/*": [PermissionLevel.ADMIN]
    }
```

## RESTful Endpoints

### Search Endpoints
```python
@app.get("/api/v1/search/properties")
async def search_properties(
    query: str = Query(None, description="Search query"),
    legal_description: str = Query(None, description="Legal description"),
    parcel_number: str = Query(None, description="Parcel number"),
    address: str = Query(None, description="Street address"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user)
) -> PropertySearchResponse:
    """
    Search for properties using various criteria
    
    Returns:
        List of matching properties with basic information
    """
    results = await property_search.search(
        query=query,
        legal_description=legal_description,
        parcel_number=parcel_number,
        address=address,
        limit=limit,
        offset=offset
    )
    
    return PropertySearchResponse(
        results=results,
        total=len(results),
        limit=limit,
        offset=offset
    )

@app.get("/api/v1/search/parties")
async def search_parties(
    name: str = Query(..., description="Party name to search"),
    fuzzy: bool = Query(True, description="Enable fuzzy matching"),
    party_type: Optional[PartyType] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user)
) -> PartySearchResponse:
    """
    Search for parties (individuals or organizations)
    
    Returns:
        List of matching parties with transaction summaries
    """
    results = await party_search.search(
        name=name,
        fuzzy=fuzzy,
        party_type=party_type,
        limit=limit
    )
    
    return PartySearchResponse(
        results=results,
        total=len(results),
        fuzzy_matching_used=fuzzy
    )

@app.get("/api/v1/search/documents")
async def search_documents(
    query: str = Query(..., description="Full-text search query"),
    document_types: List[DocumentType] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    book_from: Optional[int] = Query(None, ge=1),
    book_to: Optional[int] = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user)
) -> DocumentSearchResponse:
    """
    Full-text search across document content
    
    Returns:
        List of matching documents with highlighted excerpts
    """
    filters = SearchFilters(
        document_types=document_types,
        date_range=DateRange(date_from, date_to) if date_from else None,
        book_range=BookRange(book_from, book_to) if book_from else None
    )
    
    results = await document_search.search(
        query=query,
        filters=filters,
        limit=limit
    )
    
    return DocumentSearchResponse(
        results=results,
        total=len(results),
        query=query,
        filters=filters
    )
```

### Title Chain Endpoints
```python
@app.get("/api/v1/properties/{property_id}/chain")
async def get_title_chain(
    property_id: str = Path(..., description="Property ID"),
    start_date: Optional[date] = Query(None, description="Chain start date"),
    end_date: Optional[date] = Query(None, description="Chain end date"),
    include_gaps: bool = Query(True, description="Include gap analysis"),
    current_user: User = Depends(get_current_user)
) -> TitleChainResponse:
    """
    Retrieve complete title chain for a property
    
    Returns:
        Chronological list of transactions forming the title chain
    """
    chain = await chain_builder.build_chain(
        property_id=property_id,
        start_date=start_date,
        end_date=end_date
    )
    
    if include_gaps:
        chain.gaps = await gap_analyzer.analyze(chain)
    
    return TitleChainResponse(
        property_id=property_id,
        chain=chain,
        completeness_score=chain.completeness_score,
        gaps=chain.gaps if include_gaps else None
    )

@app.post("/api/v1/properties/{property_id}/chain/validate")
async def validate_title_chain(
    property_id: str = Path(..., description="Property ID"),
    validation_options: ChainValidationOptions = Body(...),
    current_user: User = Depends(get_current_user)
) -> ChainValidationResponse:
    """
    Validate title chain and identify issues
    
    Returns:
        Detailed validation report with identified issues
    """
    chain = await chain_builder.build_chain(property_id)
    validation = await chain_validator.validate(chain, validation_options)
    
    return ChainValidationResponse(
        property_id=property_id,
        is_valid=validation.is_valid,
        issues=validation.issues,
        recommendations=validation.recommendations
    )
```

### Document Endpoints
```python
@app.get("/api/v1/documents/{document_id}")
async def get_document(
    document_id: str = Path(..., description="Document ID"),
    include_ocr: bool = Query(False, description="Include OCR text"),
    current_user: User = Depends(get_current_user)
) -> DocumentResponse:
    """
    Retrieve document metadata and optionally OCR content
    
    Returns:
        Document details with optional OCR text
    """
    document = await document_service.get(document_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    response = DocumentResponse(
        document_id=document.document_id,
        book=document.book,
        page=document.page,
        document_type=document.document_type,
        recording_date=document.recording_date,
        status=document.status
    )
    
    if include_ocr and current_user.has_permission(PermissionLevel.READ_FULL):
        response.ocr_text = await ocr_service.get_text(document_id)
        response.ocr_confidence = document.ocr_confidence
    
    return response

@app.get("/api/v1/documents/{document_id}/download")
async def download_document(
    document_id: str = Path(..., description="Document ID"),
    format: str = Query("pdf", regex="^(pdf|txt)$"),
    current_user: User = Depends(get_current_user)
) -> FileResponse:
    """
    Download document file
    
    Returns:
        Document file in requested format
    """
    if not current_user.has_permission(PermissionLevel.READ_FULL):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    document = await document_service.get(document_id)
    
    if format == "pdf":
        file_path = await storage_service.get_document_path(document_id)
        return FileResponse(
            file_path,
            media_type="application/pdf",
            filename=f"{document_id}.pdf"
        )
    else:  # txt
        text = await ocr_service.get_text(document_id)
        return PlainTextResponse(
            content=text,
            headers={
                "Content-Disposition": f"attachment; filename={document_id}.txt"
            }
        )
```

### Report Generation Endpoints
```python
@app.post("/api/v1/reports/title")
async def generate_title_report(
    request: TitleReportRequest = Body(...),
    current_user: User = Depends(get_current_user)
) -> TitleReportResponse:
    """
    Generate comprehensive title report
    
    Returns:
        Complete title report with chain, encumbrances, and exceptions
    """
    report = await report_generator.generate_title_report(
        property_id=request.property_id,
        examination_period=request.examination_period,
        include_documents=request.include_documents
    )
    
    # Store report for later retrieval
    report_id = await report_storage.save(report)
    
    return TitleReportResponse(
        report_id=report_id,
        property=report.property,
        current_owner=report.current_owner,
        chain=report.chain,
        encumbrances=report.encumbrances,
        exceptions=report.exceptions,
        requirements=report.requirements,
        generated_at=datetime.utcnow()
    )

@app.get("/api/v1/reports/{report_id}/download")
async def download_report(
    report_id: str = Path(..., description="Report ID"),
    format: str = Query("pdf", regex="^(pdf|docx|html)$"),
    current_user: User = Depends(get_current_user)
) -> FileResponse:
    """
    Download generated report
    
    Returns:
        Report file in requested format
    """
    report = await report_storage.get(report_id)
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Check ownership or permissions
    if report.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")
    
    file_path = await report_formatter.format(report, format)
    
    return FileResponse(
        file_path,
        media_type=get_media_type(format),
        filename=f"title_report_{report_id}.{format}"
    )
```

## GraphQL Interface

### Schema Definition
```python
import strawberry
from strawberry.fastapi import GraphQLRouter

@strawberry.type
class Property:
    property_id: str
    property_type: str
    legal_description: str
    parcel_number: Optional[str]
    address: Optional[str]
    
    @strawberry.field
    async def transactions(self, limit: int = 10) -> List[Transaction]:
        return await get_property_transactions(self.property_id, limit)
    
    @strawberry.field
    async def current_owner(self) -> Optional[Party]:
        return await get_current_owner(self.property_id)
    
    @strawberry.field
    async def title_chain(self, 
                         start_date: Optional[datetime] = None) -> TitleChain:
        return await build_title_chain(self.property_id, start_date)

@strawberry.type
class Party:
    party_id: str
    full_name: str
    party_type: str
    
    @strawberry.field
    async def properties_owned(self) -> List[Property]:
        return await get_owned_properties(self.party_id)
    
    @strawberry.field
    async def transaction_history(self) -> List[Transaction]:
        return await get_party_transactions(self.party_id)

@strawberry.type
class Query:
    @strawberry.field
    async def property(self, property_id: str) -> Optional[Property]:
        return await get_property(property_id)
    
    @strawberry.field
    async def search_properties(self, 
                               query: str,
                               limit: int = 10) -> List[Property]:
        return await search_properties(query, limit)
    
    @strawberry.field
    async def party(self, party_id: str) -> Optional[Party]:
        return await get_party(party_id)
    
    @strawberry.field
    async def search_parties(self,
                           name: str,
                           fuzzy: bool = True) -> List[Party]:
        return await search_parties(name, fuzzy)

schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/api/graphql")
```

## Webhooks & Subscriptions

### Webhook Configuration
```python
@app.post("/api/v1/webhooks")
async def register_webhook(
    webhook: WebhookRegistration = Body(...),
    current_user: User = Depends(get_current_user)
) -> WebhookResponse:
    """
    Register webhook for event notifications
    
    Events:
    - document.processed: New document OCR completed
    - chain.updated: Title chain updated for property
    - report.generated: Report generation completed
    """
    webhook_id = await webhook_service.register(
        user_id=current_user.id,
        url=webhook.url,
        events=webhook.events,
        secret=webhook.secret
    )
    
    return WebhookResponse(
        webhook_id=webhook_id,
        status="active",
        events=webhook.events
    )

class WebhookService:
    """Handle webhook notifications"""
    
    async def notify(self, event: str, data: dict):
        """Send notifications to registered webhooks"""
        webhooks = await self.get_webhooks_for_event(event)
        
        for webhook in webhooks:
            payload = {
                "event": event,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            signature = self.generate_signature(payload, webhook.secret)
            
            await self.send_webhook(
                url=webhook.url,
                payload=payload,
                signature=signature
            )
```

### WebSocket Subscriptions
```python
@app.websocket("/api/v1/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...)
):
    """
    WebSocket connection for real-time updates
    """
    # Verify token
    user = await verify_websocket_token(token)
    
    if not user:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    
    # Subscribe to user's events
    subscription = await event_manager.subscribe(user.id)
    
    try:
        while True:
            # Send events to client
            event = await subscription.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        await event_manager.unsubscribe(subscription)
```

## Rate Limiting

### Implementation
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    storage_uri="redis://localhost:6379"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Custom limits for specific endpoints
@app.get("/api/v1/search/properties")
@limiter.limit("30/minute")
async def search_properties(...):
    pass

@app.post("/api/v1/reports/title")
@limiter.limit("10/hour")
async def generate_title_report(...):
    pass
```

### Tiered Rate Limits
```python
class RateLimitTiers:
    """Different rate limits based on user tier"""
    
    TIERS = {
        "free": {
            "requests_per_minute": 10,
            "requests_per_day": 100,
            "report_generation_per_day": 1
        },
        "basic": {
            "requests_per_minute": 60,
            "requests_per_day": 1000,
            "report_generation_per_day": 10
        },
        "premium": {
            "requests_per_minute": 300,
            "requests_per_day": 10000,
            "report_generation_per_day": 100
        },
        "enterprise": {
            "requests_per_minute": 1000,
            "requests_per_day": None,  # Unlimited
            "report_generation_per_day": None
        }
    }
```

## Error Handling

### Standard Error Responses
```python
class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[dict] = None
    request_id: str
    timestamp: datetime

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.__class__.__name__,
            message=exc.detail,
            request_id=request.state.request_id,
            timestamp=datetime.utcnow()
        ).dict()
    )

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="ValidationError",
            message="Invalid request data",
            details=exc.errors(),
            request_id=request.state.request_id,
            timestamp=datetime.utcnow()
        ).dict()
    )
```

## API Documentation

### OpenAPI Extensions
```python
from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Madison County Title Plant API",
        version="1.0.0",
        description="""
        ## Overview
        Comprehensive API for title searches and document retrieval.
        
        ## Authentication
        Use OAuth2 with JWT tokens or API keys for authentication.
        
        ## Rate Limits
        - Free tier: 100 requests/day
        - Basic: 1000 requests/day
        - Premium: 10000 requests/day
        
        ## Support
        Contact: api@madison-title-plant.com
        """,
        routes=app.routes,
    )
    
    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "OAuth2": {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": "/api/v1/auth/token",
                    "scopes": {
                        "read:basic": "Basic read access",
                        "read:full": "Full read access",
                        "write": "Write access"
                    }
                }
            }
        },
        "ApiKey": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key"
        }
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
```

## SDK Generation

### Client SDK Example (Python)
```python
class MadisonCountyTitlePlantClient:
    """Python SDK for Madison County Title Plant API"""
    
    def __init__(self, api_key: str = None, access_token: str = None):
        self.base_url = "https://api.madison-title-plant.com/v1"
        self.session = requests.Session()
        
        if api_key:
            self.session.headers["X-API-Key"] = api_key
        elif access_token:
            self.session.headers["Authorization"] = f"Bearer {access_token}"
    
    def search_properties(self, **kwargs) -> List[Property]:
        """Search for properties"""
        response = self.session.get(
            f"{self.base_url}/search/properties",
            params=kwargs
        )
        response.raise_for_status()
        return [Property(**p) for p in response.json()["results"]]
    
    def get_title_chain(self, property_id: str) -> TitleChain:
        """Get title chain for property"""
        response = self.session.get(
            f"{self.base_url}/properties/{property_id}/chain"
        )
        response.raise_for_status()
        return TitleChain(**response.json())
    
    def generate_title_report(self, property_id: str, 
                             examination_period: int = 60) -> str:
        """Generate title report"""
        response = self.session.post(
            f"{self.base_url}/reports/title",
            json={
                "property_id": property_id,
                "examination_period": examination_period
            }
        )
        response.raise_for_status()
        return response.json()["report_id"]
```

## Testing Strategy

### API Tests
```python
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def auth_headers():
    """Get authentication headers for tests"""
    token = create_test_token()
    return {"Authorization": f"Bearer {token}"}

def test_search_properties(client, auth_headers):
    """Test property search endpoint"""
    response = client.get(
        "/api/v1/search/properties",
        params={"query": "Madison Heights"},
        headers=auth_headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert isinstance(data["results"], list)

def test_rate_limiting(client, auth_headers):
    """Test rate limiting"""
    # Make requests up to limit
    for _ in range(100):
        response = client.get(
            "/api/v1/search/properties",
            params={"query": "test"},
            headers=auth_headers
        )
        assert response.status_code == 200
    
    # Next request should be rate limited
    response = client.get(
        "/api/v1/search/properties",
        params={"query": "test"},
        headers=auth_headers
    )
    assert response.status_code == 429

def test_title_chain_generation(client, auth_headers):
    """Test title chain endpoint"""
    property_id = "test_property_123"
    
    response = client.get(
        f"/api/v1/properties/{property_id}/chain",
        headers=auth_headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "chain" in data
    assert "completeness_score" in data
```

## Monitoring & Analytics

### API Metrics
```python
from prometheus_client import Counter, Histogram, generate_latest

# Metrics
request_count = Counter(
    'api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status']
)

request_duration = Histogram(
    'api_request_duration_seconds',
    'API request duration',
    ['method', 'endpoint']
)

@app.middleware("http")
async def track_metrics(request: Request, call_next):
    """Track API metrics"""
    start_time = time.time()
    
    response = await call_next(request)
    
    duration = time.time() - start_time
    
    request_count.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    
    request_duration.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)
    
    return response

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), media_type="text/plain")
```

## Deployment Configuration

### Docker Configuration
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### Kubernetes Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: title-plant-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: title-plant-api
  template:
    metadata:
      labels:
        app: title-plant-api
    spec:
      containers:
      - name: api
        image: madison-title-plant/api:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
        - name: JWT_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: jwt-secret
              key: key
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```