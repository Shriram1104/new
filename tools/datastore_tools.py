"""
Tools for interacting with Vertex AI Datastores.
These tools are used by agents to search for schemes with intelligent filtering.
"""

import time
import re
from typing import Dict, List, Any, Optional, Tuple
from google.cloud import discoveryengine_v1 as discoveryengine
from google.api_core.exceptions import GoogleAPIError

from config.settings import settings
from utils.logger import setup_logger, log_datastore_query
from collections.abc import Mapping

logger = setup_logger(__name__)


def _norm_state(s: str) -> str:
    """Normalize state string for comparison."""
    if not s:
        return ""
    s = str(s).strip().upper()
    s = re.sub(r"\s+", " ", s)
    # Common normalizations
    s = s.replace("&", "AND")
    return s

def _get_scheme_states(scheme: Dict[str, Any]) -> List[str]:
    """Extract scheme states from possible schema keys."""
    raw = scheme.get("nameOfState")
    if raw is None:
        raw = scheme.get("name_of_state")
    if raw is None:
        raw = scheme.get("state")  # fallback (rare)
    states: List[str] = []
    if isinstance(raw, list):
        states = [str(x) for x in raw if x is not None]
    elif isinstance(raw, str):
        # sometimes stored as comma-separated
        if "," in raw:
            states = [x.strip() for x in raw.split(",") if x.strip()]
        elif raw.strip():
            states = [raw.strip()]
    return states

def _apply_strict_state_filter(schemes: List[Dict[str, Any]], user_state: str) -> List[Dict[str, Any]]:
    """
    Keep only schemes whose nameOfState includes the user's state.
    If scheme has no states listed, drop it (strict mode).
    Allow schemes marked as pan-India (ALL INDIA / INDIA).
    """
    if not user_state:
        return schemes

    u = _norm_state(user_state)
    if not u:
        return schemes

    kept: List[Dict[str, Any]] = []
    dropped_missing = 0
    dropped_mismatch = 0

    for sc in schemes:
        states = _get_scheme_states(sc)
        if not states:
            dropped_missing += 1
            continue

        norm_states = {_norm_state(x) for x in states if x}
        if "ALL INDIA" in norm_states or "INDIA" in norm_states:
            kept.append(sc)
            continue

        if u in norm_states:
            kept.append(sc)
        else:
            dropped_mismatch += 1

    logger.info(
        "After strict state filter (state=%s): %s schemes (was %s). Dropped: missing_state_field=%s, mismatched_state=%s",
        u, len(kept), len(schemes), dropped_missing, dropped_mismatch
    )
    return kept


def _infer_support_intent(query: str, loan_amount: str = "") -> str:
    """Infer high-level support intent from query text."""
    q = f"{query} {loan_amount}".lower().strip()
    # Order matters: loan is often short ("loan", "19lakh")
    if any(k in q for k in ["loan", "credit", "finance", "financing", "working capital", "overdraft", "term loan", "mudra", "cgtmse", "subordinate debt"]):
        return "loan"
    if any(k in q for k in ["subsidy", "grant", "reimbursement", "incentive", "capital subsidy", "interest subsidy"]):
        return "subsidy"
    if any(k in q for k in ["training", "skill", "capacity building", "workshop", "mentoring", "incubation"]):
        return "training"
    if any(k in q for k in ["marketing", "export", "trade fair", "buyer", "branding", "packaging", "gem", "e-commerce", "ecommerce", "market link", "market access"]):
        return "marketing"
    return ""


