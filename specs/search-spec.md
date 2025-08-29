# Search & Analysis Specification

## Overview
This specification defines the search algorithms, title chain construction, and analysis capabilities for the Madison County Title Plant. The system implements a resilient, probabilistic approach to handle the inherent uncertainty in OCR'd historical documents. Rather than failing when encountering ambiguity, the system quantifies uncertainty, explores multiple hypotheses, and intelligently routes low-confidence results for human review.

### Key Principles
- **Probabilistic over Deterministic**: All matching operations use confidence scores
- **Embrace Ambiguity**: Multiple chain candidates are explored simultaneously
- **Two-Phase Construction**: Backward traversal for ownership spine, forward traversal for document collection
- **Confidence Propagation**: OCR confidence flows through to final chain confidence
- **Human-in-the-Loop**: Systematic escalation of uncertain cases for expert review

## Search Architecture

### Hybrid Graph-Relational Architecture
```python
class SearchArchitecture:
    """
    Implements a hybrid approach leveraging PostgreSQL's advanced features:
    - Graph traversal via Recursive CTEs for ownership chains
    - Fuzzy matching via pg_trgm and fuzzystrmatch extensions
    - Temporal queries via tstzrange types and GiST indexes
    - Confidence scoring at every level
    """
    
    def __init__(self):
        self.db = PostgreSQLConnection()
        self.enable_extensions()
        self.confidence_threshold = {
            'high': 0.95,      # Conclusive match
            'medium': 0.70,    # Requires review
            'low': 0.50        # Potential gap
        }
    
    def enable_extensions(self):
        """Enable required PostgreSQL extensions"""
        self.db.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        self.db.execute("CREATE EXTENSION IF NOT EXISTS fuzzystrmatch")
        self.db.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
```

## Title Chain Construction

