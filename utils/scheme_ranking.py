"""
Scheme Ranking Logic for MSME Agent
====================================

This module provides scoring and ranking logic to show the most relevant 
schemes first based on user profile matching.

Integrates with existing amount_filter.py and profile_analyzer.py
"""

import re
from typing import Dict, List, Optional, Any, Tuple
from utils.logger import setup_logger

logger = setup_logger(__name__)


def parse_user_profile(profile_text: str) -> Dict[str, Any]:
    """
    Parse user profile text into structured data.
    
    Args:
        profile_text: Raw profile text from user
    
    Returns:
        Dictionary with parsed profile fields
    """
    profile = {
        'state': '',
        'constitution': '',
        'business_activities': [],
        'has_gstin': False,
        'has_udyam': False,
        'gender': '',
        'category': '',  # SC/ST/OBC/General
        'msme_category': '',  # Micro/Small/Medium
        'products': [],
        'business_name': ''
    }
    
    if not profile_text:
        return profile
    
    text = profile_text
    text_lower = text.lower()
    
    # Extract state
    state_match = re.search(r'based in (\w+)', text, re.IGNORECASE)
    if state_match:
        profile['state'] = state_match.group(1).strip().upper()
    
    # Extract constitution
    constitution_patterns = [
        (r'private limited company', 'Private Limited Company'),
        (r'pvt\.?\s*ltd', 'Private Limited Company'),
        (r'partnership', 'Partnership'),
        (r'proprietorship', 'Proprietorship'),
        (r'sole proprietor', 'Proprietorship'),
        (r'llp', 'LLP'),
        (r'limited liability partnership', 'LLP'),
        (r'one person company', 'One Person Company'),
        (r'opc', 'One Person Company'),
    ]
    for pattern, const_name in constitution_patterns:
        if re.search(pattern, text_lower):
            profile['constitution'] = const_name
            break
    
    # Extract business activities
    activities_match = re.search(r'engaged in ([^.]+?)(?:\s+and\s+offering|\s+offering|\.)', text, re.IGNORECASE)
    if activities_match:
        activities_str = activities_match.group(1)
        # Split by commas and clean up
        activities = [a.strip() for a in activities_str.split(',')]
        profile['business_activities'] = [a for a in activities if a]
    
    # Check for GSTIN
    if re.search(r'gstin[:\s]*\w+', text_lower) or 'gst registered' in text_lower:
        profile['has_gstin'] = True
    
    # Check for Udyam
    if re.search(r'udyam[:\s]*\w+', text_lower) or 'msme' in text_lower:
        profile['has_udyam'] = True
    
    # Extract products
    products_match = re.search(r'products across categories such as ([^.]+)', text, re.IGNORECASE)
    if products_match:
        products_str = products_match.group(1)
        products = [p.strip() for p in products_str.split(',')]
        profile['products'] = [p for p in products if p]
    
    # Extract business name
    name_match = re.search(r'business name ([^.]+?)(?:\.|and|,)', text, re.IGNORECASE)
    if name_match:
        profile['business_name'] = name_match.group(1).strip()
    
    # Check for gender indicators
    if any(word in text_lower for word in ['woman', 'women', 'female', 'mahila']):
        profile['gender'] = 'female'
    
    # Check for category (SC/ST/OBC)
    if any(word in text_lower for word in ['scheduled caste', ' sc ', 'sc/']):
        profile['category'] = 'SC'
    elif any(word in text_lower for word in ['scheduled tribe', ' st ', '/st']):
        profile['category'] = 'ST'
    elif 'obc' in text_lower:
        profile['category'] = 'OBC'
    
    logger.info(f"Parsed profile: state={profile['state']}, constitution={profile['constitution']}, "
                f"activities={profile['business_activities']}, has_gstin={profile['has_gstin']}, "
                f"has_udyam={profile['has_udyam']}")
    
    return profile


