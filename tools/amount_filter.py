"""
Amount-based filtering and re-ranking for scheme search results.
This module handles parsing loan/benefit amounts from user queries and scheme data,
and filters/re-ranks search results based on amount requirements.
"""

import re
from typing import Dict, List, Optional, Tuple
from utils.logger import setup_logger

logger = setup_logger(__name__)


# Amount conversion constants (all in lakhs for easier comparison)
AMOUNT_MULTIPLIERS = {
    'crore': 100,      # 1 crore = 100 lakhs
    'cr': 100,
    'crores': 100,
    'lakh': 1,
    'lakhs': 1,
    'lac': 1,
    'lacs': 1,
    'l': 1,
    'thousand': 0.01,  # 1 lakh = 100 thousand
    'k': 0.01,
}


def parse_amount_from_text(text: str) -> Optional[float]:
    """
    Parse monetary amount from text string.
    Returns amount in lakhs for easier comparison.
    
    Args:
        text: Text containing amount (e.g., "15 lakh", "₹1 crore", "Rs.20,00,000")
        
    Returns:
        Amount in lakhs, or None if no amount found
        
    Examples:
        "15 lakh" -> 15.0
        "₹1 crore" -> 100.0
        "Rs.20,00,000" -> 20.0
        "50000" -> 0.5
        "₹5 crore" -> 500.0
        "10 lakh to 20 lakh" -> 20.0 (returns max)
    """
    if not text:
        return None
    
    text_lower = text.lower().strip()
    
    # Pattern 1: Number with unit (e.g., "15 lakh", "1 crore", "50 thousand")
    pattern_with_unit = r'(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|l|thousand|k)\b'
    matches = re.findall(pattern_with_unit, text_lower)
    
    if matches:
        # If multiple matches (e.g., "10 lakh to 20 lakh"), take the maximum
        amounts = []
        for num_str, unit in matches:
            try:
                num = float(num_str)
                multiplier = AMOUNT_MULTIPLIERS.get(unit, 1)
                amounts.append(num * multiplier)
            except ValueError:
                continue
        
        if amounts:
            max_amount = max(amounts)
            logger.info(f"Parsed amount from '{text}': {max_amount} lakhs (pattern: with_unit)")
            return max_amount
    
    # Pattern 2: Indian format with commas (e.g., "Rs.20,00,000" or "₹50,00,000")
    # Indian format: 1,00,000 = 1 lakh, 1,00,00,000 = 1 crore
    pattern_indian = r'[₹rs.\s]*(\d{1,2}(?:,\d{2})*(?:,\d{3})?)(?:\s|$|[^\d])'
    indian_matches = re.findall(pattern_indian, text_lower.replace(' ', ''))
    
    if indian_matches:
        amounts = []
        for match in indian_matches:
            # Remove commas and convert to number
            num_str = match.replace(',', '')
            try:
                num = float(num_str)
                # Convert to lakhs
                amount_in_lakhs = num / 100000
                amounts.append(amount_in_lakhs)
            except ValueError:
                continue
        
        if amounts:
            max_amount = max(amounts)
            logger.info(f"Parsed amount from '{text}': {max_amount} lakhs (pattern: indian_format)")
            return max_amount
    
    # Pattern 3: Plain number (interpret based on magnitude)
    pattern_plain = r'(?<![,\d])(\d+(?:\.\d+)?)(?![,\d])'
    plain_matches = re.findall(pattern_plain, text_lower)
    
    if plain_matches:
        amounts = []
        for num_str in plain_matches:
            try:
                num = float(num_str)
                # Heuristic: if number is large (>1000), assume it's in rupees
                # Otherwise, assume it's already in lakhs
                if num >= 10000000:  # 1 crore+
                    amount_in_lakhs = num / 100000
                elif num >= 100000:  # 1 lakh+
                    amount_in_lakhs = num / 100000
                elif num >= 1000:  # Thousands - likely rupees
                    amount_in_lakhs = num / 100000
                else:
                    # Small number - assume it's in lakhs if context suggests
                    # (e.g., "15" in "15 lakh loan" - but unit was already caught above)
                    # If no unit, and number is small, might be lakhs already
                    amount_in_lakhs = num if num <= 100 else num / 100000
                amounts.append(amount_in_lakhs)
            except ValueError:
                continue
        
        if amounts:
            max_amount = max(amounts)
            logger.info(f"Parsed amount from '{text}': {max_amount} lakhs (pattern: plain_number)")
            return max_amount
    
    return None