### Two-Phase Probabilistic Algorithm
```python
class TitleChainBuilder:
    """Constructs title chains using a resilient two-phase approach"""
    
    def build_chain(self, property_id: str, 
                   start_date: Optional[datetime] = None,
                   end_date: Optional[datetime] = None) -> List[TitleChain]:
        """
        Build title chain candidates using probabilistic matching.
        Returns multiple candidates ranked by confidence.
        """
        # Phase 1: Backward traversal to establish ownership spine
        ownership_spines = self.phase1_backward_traversal(
            property_id, end_date or datetime.now()
        )
        
        # Phase 2: Forward traversal to collect all documents
        complete_chains = []
        for spine in ownership_spines:
            chain = self.phase2_forward_collection(spine, property_id)
            chain.confidence_score = self.calculate_chain_confidence(spine)
            complete_chains.append(chain)
        
        # Rank chains by confidence and flag for review
        complete_chains.sort(key=lambda x: x.confidence_score, reverse=True)
        self.flag_chains_for_review(complete_chains)
        
        return complete_chains
    
    def phase1_backward_traversal(self, property_id: str, 
                                  start_point: datetime) -> List[OwnershipSpine]:
        """
        Phase 1: Trace ownership backward through time using fuzzy matching
        """
        spines = []
        current_transaction = self.get_most_recent_transaction(property_id, start_point)
        
        # Initialize the search queue with the current owner
        search_queue = [(current_transaction, [current_transaction], 1.0)]
        
        while search_queue:
            current, path, path_confidence = search_queue.pop(0)
            
            # Find the grantee who must have been the prior grantor
            target_entity = current.grantee_entity
            
            # Probabilistic search for prior transactions
            candidates = self.find_prior_grantor_transactions(
                property_id, target_entity, current.recording_date
            )
            
            for candidate, match_confidence in candidates:
                new_path = path + [candidate]
                new_confidence = path_confidence * match_confidence
                
                if match_confidence >= 0.95:
                    # High confidence - continue this path
                    if self.is_root_of_title(candidate) or len(new_path) >= 100:
                        spines.append(OwnershipSpine(new_path, new_confidence))
                    else:
                        search_queue.append((candidate, new_path, new_confidence))
                        
                elif match_confidence >= 0.70:
                    # Ambiguous - fork the chain
                    spines.append(OwnershipSpine(new_path, new_confidence, is_complete=False))
                    search_queue.append((candidate, new_path, new_confidence))
                    
                else:
                    # Low confidence - potential gap
                    spine = OwnershipSpine(new_path, new_confidence)
                    spine.has_gap = True
                    spine.gap_location = len(new_path)
                    spines.append(spine)
        
        return spines
    
    def find_prior_grantor_transactions(self, property_id: str,
                                       target_entity: Entity,
                                       before_date: datetime) -> List[Tuple[Transaction, float]]:
        """
        Find potential prior transactions using advanced fuzzy matching.
        Returns list of (transaction, match_confidence) tuples.
        """
        query = """
        WITH target_variants AS (
            SELECT raw_name, normalized_name, soundex_code, metaphone_code,
                   confidence_data->>'ocr_confidence' as ocr_conf
            FROM entity_name_variants
            WHERE entity_id = %s
        ),
        candidate_grantors AS (
            -- Use soundex for initial filtering
            SELECT DISTINCT env.entity_id, env.raw_name, env.confidence_data
            FROM entity_name_variants env
            JOIN target_variants tv ON env.soundex_code = tv.soundex_code
        )
        SELECT t.*, cg.raw_name as grantor_name,
               -- Calculate composite match confidence
               GREATEST(
                   similarity(cg.raw_name, tv.normalized_name),
                   similarity(cg.raw_name, tv.raw_name)
               ) * 
               -- Weight by OCR confidence
               ((cg.confidence_data->>'ocr_confidence')::float + 
                tv.ocr_conf::float) / 2.0 as match_confidence
        FROM transactions t
        JOIN candidate_grantors cg ON t.grantor_entity_id = cg.entity_id
        CROSS JOIN target_variants tv
        WHERE t.property_id = %s
          AND t.recording_date < %s
          AND t.transaction_type IN ('DEED', 'QUITCLAIM_DEED', 'TRUSTEES_DEED')
        ORDER BY match_confidence DESC, t.recording_date DESC
        LIMIT 10
        """
        
        results = self.db.execute(query, [target_entity.id, property_id, before_date])
        return [(Transaction(r), r['match_confidence']) for r in results]
    
    def phase2_forward_collection(self, spine: OwnershipSpine, 
                                 property_id: str) -> TitleChain:
        """
        Phase 2: Collect all documents within each ownership period
        """
        chain = TitleChain(property_id=property_id, spine=spine)
        
        # Process each ownership period in the spine
        for i in range(len(spine.transactions) - 1):
            vesting = spine.transactions[i]
            divesting = spine.transactions[i + 1]
            
            # Create ownership span using tstzrange
            ownership_period = f"[{vesting.recording_date}, {divesting.recording_date})"
            
            # Collect all documents in this period
            documents = self.collect_period_documents(
                property_id, 
                vesting.grantee_entity_id,
                ownership_period
            )
            
            chain.add_ownership_period(
                owner=vesting.grantee_entity,
                period=ownership_period,
                documents=documents
            )
        
        return chain
```