def calculate_scheme_score(
    scheme: Dict[str, Any],
    user_profile: Dict[str, Any],
    query_params: Dict[str, Any]
) -> Tuple[int, List[str]]:
    """
    Calculate a relevance score for a scheme based on user profile match.
    
    Args:
        scheme: Scheme data from datastore
        user_profile: Parsed user profile information
        query_params: Query parameters (loan_amount, query type, state, etc.)
    
    Returns:
        Tuple of (Integer score, List of match reasons)
    """
    score = 0
    match_reasons = []
    
    # Get scheme fields (handle both naming conventions)
    scheme_states = str(scheme.get('name_of_state', scheme.get('state', ''))).upper()
    scheme_type = str(scheme.get('service_type', '')).lower()
    eligibility = str(scheme.get('eligibility_criteria', scheme.get('eligibility', ''))).lower()
    scheme_name = scheme.get('name', '').lower()
    benefit_summary = str(scheme.get('benefit_summary', '')).lower()
    beneficiary_type = str(scheme.get('beneficiary_type', '')).lower()
    
    # If eligibility_criteria is a dict, convert to string
    if isinstance(eligibility, dict):
        eligibility = str(eligibility).lower()
    
    # 1. STATE MATCH (+25 points)
    user_state = user_profile.get('state', '') or query_params.get('state', '')
    user_state = user_state.upper() if user_state else ''
    
    if user_state:
        if (user_state in scheme_states or 
            'all india' in scheme_states.lower() or 
            'pan india' in scheme_states.lower() or
            not scheme_states):  # Empty means all states
            score += 25
            match_reasons.append(f"State: {user_state} ✓")
    
    # 2. SERVICE TYPE MATCH (+20 points)
    requested_type = query_params.get('query', '').lower()
    
    type_keywords = {
        'loan': ['loan', 'credit', 'finance', 'lending', 'mudra', 'cgtmse'],
        'subsidy': ['subsidy', 'grant', 'assistance', 'reimbursement'],
        'training': ['training', 'skill', 'development', 'capacity building'],
        'export': ['export', 'marketing', 'trade', 'international', 'rcmc', 'mda'],
    }
    
    for req_type, keywords in type_keywords.items():
        if req_type in requested_type:
            # Check scheme_type field
            if any(kw in scheme_type for kw in keywords):
                score += 20
                match_reasons.append(f"Type: {req_type} ✓")
                break
            # Also check scheme name and benefit summary
            if any(kw in scheme_name or kw in benefit_summary for kw in keywords):
                score += 15  # Slightly lower for indirect match
                match_reasons.append(f"Type: {req_type} (indirect) ✓")
                break
    
    # 3. BUSINESS ACTIVITY MATCH (+15 points)
    user_activities = user_profile.get('business_activities', [])
    
    activity_keywords = {
        'export': ['exporter', 'export', 'foreign trade'],
        'import': ['importer', 'import'],
        'manufacturing': ['manufacturer', 'manufacturing', 'production'],
        'retail': ['retail', 'retailer', 'shop'],
        'wholesale': ['wholesale', 'wholesaler', 'distributor'],
        'service': ['service', 'services', 'provider'],
    }
    
    for activity in user_activities:
        activity_lower = activity.lower()
        for act_type, keywords in activity_keywords.items():
            if act_type in activity_lower:
                # Check if scheme requires or benefits this activity
                if any(kw in eligibility or kw in beneficiary_type for kw in keywords):
                    score += 15
                    match_reasons.append(f"Activity: {act_type} ✓")
                    break
    
    # 4. CONSTITUTION MATCH (+10 points)
    user_constitution = user_profile.get('constitution', '').lower()
    
    if user_constitution:
        # Most schemes accept all constitutions unless specified otherwise
        constitution_restrictions = ['only proprietorship', 'only individual', 'only partnership']
        is_restricted = any(restr in eligibility for restr in constitution_restrictions)
        
        if not is_restricted:
            score += 10
            match_reasons.append("Constitution: Compatible ✓")
        else:
            # Check if user's constitution matches the restriction
            if user_constitution in eligibility:
                score += 10
                match_reasons.append(f"Constitution: {user_constitution} ✓")
    
    # 5. MSME CATEGORY MATCH (+10 points)
    user_category = user_profile.get('msme_category', '').lower()
    
    if user_category:
        if (user_category in eligibility or 
            'all msme' in eligibility or 
            'micro, small' in eligibility or
            'msme' in eligibility):
            score += 10
            match_reasons.append(f"MSME Category: {user_category} ✓")
    else:
        # If user has MSME registration (Udyam), assume they qualify
        if user_profile.get('has_udyam'):
            score += 5
            match_reasons.append("MSME Registered ✓")
    
    # 6. SPECIAL CATEGORY BONUS (+10 points)
    user_gender = user_profile.get('gender', '') or query_params.get('gender', '')
    
    if user_gender and user_gender.lower() == 'female':
        women_keywords = ['women', 'woman', 'female', 'mahila', 'ladies']
        if any(kw in eligibility or kw in beneficiary_type or kw in scheme_name for kw in women_keywords):
            score += 10
            match_reasons.append("Women Entrepreneur Scheme ✓")
    
    user_social_category = user_profile.get('category', '')
    if user_social_category in ['SC', 'ST']:
        if any(kw in eligibility for kw in ['sc/st', 'sc', 'st', 'scheduled']):
            score += 10
            match_reasons.append(f"{user_social_category} Category Benefit ✓")
    
    # 7. EXISTING BUSINESS ELIGIBLE (+5 points, -100 if not eligible)
    is_existing = user_profile.get('has_gstin') or user_profile.get('has_udyam')
    
    if is_existing:
        new_business_keywords = [
            'new enterprise', 'first time', 'new business', 'startup',
            'greenfield', 'not commenced', 'pmegp', 'first generation'
        ]
        
        is_new_only = any(kw in eligibility or kw in scheme_name for kw in new_business_keywords)
        
        if is_new_only:
            score -= 100  # Major penalty - effectively excludes
            match_reasons.append("❌ New Business Only")
        else:
            score += 5
            match_reasons.append("Existing Business OK ✓")
    
    return score, match_reasons