def _intent_scores_for_scheme(scheme: Dict[str, Any]) -> Dict[str, int]:
    """Compute simple keyword scores per intent for a scheme."""
    parts: List[str] = []
    for k in ["serviceType", "service_type", "schemeType", "scheme_type", "benefitSummary", "benefit_summary", "benefit", "description", "name"]:
        v = scheme.get(k)
        if not v:
            continue
        if isinstance(v, list):
            parts.append(" ".join(str(x) for x in v if x is not None))
        else:
            parts.append(str(v))
    text = " ".join(parts).lower()

    def score(keys: List[str]) -> int:
        return sum(1 for kw in keys if kw in text)

    return {
        "loan": score(["loan", "credit", "cgtmse", "guarantee", "overdraft", "working capital", "term loan", "subordinate debt", "mudra"]),
        "subsidy": score(["subsidy", "grant", "reimbursement", "incentive", "capital subsidy", "interest subsidy", "upgradation fund", "atu f", "atufs"]),
        "training": score(["training", "skill", "capacity building", "workshop", "mentoring", "incubation", "consultancy"]),
        "marketing": score(["marketing", "export", "trade fair", "buyer", "branding", "packaging", "gem", "e-commerce", "ecommerce", "market access", "market linkage"]),
    }


def _apply_support_intent_filter(schemes: List[Dict[str, Any]], intent: str) -> Tuple[List[Dict[str, Any]], int]:
    """Filter schemes to match chosen intent; returns (kept, dropped_count)."""
    if not intent:
        return schemes, 0
    kept: List[Dict[str, Any]] = []
    dropped = 0

    for sc in schemes:
        scores = _intent_scores_for_scheme(sc)
        intent_score = scores.get(intent, 0)
        # Drop if the scheme looks strongly like a different category and not like the requested one.
        other_best = max(v for k, v in scores.items() if k != intent)
        if intent_score == 0 and other_best > 0:
            dropped += 1
            continue
        # If both have some signals, prefer requested intent
        if intent_score >= other_best:
            kept.append(sc)
        else:
            dropped += 1

    return kept, dropped