### Confidence Propagation & Gap Analysis
```python
class ChainConfidenceAnalyzer:
    """Propagates confidence scores and identifies uncertainty sources"""
    
    def calculate_chain_confidence(self, spine: OwnershipSpine) -> float:
        """
        Calculate overall chain confidence as product of link confidences.
        Distinguishes between OCR uncertainty and legal ambiguity.
        """
        if not spine.transactions:
            return 0.0
        
        # Product of all match confidence scores
        confidence = 1.0
        for i, transaction in enumerate(spine.transactions[1:]):
            confidence *= transaction.match_confidence
        
        # Apply penalties for gaps and ambiguities
        if spine.has_gap:
            confidence *= 0.5  # 50% penalty for gaps
        
        if not spine.is_complete:
            confidence *= 0.8  # 20% penalty for incomplete chains
        
        return confidence
    
    def identify_uncertainty_sources(self, chain: TitleChain) -> UncertaintyReport:
        """
        Distinguish between OCR issues and legal complexities
        """
        report = UncertaintyReport()
        
        for link in chain.spine.transactions:
            # OCR Uncertainty: Low confidence due to poor scan quality
            if link.ocr_confidence < 0.7:
                report.ocr_issues.append({
                    'transaction_id': link.id,
                    'confidence': link.ocr_confidence,
                    'fields': link.low_confidence_fields
                })
            
            # Legal Ambiguity: Multiple high-confidence competing paths
            if link.alternative_matches:
                high_conf_alternatives = [
                    alt for alt in link.alternative_matches 
                    if alt.match_confidence > 0.85
                ]
                if len(high_conf_alternatives) > 1:
                    report.legal_ambiguities.append({
                        'transaction_id': link.id,
                        'alternatives': high_conf_alternatives,
                        'reason': 'Multiple valid interpretations'
                    })
        
        # Time gaps that might indicate missing documents
        for i in range(1, len(chain.spine.transactions)):
            prev = chain.spine.transactions[i-1]
            curr = chain.spine.transactions[i]
            time_gap = curr.recording_date - prev.recording_date
            
            if time_gap.days > 365 * 20:  # 20+ year gap
                report.potential_gaps.append({
                    'position': i,
                    'gap_years': time_gap.days // 365,
                    'confidence_impact': 0.5
                })
        
        return report
    
    def suggest_remedies(self, gap: TitleGap) -> List[Remedy]:
        """Suggest remedies for identified gaps"""
        remedies = []
        
        if gap.type == GapType.TIME_GAP:
            remedies.append(Remedy(
                type=RemedyType.QUITCLAIM,
                description="Obtain quitclaim deed from potential heirs"
            ))
            remedies.append(Remedy(
                type=RemedyType.QUIET_TITLE,
                description="File quiet title action"
            ))
        
        elif gap.type == GapType.PARTY_MISMATCH:
            remedies.append(Remedy(
                type=RemedyType.AFFIDAVIT,
                description="Obtain affidavit explaining name variation"
            ))
            remedies.append(Remedy(
                type=RemedyType.CORRECTIVE_DEED,
                description="Record corrective deed"
            ))
        
        return remedies
```

## Search Algorithms

### Property Search
```python
class PropertySearchEngine:
    """Search for properties using various criteria"""
    
    def search_by_address(self, address: str) -> List[Property]:
        """Geocode address and search by location"""
        # Geocode address
        lat, lon = self.geocode(address)
        
        # Search within radius
        query = """
            SELECT * FROM properties
            WHERE ST_DWithin(
                polygon::geography,
                ST_MakePoint(%s, %s)::geography,
                100  -- 100 meter radius
            )
            ORDER BY ST_Distance(
                polygon::geography,
                ST_MakePoint(%s, %s)::geography
            )
        """
        return self.db.execute(query, [lon, lat, lon, lat])
    
    def search_by_legal_description(self, 
                                   description: str) -> List[Property]:
        """Parse and search by legal description"""
        # Parse description
        parsed = self.parse_legal_description(description)
        
        # Build search query based on parsed components
        if parsed.get('subdivision'):
            return self.search_by_subdivision(
                parsed['subdivision'],
                parsed.get('lot'),
                parsed.get('block')
            )
        
        elif parsed.get('section'):
            return self.search_by_section_township_range(
                parsed['section'],
                parsed['township'],
                parsed['range']
            )
        
        else:
            # Fall back to fuzzy text search
            return self.fuzzy_search_description(description)
    
    def search_by_parcel(self, parcel_number: str) -> Optional[Property]:
        """Direct search by parcel number"""
        # Normalize parcel number
        normalized = self.normalize_parcel_number(parcel_number)
        
        query = """
            SELECT * FROM properties
            WHERE parcel_number = %s
            OR parcel_number LIKE %s
        """
        
        results = self.db.execute(query, [
            normalized,
            f"%{normalized}%"
        ])
        
        return results[0] if results else None
```