def rank_schemes_by_relevance(
    schemes: List[Dict[str, Any]],
    user_profile_text: str,
    query_params: Dict[str, Any],
    exclude_schemes: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Rank schemes by relevance score based on user profile matching.
    
    Args:
        schemes: List of scheme dictionaries from search
        user_profile_text: Raw user profile text
        query_params: Query parameters (query, loan_amount, state, gender, etc.)
        exclude_schemes: List of scheme names to exclude
    
    Returns:
        List of schemes sorted by relevance score (highest first)
    """
    if not schemes:
        return schemes
    
    # Parse user profile
    user_profile = parse_user_profile(user_profile_text)
    
    # Also use query params to fill in missing profile data
    if not user_profile['state'] and query_params.get('state'):
        user_profile['state'] = query_params['state']
    if not user_profile['gender'] and query_params.get('gender'):
        user_profile['gender'] = query_params['gender']
    
    # Filter out excluded schemes
    exclude_set = set(s.lower().strip() for s in (exclude_schemes or []))
    filtered_schemes = [
        s for s in schemes 
        if s.get('name', '').lower().strip() not in exclude_set
    ]
    
    # Calculate scores
    scored_schemes = []
    for scheme in filtered_schemes:
        score, reasons = calculate_scheme_score(scheme, user_profile, query_params)
        
        scheme_copy = scheme.copy()
        scheme_copy['_relevance_score'] = score
        scheme_copy['_match_reasons'] = reasons
        scored_schemes.append(scheme_copy)
        
        logger.debug(f"Scheme '{scheme.get('name')}': Score={score}, Reasons={reasons}")
    
    # Sort by score (highest first)
    scored_schemes.sort(key=lambda x: x.get('_relevance_score', 0), reverse=True)
    
    # Log top results
    logger.info("=== Relevance Ranking Results ===")
    for i, scheme in enumerate(scored_schemes[:5]):
        logger.info(f"  {i+1}. {scheme.get('name', 'Unknown')} "
                   f"(Score: {scheme.get('_relevance_score', 0)}) "
                   f"Reasons: {scheme.get('_match_reasons', [])}")
    
    return scored_schemes


def get_top_relevant_schemes(
    schemes: List[Dict[str, Any]],
    user_profile_text: str,
    query_params: Dict[str, Any],
    count: int = 3,
    exclude_schemes: Optional[List[str]] = None,
    min_score: int = 0
) -> List[Dict[str, Any]]:
    """
    Get top N most relevant schemes.
    
    Args:
        schemes: List of scheme dictionaries
        user_profile_text: Raw user profile text
        query_params: Query parameters
        count: Number of schemes to return
        exclude_schemes: List of scheme names to exclude
        min_score: Minimum score threshold (schemes below this are deprioritized)
    
    Returns:
        Top N schemes sorted by relevance
    """
    ranked = rank_schemes_by_relevance(
        schemes, 
        user_profile_text, 
        query_params, 
        exclude_schemes
    )
    
    # Filter out schemes with very low scores (likely ineligible)
    # But keep at least 'count' schemes
    eligible = [s for s in ranked if s.get('_relevance_score', 0) >= min_score]
    
    if len(eligible) >= count:
        return eligible[:count]
    else:
        # Include some lower-scored schemes if not enough high-scoring ones
        return ranked[:count]


def classify_scheme_type(scheme: Dict[str, Any]) -> str:
    """
    Classify a scheme as Central or State based on scheme_type field.
    
    Args:
        scheme: Scheme dictionary
    
    Returns:
        "Central" or "State" or "Other"
    """
    scheme_type = str(scheme.get('scheme_type', '')).lower()
    
    if 'central' in scheme_type:
        return 'Central'
    elif 'state' in scheme_type:
        return 'State'
    else:
        # Try to infer from other fields
        name = str(scheme.get('name', '')).lower()
        states_of_india = ['maharashtra', 'karnataka', 'tamil nadu', 'kerala', 
                          'andhra', 'telangana', 'gujarat', 'rajasthan', 
                          'uttar pradesh', 'madhya pradesh', 'bihar', 'haryana',
                          'punjab', 'west bengal', 'odisha', 'assam']
        
        for state in states_of_india:
            if state in name:
                return 'State'
        
        # Check if it mentions central keywords
        central_keywords = ['pm ', 'pradhan mantri', 'national', 'india', 'cgtmse', 'mudra']
        for keyword in central_keywords:
            if keyword in name:
                return 'Central'
        
        return 'Other'


def group_schemes_by_type(schemes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group schemes by Central/State type.
    
    Args:
        schemes: List of scheme dictionaries
    
    Returns:
        Dictionary with 'central', 'state', 'other' keys containing grouped schemes
    """
    grouped = {
        'central': [],
        'state': [],
        'other': []
    }
    
    for scheme in schemes:
        scheme_category = classify_scheme_type(scheme)
        
        if scheme_category == 'Central':
            grouped['central'].append(scheme)
        elif scheme_category == 'State':
            grouped['state'].append(scheme)
        else:
            grouped['other'].append(scheme)
    
    return grouped


def get_schemes_grouped_by_type(
    schemes: List[Dict[str, Any]],
    user_profile_text: str,
    query_params: Dict[str, Any],
    count: int = 3,
    exclude_schemes: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Get top schemes grouped by Central/State type.
    
    Args:
        schemes: List of scheme dictionaries
        user_profile_text: Raw user profile text
        query_params: Query parameters
        count: Total number of schemes to return
        exclude_schemes: List of scheme names to exclude
    
    Returns:
        Dictionary with grouped schemes and metadata
    """
    # First rank all schemes
    ranked = rank_schemes_by_relevance(
        schemes, 
        user_profile_text, 
        query_params, 
        exclude_schemes
    )
    
    # Group by type
    grouped = group_schemes_by_type(ranked)
    
    # Select top schemes prioritizing Central first, then State
    selected = []
    
    # Add Central schemes first
    for scheme in grouped['central']:
        if len(selected) < count:
            selected.append(scheme)
    
    # Then add State schemes
    for scheme in grouped['state']:
        if len(selected) < count:
            selected.append(scheme)
    
    # Then add Other if still needed
    for scheme in grouped['other']:
        if len(selected) < count:
            selected.append(scheme)
    
    return {
        'schemes': selected,
        'grouped': {
            'central': [s for s in selected if classify_scheme_type(s) == 'Central'],
            'state': [s for s in selected if classify_scheme_type(s) == 'State'],
            'other': [s for s in selected if classify_scheme_type(s) == 'Other']
        },
        'total_central': len(grouped['central']),
        'total_state': len(grouped['state']),
        'total_other': len(grouped['other'])
    }


def format_department_info(scheme: Dict[str, Any]) -> str:
    """
    Format department/agency information for display.
    
    Args:
        scheme: Scheme dictionary
    
    Returns:
        Formatted department string
    """
    department = scheme.get('department_agency', [])
    
    if isinstance(department, list) and department:
        # Return first department (usually the primary one)
        return department[0] if department else ''
    elif isinstance(department, str):
        return department
    
    return ''