def parse_user_amount_requirement(query: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Parse user's loan/benefit amount requirement from their query.
    
    Args:
        query: User's search query (e.g., "loan 15 lakh", "above 1 crore")
        
    Returns:
        Tuple of (amount_in_lakhs, comparison_type)
        comparison_type can be: "exact", "above", "below", "range"
        
    Examples:
        "15 lakh loan" -> (15.0, "exact")
        "loan above 1 crore" -> (100.0, "above")
        "less than 50 lakh" -> (50.0, "below")
        "10 to 20 lakh" -> (20.0, "range")
    """
    if not query:
        return None, None
    
    query_lower = query.lower()
    
    # Check for comparison keywords
    above_keywords = ['above', 'more than', 'greater than', 'over', 'exceeding', 'minimum', 'at least', 'upar', 'zyada']
    below_keywords = ['below', 'less than', 'under', 'within', 'up to', 'upto', 'maximum', 'max', 'tak', 'niche']
    
    comparison_type = "exact"
    
    for keyword in above_keywords:
        if keyword in query_lower:
            comparison_type = "above"
            break
    
    if comparison_type == "exact":
        for keyword in below_keywords:
            if keyword in query_lower:
                comparison_type = "below"
                break
    
    # Check for range (e.g., "10 to 20 lakh")
    range_pattern = r'(\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|l)?'
    range_match = re.search(range_pattern, query_lower)
    if range_match:
        comparison_type = "range"
    
    # Parse the amount
    amount = parse_amount_from_text(query)
    
    if amount:
        logger.info(f"User amount requirement: {amount} lakhs, comparison: {comparison_type}")
    
    return amount, comparison_type


def parse_scheme_max_amount(scheme: Dict) -> Optional[float]:
    """
    Parse maximum loan/benefit amount from a scheme's data.
    
    Checks benefit_summary, benefit, and description fields.
    
    Args:
        scheme: Scheme dictionary with benefit_summary, benefit, description
        
    Returns:
        Maximum amount in lakhs, or None if not found
    """
    # Priority order: benefit_summary > benefit > description
    fields_to_check = [
        scheme.get('benefit_summary', ''),
        scheme.get('benefit', ''),
        scheme.get('description', '')
    ]
    
    # Handle if benefit is a list
    if isinstance(fields_to_check[1], list):
        fields_to_check[1] = ' '.join(str(item) for item in fields_to_check[1])
    
    for field in fields_to_check:
        if field:
            amount = parse_amount_from_text(str(field))
            if amount:
                scheme_name = scheme.get('name', 'Unknown')
                logger.debug(f"Scheme '{scheme_name}' max amount: {amount} lakhs")
                return amount
    
    return None


def filter_schemes_by_amount(
    schemes: List[Dict],
    user_amount: float,
    comparison_type: str = "exact",
    lower_tolerance: float = 0.0,
) -> List[Dict]:
    """
    Filter schemes based on user's amount requirement.
    
    Args:
        schemes: List of scheme dictionaries
        user_amount: User's required amount in lakhs
        comparison_type: "exact", "above", "below", or "range"
        
    Returns:
        Filtered list of schemes that meet the amount requirement
    """
    if not schemes or not user_amount:
        return schemes
    
    # Clamp tolerance to a sane range (0% to 50%)
    try:
        lower_tolerance = float(lower_tolerance or 0.0)
    except Exception:
        lower_tolerance = 0.0
    if lower_tolerance < 0:
        lower_tolerance = 0.0
    if lower_tolerance > 0.5:
        lower_tolerance = 0.5

    effective_min = user_amount
    # For "exact" (e.g. "15 lakh") allow schemes slightly lower than requirement
    # Example: user wants 15L, tolerance 20% -> accept >= 12L
    if comparison_type in ["exact", "range"] and lower_tolerance > 0:
        effective_min = user_amount * (1.0 - lower_tolerance)

    filtered = []
    
    for scheme in schemes:
        scheme_max = parse_scheme_max_amount(scheme)
        scheme_name = scheme.get('name', 'Unknown')
        
        if scheme_max is None:
            # If we can't parse the amount, include the scheme (benefit of doubt)
            logger.debug(f"Scheme '{scheme_name}': No amount found, including by default")
            filtered.append(scheme)
            continue
        
        # Apply filter based on comparison type
        include = False
        
        if comparison_type == "above":
            # User wants schemes that offer MORE than their requirement
            include = scheme_max >= user_amount
            
        elif comparison_type == "below":
            # User wants schemes that are WITHIN their limit
            include = scheme_max <= user_amount
            
        elif comparison_type in ["exact", "range"]:
            # User wants schemes that can cover their requirement.
            # With tolerance, we also accept schemes that are close (slightly below).
            include = scheme_max >= effective_min
        
        if include:
            if comparison_type in ["exact", "range"] and effective_min != user_amount:
                logger.info(
                    f"✅ Scheme '{scheme_name}' INCLUDED: offers {scheme_max}L, user needs {user_amount}L (tolerance allows >= {effective_min:.2f}L)"
                )
            else:
                logger.info(f"✅ Scheme '{scheme_name}' INCLUDED: offers {scheme_max}L, user needs {user_amount}L ({comparison_type})")
            filtered.append(scheme)
        else:
            if comparison_type in ["exact", "range"] and effective_min != user_amount:
                logger.info(
                    f"❌ Scheme '{scheme_name}' EXCLUDED: offers {scheme_max}L, user needs {user_amount}L (tolerance allows >= {effective_min:.2f}L)"
                )
            else:
                logger.info(f"❌ Scheme '{scheme_name}' EXCLUDED: offers {scheme_max}L, user needs {user_amount}L ({comparison_type})")
    
    return filtered


def rank_schemes_by_amount_relevance(
    schemes: List[Dict],
    user_amount: float,
    comparison_type: str = "exact"
) -> List[Dict]:
    """
    Re-rank schemes by how well they match the user's amount requirement.
    
    Schemes closest to user's requirement (but still meeting it) rank higher.
    
    Args:
        schemes: List of scheme dictionaries (already filtered)
        user_amount: User's required amount in lakhs
        comparison_type: "exact", "above", "below", or "range"
        
    Returns:
        Re-ranked list of schemes
    """
    if not schemes or not user_amount:
        return schemes
    
    def get_relevance_score(scheme: Dict) -> float:
        """
        Calculate relevance score. Lower score = better match.
        """
        scheme_max = parse_scheme_max_amount(scheme)
        
        if scheme_max is None:
            # Unknown amount - give it a neutral score
            return 1000
        
        if comparison_type in ["exact", "range"]:
            # For exact/range: prefer schemes closest to user's amount (but >= it)
            # Score = difference from user's amount
            # Schemes that are much larger than needed are less relevant
            if scheme_max >= user_amount:
                # Within 50% of user's amount is ideal
                ratio = scheme_max / user_amount
                if ratio <= 1.5:
                    return ratio - 1  # 0 to 0.5
                elif ratio <= 3:
                    return ratio  # 1.5 to 3
                else:
                    return ratio * 2  # Penalize very large schemes
            else:
                return 10000  # Should have been filtered out
                
        elif comparison_type == "above":
            # User wants large loans - prefer larger schemes
            if scheme_max >= user_amount:
                # Larger is better, but not too extreme
                return 1 / (scheme_max / user_amount)
            else:
                return 10000
                
        elif comparison_type == "below":
            # User wants within limit - prefer schemes using more of the limit
            if scheme_max <= user_amount:
                # Closer to the limit is better
                return user_amount - scheme_max
            else:
                return 10000
        
        return 1000
    
    # Sort by relevance score (ascending)
    ranked = sorted(schemes, key=get_relevance_score)
    
    # Log the ranking
    for i, scheme in enumerate(ranked[:5]):
        scheme_name = scheme.get('name', 'Unknown')
        scheme_max = parse_scheme_max_amount(scheme)
        logger.info(f"Rank {i+1}: {scheme_name} (offers: {scheme_max}L)")
    
    return ranked


def filter_and_rank_by_amount(
    schemes: List[Dict],
    user_query: str,
    min_results: int = 3,
    profile_exclusions: Optional[Dict] = None
) -> Tuple[List[Dict], Optional[float]]:
    """
    Main function to filter and re-rank schemes based on user's amount requirement.
    
    This is the primary entry point for amount-based filtering.
    Ensures at least min_results schemes are returned by supplementing with
    other schemes if not enough match the amount criteria.
    
    Note: Eligibility filtering (e.g., for existing businesses) should be done
    BEFORE calling this function in datastore_tools.py.
    
    Args:
        schemes: List of scheme dictionaries from search
        user_query: User's original search query
        min_results: Minimum number of schemes to return (default 3)
        profile_exclusions: Dict with user profile info (kept for compatibility)
        
    Returns:
        Tuple of (filtered_and_ranked_schemes, user_amount)
    """
    # Parse user's amount requirement
    user_amount, comparison_type = parse_user_amount_requirement(user_query)
    
    if user_amount is None:
        # No amount in query - return schemes as-is
        logger.info("No amount requirement in query, skipping amount filter")
        return schemes, None
    
    logger.info(f"Amount filter: user wants {user_amount}L ({comparison_type})")
    logger.info(f"Input schemes: {len(schemes)}")
    
    # Filter schemes by amount
    # Allow slightly lower max amounts for "exact" queries (tolerance),
    # so a 14L scheme can still be considered for a 15L requirement.
    try:
        from config.settings import settings
        lower_tol = float(getattr(settings, "loan_amount_lower_tolerance", 0.0) or 0.0)
    except Exception:
        lower_tol = 0.0

    filtered = filter_schemes_by_amount(
        schemes,
        user_amount,
        comparison_type,
        lower_tolerance=lower_tol,
    )
    logger.info(f"After amount filter: {len(filtered)} schemes")
    
    # Re-rank by relevance
    ranked = rank_schemes_by_amount_relevance(filtered, user_amount, comparison_type)
    
    # IMPORTANT: Ensure we have at least min_results schemes
    # If not enough schemes match the amount criteria, supplement with others
    if len(ranked) < min_results:
        logger.info(f"Only {len(ranked)} schemes match amount criteria, supplementing to reach {min_results}")
        
        # Get schemes that didn't make the cut (not in ranked list)
        ranked_ids = {s.get('id') or s.get('name') for s in ranked}
        supplemental = [s for s in schemes if (s.get('id') or s.get('name')) not in ranked_ids]
        
        # Sort supplemental by their max amount (higher = more relevant for loans)
        def get_amount_for_sort(scheme):
            amt = parse_scheme_max_amount(scheme)
            return amt if amt else 0
        
        supplemental_sorted = sorted(supplemental, key=get_amount_for_sort, reverse=True)
        
        # Add supplemental schemes until we reach min_results
        for scheme in supplemental_sorted:
            if len(ranked) >= min_results:
                break
            ranked.append(scheme)
            scheme_name = scheme.get('name', 'Unknown')
            scheme_max = parse_scheme_max_amount(scheme)
            logger.info(f"Added supplemental scheme: {scheme_name} (offers: {scheme_max}L)")
    
    return ranked, user_amount


def filter_new_business_only_schemes(schemes: List[Dict]) -> List[Dict]:
    """
    Filter out schemes that are only for NEW businesses when user has existing business.
    
    Args:
        schemes: List of scheme dictionaries
        
    Returns:
        Filtered list excluding "new business only" schemes
    """
    # Keywords that indicate a scheme is for NEW businesses only
    new_business_keywords = [
        'new enterprise', 'new business', 'first generation', 'first-generation',
        'new unit', 'greenfield', 'setting up new', 'start new', 'starting new',
        'new ventures', 'new project', 'pmegp', 'employment generation programme',
        'employment generation program'
    ]
    
    filtered = []
    for scheme in schemes:
        scheme_name = scheme.get('name', '').lower()
        scheme_desc = scheme.get('description', '').lower()
        benefit_summary = str(scheme.get('benefit_summary', '')).lower()
        eligibility = str(scheme.get('eligibility', '')).lower()
        
        # Check all text fields for new business keywords
        all_text = f"{scheme_name} {scheme_desc} {benefit_summary} {eligibility}"
        
        is_new_business_only = any(keyword in all_text for keyword in new_business_keywords)
        
        if is_new_business_only:
            logger.info(f"❌ Excluded scheme (new business only): {scheme.get('name')}")
        else:
            filtered.append(scheme)
    
    return filtered


def detect_amount_in_query(query: str) -> bool:
    """
    Quick check if query contains any amount-related terms.
    
    Args:
        query: User's search query
        
    Returns:
        True if query likely contains an amount requirement
    """
    if not query:
        return False
    
    query_lower = query.lower()
    
    # Amount-related patterns
    patterns = [
        r'\d+\s*(crores?|cr|lakhs?|lacs?|l|thousand|k)\b',  # "15 lakh"
        r'₹\s*\d+',  # "₹15"
        r'rs\.?\s*\d+',  # "Rs.15"
        r'\d{1,2},\d{2},\d{3}',  # Indian format "15,00,000"
        r'(above|below|upto|more than|less than)\s*\d+',  # "above 1 crore"
    ]
    
    for pattern in patterns:
        if re.search(pattern, query_lower):
            return True
    
    return False