### Party Search
```python
class PartySearchEngine:
    """Search for parties and their transactions"""
    
    def search_party(self, name: str, 
                    fuzzy: bool = True) -> List[PartySearchResult]:
        """
        Search for parties by name with optional fuzzy matching
        """
        results = []
        
        # Exact match
        exact = self.exact_name_search(name)
        results.extend(exact)
        
        if fuzzy and len(results) < 10:
            # Fuzzy match
            fuzzy_results = self.fuzzy_name_search(name, threshold=0.7)
            results.extend(fuzzy_results)
            
            # Phonetic match
            phonetic = self.phonetic_search(name)
            results.extend(phonetic)
        
        # Deduplicate and rank
        results = self.deduplicate_results(results)
        results = self.rank_results(results, name)
        
        return results
    
    def get_party_transactions(self, party_id: str) -> PartyHistory:
        """Get complete transaction history for a party"""
        query = """
            SELECT 
                t.*,
                tp.party_role,
                tp.ownership_percentage,
                p.legal_description_text,
                d.document_type,
                d.recording_date
            FROM transaction_parties tp
            JOIN transactions t ON t.transaction_id = tp.transaction_id
            JOIN properties p ON p.property_id = t.property_id
            JOIN documents d ON d.document_id = t.document_id
            WHERE tp.party_id = %s
            ORDER BY d.recording_date DESC
        """
        
        transactions = self.db.execute(query, [party_id])
        
        return PartyHistory(
            party_id=party_id,
            transactions=transactions,
            as_grantor=self.filter_by_role(transactions, PartyRole.GRANTOR),
            as_grantee=self.filter_by_role(transactions, PartyRole.GRANTEE),
            properties_owned=self.extract_owned_properties(transactions)
        )
```

### Document Search
```python
class DocumentSearchEngine:
    """Search through document content and metadata"""
    
    def search_documents(self, 
                        query: str,
                        filters: Optional[SearchFilters] = None) -> List[Document]:
        """
        Full-text search across OCR content
        """
        # Build search query
        search_query = self.build_search_query(query, filters)
        
        # Execute search
        if self.use_elasticsearch:
            results = self.elasticsearch_search(search_query)
        else:
            results = self.postgres_fts_search(search_query)
        
        # Apply post-processing
        results = self.apply_relevance_scoring(results, query)
        results = self.highlight_matches(results, query)
        
        return results
    
    def build_search_query(self, query: str, 
                          filters: Optional[SearchFilters]) -> dict:
        """Build search query with filters"""
        search = {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"ocr_text": query}}
                    ],
                    "filter": []
                }
            }
        }
        
        if filters:
            if filters.document_types:
                search["query"]["bool"]["filter"].append({
                    "terms": {"document_type": filters.document_types}
                })
            
            if filters.date_range:
                search["query"]["bool"]["filter"].append({
                    "range": {
                        "recording_date": {
                            "gte": filters.date_range.start,
                            "lte": filters.date_range.end
                        }
                    }
                })
            
            if filters.book_range:
                search["query"]["bool"]["filter"].append({
                    "range": {
                        "book": {
                            "gte": filters.book_range.start,
                            "lte": filters.book_range.end
                        }
                    }
                })
        
        return search
```

## Advanced Search Features

### Relationship Graph Search
```python
class GraphSearchEngine:
    """Graph-based search for complex relationships"""
    
    def find_ownership_path(self, 
                           start_party: str,
                           end_party: str,
                           property_id: Optional[str] = None) -> List[Path]:
        """
        Find how ownership transferred between two parties
        """
        # Build ownership graph
        graph = self.build_ownership_graph(property_id)
        
        # Find all paths using BFS/DFS
        paths = self.find_all_paths(
            graph,
            start_party,
            end_party,
            max_depth=10
        )
        
        # Rank paths by reliability
        ranked_paths = self.rank_paths(paths)
        
        return ranked_paths
    
    def find_common_ownership(self, 
                             party_ids: List[str]) -> List[Property]:
        """
        Find properties owned by multiple parties
        """
        query = """
            WITH party_properties AS (
                SELECT 
                    tp.party_id,
                    t.property_id,
                    COUNT(*) as transaction_count
                FROM transaction_parties tp
                JOIN transactions t ON t.transaction_id = tp.transaction_id
                WHERE tp.party_id = ANY(%s)
                AND tp.party_role = 'GRANTEE'
                GROUP BY tp.party_id, t.property_id
            )
            SELECT 
                p.*,
                array_agg(pp.party_id) as involved_parties
            FROM properties p
            JOIN party_properties pp ON pp.property_id = p.property_id
            GROUP BY p.property_id
            HAVING COUNT(DISTINCT pp.party_id) >= 2
        """
        
        return self.db.execute(query, [party_ids])
```