class DatastoreClient:
    """Client for interacting with Vertex AI Datastores."""
    
    def __init__(self):
        """Initialize datastore client."""
        self.project_id = settings.google_cloud_project
        self.location = settings.datastore_location
        self.farmer_datastore_id = settings.farmer_datastore_id
        self.msme_datastore_id = settings.msme_datastore_id
        
        # Initialize search client
        self.client = discoveryengine.SearchServiceAsyncClient()
    
    def _get_serving_config(self, datastore_id: str) -> str:
        """
        Get serving config path for datastore.
        
        Args:
            datastore_id: Datastore ID
            
        Returns:
            Serving config path
        """
        return (
            f"projects/{self.project_id}/locations/{self.location}/"
            f"collections/default_collection/dataStores/{datastore_id}/"
            f"servingConfigs/default_config"
        )
    
    async def search(
        self,
        query: str,
        datastore_id: str,
        filters: Optional[Dict[str, Any]] = None,
        max_results: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Search datastore for schemes.
        
        Args:
            query: Search query
            datastore_id: Datastore to search
            filters: Optional filters (NOT USED - datastore doesn't support field filters)
            max_results: Maximum number of results
            
        Returns:
            List of scheme documents
        """
        start_time = time.time()
        
        try:
            serving_config = self._get_serving_config(datastore_id)

            request = discoveryengine.SearchRequest(
                serving_config=serving_config,
                query=query,
                page_size=max_results,
                # Enable query expansion to improve recall for short queries like "loan".
                query_expansion_spec=discoveryengine.SearchRequest.QueryExpansionSpec(
                    condition=discoveryengine.SearchRequest.QueryExpansionSpec.Condition.AUTO
                ),
                spell_correction_spec=discoveryengine.SearchRequest.SpellCorrectionSpec(
                    mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO
                ),
            )
            
            # Execute search
            response = await self.client.search(request)
            
            # Parse results
            results = []
            for result in response.results:
                doc_data = self._parse_document(result.document)
                if doc_data:
                    # Attach retrieval score (0.0 if unavailable)
                    try:
                        doc_data["score"] = float(getattr(getattr(result, "metadata", None), "score", 0.0) or 0.0)
                    except Exception:
                        doc_data["score"] = 0.0
                    results.append(doc_data)
            
            duration_ms = (time.time() - start_time) * 1000
            log_datastore_query(
                logger,
                datastore_id,
                query,
                len(results),
                duration_ms
            )
            
            return results
            
        except GoogleAPIError as e:
            logger.error(f"Datastore search error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in datastore search: {e}")
            return []
    
    def _build_filter_string(self, filters: Dict[str, Any]) -> str:
        """
        Build filter string for datastore query.
        
        Args:
            filters: Filter dictionary
            
        Returns:
            Filter string
        """
        filter_parts = []
        
        # Location filter - using nameOfState field from your datastore schema
        if "state" in filters and filters["state"]:
            filter_parts.append(f'nameOfState: ANY("{filters["state"]}")')
        
        # Gender filter
        if "gender" in filters and filters["gender"]:
            filter_parts.append(f'gender: ANY("{filters["gender"]}")')
        
        # Category filter (for farmers)
        if "category" in filters and filters["category"]:
            filter_parts.append(f'category: ANY("{filters["category"]}")')
        
        # Business type filter (for MSMEs)
        if "business_type" in filters and filters["business_type"]:
            filter_parts.append(f'business_type: ANY("{filters["business_type"]}")')
        
        return " AND ".join(filter_parts)
    
    def _parse_document(self, document) -> Optional[Dict[str, Any]]:
        """
        Parse document from search result.
        
        Args:
            document: Document from search response
            
        Returns:
            Parsed document dictionary matching your schema
        """
        try:
            struct_data = document.struct_data
            
            # Extract data from your schema structure
            data = struct_data.get("data", {})
            
            # Deep conversion function to handle all protobuf types
            def make_json_safe(obj):
                """Recursively convert protobuf objects to JSON-serializable Python types."""
                if obj is None:
                    return None
                elif isinstance(obj, (str, int, float, bool)):
                    return obj
                # FIX: Check for Mapping (includes dict, Proto Maps, Structs)
                elif isinstance(obj, Mapping):
                    return {k: make_json_safe(v) for k, v in obj.items()}
                elif isinstance(obj, (list, tuple)):
                    return [make_json_safe(item) for item in obj]
                else:
                    try:
                        # This handles RepeatedComposite (lists)
                        return [make_json_safe(item) for item in obj]
                    except TypeError:
                        return str(obj)  
            
            return {
                "id": document.id,
                "guid": make_json_safe(data.get("guid", "")),
                "name": make_json_safe(data.get("name", "")),
                "description": make_json_safe(data.get("description", "")),
                "benefit_summary": make_json_safe(data.get("benefitSummary", "")),
                "benefit": make_json_safe(data.get("benefit", [])),
                "eligibility": make_json_safe(data.get("eligibility", [])),
                "eligibility_criteria": make_json_safe(data.get("eligibilityCriteria", {})),
                "process": make_json_safe(data.get("process", [])),
                "document_checklist": make_json_safe(data.get("documentChecklist", [])),
                "scheme_type": make_json_safe(data.get("schemeType", "")),
                "department_agency": make_json_safe(data.get("departmentAgency", [])),
                "service_type": make_json_safe(data.get("serviceType", [])),
                "beneficiary_type": make_json_safe(data.get("beneficiaryType", [])),
                "name_of_state": make_json_safe(data.get("nameOfState", [])),
                "sdg_impacted": make_json_safe(data.get("sdgImpactedList", [])),
            }
        except Exception as e:
            logger.error(f"Error parsing document: {e}")
            return None


# Global datastore client instance
_datastore_client = None


def get_datastore_client() -> DatastoreClient:
    """Get or create datastore client singleton."""
    global _datastore_client
    if _datastore_client is None:
        _datastore_client = DatastoreClient()
    return _datastore_client


# Tool functions for agents
async def search_farmer_schemes(
    query: str,
    state: str = "",
    category: str = "",
    gender: str = "",
    user_profile: str = "",
    exclude_schemes: str = ""
) -> str:
    """
    Search for farmer schemes in the datastore with intelligent filtering.
    
    This tool searches the farmer schemes datastore and returns relevant schemes
    based on the query. It automatically excludes schemes the user has already benefited from.
    
    Args:
        query: Search query describing the farmer's needs (e.g., "loan schemes for wheat farmers")
        state: State name (e.g., "Maharashtra", "Rajasthan") - will be added to query text
        category: Farmer category (e.g., "small", "marginal", "medium") - will be added to query text
        gender: Gender for targeting specific schemes (e.g., "male", "female") - will be added to query text
        user_profile: Complete user profile text to identify existing schemes/registrations (optional but recommended)
        exclude_schemes: Comma-separated list of scheme names to EXCLUDE from results (for "more schemes" requests)
        
    Returns:
        JSON string with list of schemes, count, and exclusion information
    """
    import json
    from tools.profile_analyzer import build_smart_query, extract_profile_exclusions
    
    client = get_datastore_client()
    
    # Parse excluded schemes list
    excluded_scheme_names = []
    if exclude_schemes:
        excluded_scheme_names = [s.strip().lower() for s in exclude_schemes.split(",") if s.strip()]
        logger.info(f"Excluding previously shown schemes: {excluded_scheme_names}")
    
    # Analyze profile for exclusions
    exclusion_info = {}
    if user_profile:
        exclusion_info = extract_profile_exclusions(user_profile)
        logger.info(f"Profile exclusions: {exclusion_info}")
    
    # Build enhanced query by including filters in the query text
    enhanced_query_parts = [query]
    
    if state:
        enhanced_query_parts.append(state)
    if category:
        enhanced_query_parts.append(f"{category} farmer")
    if gender:
        enhanced_query_parts.append(f"{gender} farmer")
    
    base_query = " ".join(enhanced_query_parts)
    
    # Apply smart filtering with exclusions
    enhanced_query = build_smart_query(
        base_query=base_query,
        profile_text=user_profile if user_profile else None
    )
    
    # Search with extra results to allow filtering
    # CRITICAL: When user asks for "more schemes", fetch more to find different schemes
    if excluded_scheme_names:
        fetch_count = 3 + len(excluded_scheme_names) + 10
        fetch_count = min(fetch_count, 25)
        logger.info(f"'More schemes' request: fetching {fetch_count} results")
    else:
        fetch_count = 8  # First search - fetch extra for invalid records
    
    # Search without filters (include context in query instead)
    schemes = await client.search(
        query=enhanced_query,
        datastore_id=settings.farmer_datastore_id,
        filters=None,  # Not used
        max_results=fetch_count
    )
    
    # CRITICAL: Filter out invalid/empty scheme records first
    if schemes:
        valid_schemes = []
        for scheme in schemes:
            scheme_name = scheme.get("name", "").strip()
            scheme_id = scheme.get("id", "").strip()
            
            # Skip empty or invalid records
            if not scheme_name:
                logger.warning(f"Filtered out empty scheme record: id={scheme_id}")
                continue
            if scheme_id in ["msme-schemes-list", "farmer-schemes-list", ""]:
                logger.warning(f"Filtered out metadata record: {scheme_id}")
                continue
            
            valid_schemes.append(scheme)
        
        schemes = valid_schemes
        logger.info(f"After filtering invalid records: {len(schemes)} valid schemes")
        # ===============================
        # MINIMUM SCORE FILTER (QUALITY)
        # ===============================
        try:
            min_score = float(getattr(settings, "min_scheme_score", 0.0) or 0.0)
        except Exception:
            min_score = 0.0

        if schemes and min_score > 0:
            before_score_count = len(schemes)
            dropped_low_score = 0
            kept = []
            for s in schemes:
                score = s.get("score", 0) or 0
                try:
                    score = float(score)
                except Exception:
                    score = 0.0
                if score >= min_score:
                    kept.append(s)
                else:
                    dropped_low_score += 1
            schemes = kept
            logger.info(
                f"[FARMER] After min score filter (min_score={min_score}): "
                f"{len(schemes)} schemes (was {before_score_count}). "
                f"Dropped low score: {dropped_low_score}"
            )
    
    # Filter out excluded schemes (for "more schemes" requests)
    if excluded_scheme_names and schemes:
        filtered_schemes = []
        for scheme in schemes:
            scheme_name = scheme.get("name", "").lower()
            is_excluded = any(
                excluded_name in scheme_name or scheme_name in excluded_name 
                for excluded_name in excluded_scheme_names
            )
            if not is_excluded:
                filtered_schemes.append(scheme)
            else:
                logger.info(f"Filtered out already-shown scheme: {scheme.get('name')}")
        
        schemes = filtered_schemes
        logger.info(f"After excluding shown schemes: {len(schemes)} remaining")

    # Filter by the support intent (loan/subsidy/training/marketing) to avoid cross-category results.
    intent = _infer_support_intent(query=query, loan_amount=loan_amount)
    if schemes and intent:
        before_intent = len(schemes)
        schemes, dropped = _apply_support_intent_filter(schemes, intent)
        logger.info(
            f"After support-intent filter (intent={intent}): {len(schemes)} schemes (was {before_intent}). Dropped: {dropped}"
        )


    # Strict state filter: show only schemes applicable to the user's state (nameOfState)
    if schemes and state:
        schemes = _apply_strict_state_filter(schemes, state)
    
    # Always limit to top 3 schemes
    schemes = schemes[:3] if schemes else []
    
    result = {
        "schemes": schemes,
        "count": len(schemes),
        "query": enhanced_query,
        "base_query": base_query,
        "state": state,
        "category": category,
        "excluded_schemes": excluded_scheme_names,
        "profile_analysis": {
            "existing_registrations": exclusion_info.get("existing_registrations", []),
            "excluded_schemes": exclusion_info.get("excluded_keywords", []),
            "exclusion_reasons": exclusion_info.get("exclusion_reasons", [])
        }
    }
    
    return result


async def search_msme_schemes(
    query: str,
    state: str = "",
    business_type: str = "",
    gender: str = "",
    user_profile: str = "",
    exclude_schemes: str = "",
    loan_amount: str = "",
    scheme_type: str = ""
) -> Dict[str, Any]:
    """
    Search for MSME schemes in the datastore with intelligent filtering.
    
    This tool searches the MSME schemes datastore and returns relevant schemes.
    It automatically excludes schemes the user has already benefited from based on their profile.
    It also filters and re-ranks schemes based on loan/benefit amount requirements.
    
    Args:
        query: Search query describing the business needs (e.g., "loan for textile business")
        state: State name (e.g., "Maharashtra", "Rajasthan") - will be added to query text
        business_type: Type of business (e.g., "manufacturing", "services", "trading") - will be added to query text
        gender: Gender for women entrepreneurship schemes (e.g., "female") - will be added to query text
        user_profile: Complete user profile text to identify existing schemes/registrations (optional but recommended)
        exclude_schemes: Comma-separated list of scheme names to EXCLUDE from results (for "more schemes" requests)
        loan_amount: User's required loan/benefit amount (e.g., "15 lakh", "1 crore", "above 50 lakh")
        scheme_type: Filter by scheme type - "central" for Central Government schemes, "state" for State schemes, "" for all
        
    Returns:
        Dictionary with list of schemes, count, and search metadata.
    """
    from tools.profile_analyzer import build_smart_query, extract_profile_exclusions
    from tools.amount_filter import filter_and_rank_by_amount, detect_amount_in_query
    
    client = get_datastore_client()
    
    # Parse excluded schemes list
    excluded_scheme_names = []
    if exclude_schemes:
        excluded_scheme_names = [s.strip().lower() for s in exclude_schemes.split(",") if s.strip()]
        logger.info(f"Excluding previously shown schemes: {excluded_scheme_names}")
    
    # Analyze profile for exclusions
    exclusion_info = {}
    if user_profile:
        exclusion_info = extract_profile_exclusions(user_profile)
        logger.info(f"Profile exclusions: {exclusion_info}")
    
    # Build enhanced query by including filters in the query text
    logger.info(f"msme query: {query}")
    enhanced_query_parts = [query]
    
    # Add state to query (helps with state-specific schemes)
    if state:
        enhanced_query_parts.append(state)
    
    # Add business_type to query - BUT limit to avoid noise
    # Only add business_type if it's a simple term (long strings dilute search relevance)
    if business_type:
        # Take only the first term if comma-separated, and limit length
        business_type_clean = business_type.split(',')[0].strip()[:30]
        if len(business_type_clean) <= 25:  # Only add if reasonably short
            enhanced_query_parts.append(business_type_clean)
    
    if gender and gender.lower() == "female":
        enhanced_query_parts.append("women entrepreneur")
    
    base_query = " ".join(enhanced_query_parts)
    
    # Apply smart filtering with exclusions
    enhanced_query = build_smart_query(
        base_query=base_query,
        profile_text=user_profile if user_profile else None
    )

    logger.info(f"enhanced query with exclusions: {enhanced_query}")
    
    # Detect if this is an amount-based query
    # Check both the original query and the loan_amount parameter
    amount_query = loan_amount if loan_amount else query
    has_amount_requirement = detect_amount_in_query(amount_query) or bool(loan_amount)
    
    if has_amount_requirement:
        logger.info(f"Amount-based query detected: '{amount_query}'")
    
    # Search with extra results to allow filtering
    # CRITICAL: Fetch MORE results when:
    # 1. User asks for "more schemes"
    # 2. Query has an amount requirement (need more to filter properly)
    if excluded_scheme_names:
        # For "more schemes" requests, fetch much more to find different schemes
        fetch_count = 3 + len(excluded_scheme_names) + 15  # Increased buffer
        fetch_count = min(fetch_count, 30)  # Increased cap
        logger.info(f"'More schemes' request: fetching {fetch_count} results to find new schemes")
    elif has_amount_requirement:
        # For amount-based queries, fetch many more to filter properly
        fetch_count = 25  # Fetch 25 to have good pool for amount filtering
        logger.info(f"Amount-based query: fetching {fetch_count} results for filtering")
    else:
        # First search without amount - fetch extra for invalid records
        fetch_count = 15  # Increased from 8 to 15 for better coverage
    schemes = await client.search(
        query=enhanced_query,
        datastore_id=settings.msme_datastore_id,
        filters=None,  # Not used
        max_results=fetch_count
    )
    
    # CRITICAL: Filter out invalid/empty scheme records first
    if schemes:
        valid_schemes = []
        for scheme in schemes:
            scheme_name = scheme.get("name", "").strip()
            scheme_id = scheme.get("id", "").strip()
            
            # Skip empty or invalid records
            if not scheme_name:
                logger.warning(f"Filtered out empty scheme record: id={scheme_id}")
                continue
            if scheme_id in ["msme-schemes-list", "farmer-schemes-list", ""]:
                logger.warning(f"Filtered out metadata record: {scheme_id}")
                continue
            
            valid_schemes.append(scheme)
        
        schemes = valid_schemes
        logger.info(f"After filtering invalid records: {len(schemes)} valid schemes")
        # ===============================
        # MINIMUM SCORE FILTER (QUALITY)
        # ===============================
        try:
            min_score = float(getattr(settings, "min_scheme_score", 0.0) or 0.0)
        except Exception:
            min_score = 0.0

        if schemes and min_score > 0:
            before_score_count = len(schemes)
            dropped_low_score = 0
            kept = []
            for s in schemes:
                score = s.get("score", 0) or 0
                try:
                    score = float(score)
                except Exception:
                    score = 0.0
                if score >= min_score:
                    kept.append(s)
                else:
                    dropped_low_score += 1
            schemes = kept
            logger.info(
                f"[MSME] After min score filter (min_score={min_score}): "
                f"{len(schemes)} schemes (was {before_score_count}). "
                f"Dropped low score: {dropped_low_score}"
            )
    
    # Filter out excluded schemes (for "more schemes" requests)
    if excluded_scheme_names and schemes:
        filtered_schemes = []
        for scheme in schemes:
            scheme_name = scheme.get("name", "").lower()
            # Check if this scheme name matches any excluded name (partial match)
            is_excluded = any(
                excluded_name in scheme_name or scheme_name in excluded_name 
                for excluded_name in excluded_scheme_names
            )
            if not is_excluded:
                filtered_schemes.append(scheme)
            else:
                logger.info(f"Filtered out already-shown scheme: {scheme.get('name')}")
        
        schemes = filtered_schemes
        logger.info(f"After excluding shown schemes: {len(schemes)} remaining")

    # Filter by high-level support intent (loan/subsidy/training/marketing)
    # This prevents non-loan items (e.g., account opening / generic services) from leaking into loan results.
    intent = _infer_support_intent(query, loan_amount)
    if schemes and intent:
        before_intent = len(schemes)
        schemes, dropped_intent = _apply_support_intent_filter(schemes, intent)
        logger.info(
            "After support intent filter (intent=%s): %s schemes (was %s). Dropped=%s",
            intent, len(schemes), before_intent, dropped_intent,
        )


    # Strict state filter: show only schemes applicable to the user's state (nameOfState)
    if schemes and state:
        schemes = _apply_strict_state_filter(schemes, state)
    
    # Filter by scheme_type (Central/State) if specified
    if scheme_type and schemes:
        scheme_type_lower = scheme_type.lower().strip()
        filtered_by_type = []
        
        for scheme in schemes:
            s_type = str(scheme.get("scheme_type", "")).lower()
            
            if scheme_type_lower in ["central", "central government", "केंद्र", "केंद्रीय"]:
                # Match Central Sector Scheme, Centrally Sponsored Scheme, etc.
                if "central" in s_type:
                    filtered_by_type.append(scheme)
            elif scheme_type_lower in ["state", "state government", "राज्य"]:
                # Match State Sector Scheme, State schemes, etc.
                if "state" in s_type or (s_type and "central" not in s_type):
                    filtered_by_type.append(scheme)
            else:
                # Unknown type filter - include all
                filtered_by_type.append(scheme)
        
        if filtered_by_type:
            schemes = filtered_by_type
            logger.info(f"After scheme_type filter ({scheme_type}): {len(schemes)} schemes")
        else:
            logger.info(f"No schemes found for type '{scheme_type}', keeping all schemes")
    
    # STEP 1: Apply eligibility filtering for existing businesses FIRST
    # This must run BEFORE amount filtering to exclude new-business-only schemes like PMEGP
    if exclusion_info.get('is_existing_business') and schemes:
        from tools.amount_filter import filter_new_business_only_schemes
        original_count = len(schemes)
        schemes = filter_new_business_only_schemes(schemes)
        logger.info(f"After eligibility filter (existing business): {len(schemes)} schemes (was {original_count})")
    
    # STEP 2: Apply amount-based filtering and re-ranking
    user_amount = None
    if has_amount_requirement and schemes:
        # Use loan_amount if provided, otherwise extract from query
        filter_query = loan_amount if loan_amount else query
        schemes, user_amount = filter_and_rank_by_amount(
            schemes, 
            filter_query, 
            min_results=3,
            profile_exclusions=exclusion_info
        )
        logger.info(f"After amount filter and re-rank: {len(schemes)} schemes (user_amount: {user_amount}L)")
    
    # STEP 3: Apply relevance-based ranking using user profile
    # This ranks schemes by how well they match the user's profile
    if schemes and user_profile:
        from utils.scheme_ranking import rank_schemes_by_relevance
        
        query_params = {
            'query': query,
            'state': state,
            'gender': gender,
            'loan_amount': loan_amount,
            'business_type': business_type
        }
        
        schemes = rank_schemes_by_relevance(
            schemes=schemes,
            user_profile_text=user_profile,
            query_params=query_params,
            exclude_schemes=excluded_scheme_names
        )
        logger.info(f"After relevance ranking: {len(schemes)} schemes")

        # Log top 3 with scores
        for i, scheme in enumerate(schemes[:3]):
            score = scheme.get('_relevance_score', 'N/A')
            reasons = scheme.get('_match_reasons', [])
            logger.info(f"  Top {i+1}: {scheme.get('name')} (Score: {score}, Matches: {reasons})")
    
    # Do NOT limit to 3 here. The agent must use progressive disclosure (3 at a time).
    logger.info(f"Final result pool: {len(schemes)} schemes")
    
    # Clean up internal scoring fields before returning
    for scheme in schemes:
        scheme.pop('_relevance_score', None)
        scheme.pop('_match_reasons', None)
    
    # Add scheme type classification to each scheme
    from utils.scheme_ranking import classify_scheme_type, format_department_info
    
    central_schemes = []
    state_schemes = []
    
    for scheme in schemes:
        scheme_category = classify_scheme_type(scheme)
        scheme['_scheme_category'] = scheme_category
        scheme['_department'] = format_department_info(scheme)
        
        if scheme_category == 'Central':
            central_schemes.append(scheme.get('name', ''))
        elif scheme_category == 'State':
            state_schemes.append(scheme.get('name', ''))
    
    # Display instruction for the agent (do not inline all names; use pagination)
    display_instruction = (
        "MANDATORY: Do not display more than 3 schemes at once. "
        "Use manage_scheme_pagination(schemes, current_page=0, session_state) "
        "and display ONLY the returned 'schemes_to_show'."
    )

    result = {
        "schemes": schemes,
        "count": len(schemes),
        "IMPORTANT_DISPLAY_ALL": display_instruction,
        "query": enhanced_query,
        "base_query": base_query,
        "state": state,
        "business_type": business_type,
        "excluded_schemes": excluded_scheme_names,
        "user_amount_lakhs": user_amount,
        "scheme_type_filter": scheme_type,
        "scheme_grouping": {
            "central_schemes": central_schemes,
            "state_schemes": state_schemes,
            "central_count": len(central_schemes),
            "state_count": len(state_schemes)
        },
        "profile_analysis": {
            "existing_registrations": exclusion_info.get("existing_registrations", []),
            "excluded_schemes": exclusion_info.get("excluded_keywords", []),
            "exclusion_reasons": exclusion_info.get("exclusion_reasons", [])
        }
    }
    
    return result


async def get_scheme_details(scheme_id: str, datastore_type: str) -> str:
    """
    Get detailed information about a specific scheme.
    
    This tool retrieves comprehensive details about a scheme including
    the application process, required documents, and contact information.
    
    Args:
        scheme_id: Unique identifier of the scheme
        datastore_type: Type of datastore - either "farmer" or "msme"
        
    Returns:
        JSON string with detailed scheme information
    """
    import json
    
    client = get_datastore_client()
    
    # Determine which datastore to use
    datastore_id = (
        settings.farmer_datastore_id if datastore_type == "farmer"
        else settings.msme_datastore_id
    )
    
    # Search for specific scheme by ID
    schemes = await client.search(
        query=scheme_id,
        datastore_id=datastore_id,
        max_results=10
    )

    for scheme in schemes:
        if scheme.get("id") == scheme_id:
             return json.dumps(scheme)
        if scheme.get("id") != "farmers-schemes-list" and scheme.get("name"):
             return json.dumps(scheme)
    
    return json.dumps({
        "error": "Scheme not found",
        "scheme_id": scheme_id
    })