### Human-in-the-Loop (HITL) Workflow
```python
class HITLWorkflowManager:
    """Manages human review workflow for uncertain chains"""
    
    def __init__(self):
        self.review_thresholds = {
            'auto_accept': 0.95,      # Fully automated above this
            'quick_review': 0.85,     # Light review
            'detailed_review': 0.70,  # Full review
            'expert_required': 0.50   # Escalate to senior examiner
        }
    
    def triage_chains_for_review(self, chains: List[TitleChain]) -> ReviewQueue:
        """
        Intelligently route chains to appropriate review level
        """
        queue = ReviewQueue()
        
        for chain in chains:
            confidence = chain.confidence_score
            uncertainty = chain.uncertainty_report
            
            # Determine review level
            if confidence >= self.review_thresholds['auto_accept']:
                if not uncertainty.legal_ambiguities:
                    chain.status = 'AUTO_APPROVED'
                    continue
            
            # Create review task
            task = ReviewTask(
                chain_id=chain.id,
                property_id=chain.property_id,
                confidence_score=confidence,
                priority=self.calculate_priority(chain),
                review_level=self.determine_review_level(confidence),
                evidence_packages=self.prepare_evidence(chain)
            )
            
            # Add specific review points
            for issue in uncertainty.ocr_issues:
                task.add_review_point(
                    type='OCR_VERIFICATION',
                    transaction_id=issue['transaction_id'],
                    description=f"Verify OCR text (confidence: {issue['confidence']:.2%})"
                )
            
            for ambiguity in uncertainty.legal_ambiguities:
                task.add_review_point(
                    type='LEGAL_DECISION',
                    transaction_id=ambiguity['transaction_id'],
                    description='Choose correct ownership path',
                    options=ambiguity['alternatives']
                )
            
            queue.add_task(task)
        
        return queue
    
    def prepare_evidence(self, chain: TitleChain) -> List[EvidencePackage]:
        """
        Prepare evidence packages for reviewer interface
        """
        packages = []
        
        for link in chain.spine.transactions:
            if link.match_confidence < 0.90:
                package = EvidencePackage(
                    transaction_id=link.id,
                    document_images=self.get_document_images(link.doc_id),
                    ocr_raw_text=link.ocr_raw_text,
                    ocr_corrected_text=link.ocr_corrected_text,
                    extracted_entities=link.extracted_entities,
                    confidence_scores={
                        'ocr': link.ocr_confidence,
                        'ner': link.ner_confidence,
                        'match': link.match_confidence
                    },
                    alternative_interpretations=link.alternative_matches
                )
                packages.append(package)
        
        return packages
    
    def process_reviewer_feedback(self, task: ReviewTask, 
                                 decisions: List[ReviewDecision]) -> None:
        """
        Process human reviewer decisions and update chain
        """
        chain = self.get_chain(task.chain_id)
        
        for decision in decisions:
            if decision.type == 'OCR_CORRECTION':
                # Update OCR text in database
                self.update_ocr_text(
                    decision.transaction_id,
                    decision.corrected_text
                )
                # Add to retraining dataset
                self.add_to_training_data(
                    original=decision.original_text,
                    corrected=decision.corrected_text,
                    confidence=1.0  # Human-verified
                )
            
            elif decision.type == 'LINK_CONFIRMATION':
                # Update match confidence to 1.0 for confirmed links
                self.update_match_confidence(
                    decision.transaction_id,
                    confidence=1.0,
                    verified_by=decision.reviewer_id
                )
            
            elif decision.type == 'GAP_DECLARATION':
                # Formally declare a gap in the chain
                self.declare_chain_gap(
                    chain_id=chain.id,
                    position=decision.gap_position,
                    reason=decision.gap_reason
                )
        
        # Update chain status
        chain.status = 'HUMAN_VERIFIED'
        chain.reviewed_by = task.reviewer_id
        chain.reviewed_at = datetime.now()
        self.save_chain(chain)
```

## Title Examination Automation

### Automated Title Report Generation
```python
class TitleReportGenerator:
    """Generate comprehensive title reports"""
    
    def generate_report(self, 
                       property_id: str,
                       examination_period: int = 60) -> TitleReport:
        """
        Generate complete title report for property
        """
        report = TitleReport()
        
        # Property information
        report.property = self.get_property_details(property_id)
        
        # Current ownership
        report.current_owner = self.get_current_owner(property_id)
        
        # Title chain
        start_date = datetime.now() - timedelta(days=examination_period * 365)
        report.chain = self.build_title_chain(property_id, start_date)
        
        # Encumbrances
        report.mortgages = self.find_open_mortgages(property_id)
        report.liens = self.find_liens(property_id)
        report.easements = self.find_easements(property_id)
        
        # Exceptions and requirements
        report.exceptions = self.identify_exceptions(report.chain)
        report.requirements = self.generate_requirements(report.exceptions)
        
        # Risk assessment
        report.risk_score = self.calculate_risk_score(report)
        report.insurability = self.assess_insurability(report)
        
        return report
    
    def identify_exceptions(self, chain: TitleChain) -> List[Exception]:
        """
        Identify standard title insurance exceptions
        """
        exceptions = []
        
        # Standard exceptions
        exceptions.append(Exception(
            type=ExceptionType.STANDARD,
            description="Rights of parties in possession"
        ))
        
        exceptions.append(Exception(
            type=ExceptionType.STANDARD,
            description="Encroachments, overlaps, boundary disputes"
        ))
        
        # Chain-specific exceptions
        for gap in chain.gaps:
            exceptions.append(Exception(
                type=ExceptionType.GAP,
                description=f"Gap in title chain: {gap.description}",
                severity=gap.severity
            ))
        
        # Missing documents
        if chain.missing_documents:
            for doc in chain.missing_documents:
                exceptions.append(Exception(
                    type=ExceptionType.MISSING_DOCUMENT,
                    description=f"Missing: {doc.description}"
                ))
        
        return exceptions
```

## Search Optimization

### Caching Strategy
```python
class SearchCache:
    """Cache frequently searched items"""
    
    def __init__(self):
        self.redis = Redis()
        self.cache_ttl = {
            'property': 3600,      # 1 hour
            'party': 1800,         # 30 minutes
            'chain': 7200,         # 2 hours
            'document': 86400     # 24 hours
        }
    
    def get_cached_chain(self, property_id: str) -> Optional[TitleChain]:
        key = f"chain:{property_id}"
        cached = self.redis.get(key)
        
        if cached:
            # Validate cache freshness
            chain = json.loads(cached)
            if self.is_cache_valid(chain):
                return chain
        
        return None
    
    def cache_search_results(self, 
                           query: str, 
                           results: List[Any],
                           ttl: int = 1800):
        """Cache search results with query as key"""
        key = f"search:{hashlib.md5(query.encode()).hexdigest()}"
        self.redis.setex(key, ttl, json.dumps(results))
```

### Query Optimization
```python
class QueryOptimizer:
    """Optimize database queries for performance"""
    
    def optimize_chain_query(self, property_id: str) -> str:
        """
        Generate optimized query for title chain retrieval
        """
        return """
            WITH RECURSIVE chain AS (
                -- Anchor: most recent transaction
                SELECT 
                    t.*,
                    1 as depth,
                    ARRAY[t.transaction_id] as path
                FROM transactions t
                WHERE t.property_id = %s
                AND NOT EXISTS (
                    SELECT 1 FROM transactions t2
                    WHERE t2.property_id = t.property_id
                    AND t2.recording_date > t.recording_date
                )
                
                UNION ALL
                
                -- Recursive: previous transactions
                SELECT 
                    t.*,
                    c.depth + 1,
                    c.path || t.transaction_id
                FROM transactions t
                JOIN chain c ON t.property_id = c.property_id
                WHERE t.recording_date < c.recording_date
                AND NOT t.transaction_id = ANY(c.path)
                AND c.depth < 100
            )
            SELECT * FROM chain
            ORDER BY recording_date DESC
        """
```

## Analytics & Reporting

### Market Analytics
```python
class MarketAnalytics:
    """Analyze market trends from title data"""
    
    def calculate_property_velocity(self, 
                                   area: Polygon,
                                   period: DateRange) -> VelocityMetrics:
        """
        Calculate how quickly properties change hands
        """
        query = """
            SELECT 
                COUNT(*) as transaction_count,
                COUNT(DISTINCT property_id) as unique_properties,
                AVG(EXTRACT(days FROM 
                    lead(recording_date) OVER (
                        PARTITION BY property_id 
                        ORDER BY recording_date
                    ) - recording_date
                )) as avg_holding_period
            FROM transactions t
            JOIN properties p ON p.property_id = t.property_id
            WHERE ST_Within(p.polygon, %s)
            AND t.recording_date BETWEEN %s AND %s
        """
        
        results = self.db.execute(query, [area, period.start, period.end])
        
        return VelocityMetrics(
            transactions=results['transaction_count'],
            unique_properties=results['unique_properties'],
            avg_holding_days=results['avg_holding_period'],
            velocity_score=self.calculate_velocity_score(results)
        )
```

### Quality Metrics
```python
class QualityAnalyzer:
    """Analyze data quality and completeness"""
    
    def analyze_data_quality(self) -> QualityReport:
        """
        Comprehensive data quality analysis
        """
        return QualityReport(
            total_documents=self.count_documents(),
            ocr_completion_rate=self.calculate_ocr_rate(),
            avg_ocr_confidence=self.calculate_avg_confidence(),
            chain_completeness=self.analyze_chain_completeness(),
            party_resolution_rate=self.calculate_party_resolution(),
            missing_data_report=self.identify_missing_data()
        )
    
    def identify_missing_data(self) -> MissingDataReport:
        """
        Identify gaps in data coverage
        """
        # Find missing book/page combinations
        missing_docs = self.find_missing_documents()
        
        # Find properties without complete chains
        incomplete_chains = self.find_incomplete_chains()
        
        # Find unresolved parties
        unresolved_parties = self.find_unresolved_parties()
        
        return MissingDataReport(
            missing_documents=missing_docs,
            incomplete_chains=incomplete_chains,
            unresolved_parties=unresolved_parties,
            coverage_percentage=self.calculate_coverage()
        )
```

## Testing Strategy

### Search Accuracy Tests
```python
class SearchAccuracyTests:
    """Test search accuracy and completeness"""
    
    def test_title_chain_construction(self):
        """Test chain construction with known data"""
        # Create test property with known chain
        property_id = self.create_test_property()
        self.create_test_transactions(property_id)
        
        # Build chain
        chain = self.chain_builder.build_chain(property_id)
        
        # Verify chain integrity
        assert len(chain.links) == 5
        assert chain.completeness_score > 0.9
        assert len(chain.gaps) == 0
    
    def test_fuzzy_party_matching(self):
        """Test party name matching algorithms"""
        test_cases = [
            ("John Smith", "John W Smith", 0.9),
            ("ABC Corp", "ABC Corporation", 0.95),
            ("Smith, John", "John Smith", 1.0)
        ]
        
        for name1, name2, expected_score in test_cases:
            score = self.matcher.match_score(name1, name2)
            assert abs(score - expected_score) < 0.05
```

### Performance Tests
```python
class SearchPerformanceTests:
    """Test search performance at scale"""
    
    def test_chain_construction_performance(self):
        """Ensure chain construction completes in reasonable time"""
        import time
        
        # Test with property having 100+ transactions
        property_id = self.get_complex_property()
        
        start = time.time()
        chain = self.chain_builder.build_chain(property_id)
        elapsed = time.time() - start
        
        assert elapsed < 2.0  # Should complete in under 2 seconds
        assert len(chain.links) > 100
    
    def test_concurrent_searches(self):
        """Test system under concurrent search load"""
        from concurrent.futures import ThreadPoolExecutor
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for _ in range(100):
                future = executor.submit(
                    self.search_engine.search_documents,
                    "test query"
                )
                futures.append(future)
            
            results = [f.result() for f in futures]
            
        # All searches should complete successfully
        assert all(r is not None for r in results)
```