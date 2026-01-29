"""
Tools for extracting and enriching user context from conversations.
"""

from typing import Dict, Any, Optional
from utils.helpers import (
    extract_location_info,
    extract_gender,
    extract_business_type,
    extract_crop_type,
    detect_language,
)
from utils.logger import setup_logger

logger = setup_logger(__name__)


def extract_user_context(message: str, existing_context: str = "{}") -> str:
    """
    Extract user context from a message.
    
    This tool analyzes user messages to extract demographic and profile information
    such as location, gender, business type, crop type, etc. It merges with existing
    context to build a comprehensive user profile.
    
    Args:
        message: User's message text
        existing_context: Previously extracted context as JSON string (optional)
        
    Returns:
        JSON string containing extracted context with fields like location, gender,
        business_type, crop_type, language, and raw_message
    """
    import json
    
    # Parse existing context
    try:
        context = json.loads(existing_context) if existing_context != "{}" else {}
    except:
        context = {}
    
    # Extract location
    location = extract_location_info(message)
    if any(location.values()):
        context["location"] = location
    
    # Extract gender
    gender = extract_gender(message)
    if gender:
        context["gender"] = gender
    
    # Extract business type (for MSME)
    business_type = extract_business_type(message)
    if business_type:
        context["business_type"] = business_type
    
    # Extract crop type (for farmers)
    crop_type = extract_crop_type(message)
    if crop_type:
        context["crop_type"] = crop_type
    
    # Detect language
    language = detect_language(message)
    context["language"] = language
    
    # Store raw message for reference
    context["raw_message"] = message
    
    logger.info(f"Extracted context: {context}")
    
    return json.dumps(context)


def classify_user_persona(message: str, context: str = "{}") -> str:
    """
    Classify user as farmer or MSME based on their message and context.
    
    This tool determines whether a user is a farmer or MSME/business owner
    based on keywords and context from their messages.
    
    Args:
        message: User's message text
        context: Additional context information as JSON string (optional)
        
    Returns:
        JSON string with persona classification: {"persona": "farmer"|"msme"|"unclear", 
        "confidence": "high"|"medium"|"low", "reasoning": "explanation"}
    """
    import json
    
    # Parse context
    try:
        context_dict = json.loads(context) if context != "{}" else {}
    except:
        context_dict = {}
    
    message_lower = message.lower()
    
    # Farmer keywords
    farmer_keywords = [
        "farmer", "farming", "farm", "agriculture", "crop", "land",
        "किसान", "खेती", "कृषि", "फसल",
        "wheat", "rice", "cotton", "sugarcane",
        "गेहूं", "धान", "कपास", "गन्ना",
        "livestock", "cattle", "dairy", "पशुपालन"
    ]
    
    # MSME/Business keywords
    msme_keywords = [
        "business", "msme", "enterprise", "company", "startup",
        "व्यवसाय", "उद्यम", "कंपनी",
        "manufacturing", "services", "trading", "retail",
        "निर्माण", "सेवा", "व्यापार",
        "shop", "store", "factory", "दुकान", "फैक्टरी"
    ]
    
    farmer_score = sum(1 for kw in farmer_keywords if kw in message_lower)
    msme_score = sum(1 for kw in msme_keywords if kw in message_lower)
    
    # Check context for additional signals
    if context_dict:
        if context_dict.get("crop_type"):
            farmer_score += 2
        if context_dict.get("business_type"):
            msme_score += 2
    
    # Classify
    result = {}
    if farmer_score > msme_score and farmer_score > 0:
        confidence = "high" if farmer_score >= 2 else "medium"
        result = {
            "persona": "farmer",
            "confidence": confidence,
            "reasoning": f"Found {farmer_score} farmer-related keywords"
        }
    elif msme_score > farmer_score and msme_score > 0:
        confidence = "high" if msme_score >= 2 else "medium"
        result = {
            "persona": "msme",
            "confidence": confidence,
            "reasoning": f"Found {msme_score} business-related keywords"
        }
    else:
        result = {
            "persona": "unclear",
            "confidence": "low",
            "reasoning": "Could not determine persona from message"
        }
    
    return json.dumps(result)


def enrich_farmer_context(
    current_context: Dict[str, Any],
    message: str
) -> Dict[str, Any]:
    """
    Enrich farmer-specific context from conversation.
    
    This tool extracts and adds farmer-specific information like land size,
    farming practices, crop types, and farmer category.
    
    Args:
        current_context: Current user context
        message: Latest user message
        
    Returns:
        Enriched context dictionary with farmer-specific fields
    """
    context = current_context.copy()
    message_lower = message.lower()
    
    # Extract land size
    land_keywords = {
        "small": ["small", "2 acre", "1 acre", "marginal", "छोटा"],
        "medium": ["5 acre", "10 acre", "medium", "मध्यम"],
        "large": ["large", "20 acre", "50 acre", "बड़ा"]
    }
    
    for category, keywords in land_keywords.items():
        for keyword in keywords:
            if keyword in message_lower:
                context["farmer_category"] = category
                break
    
    # Extract farming type
    if "organic" in message_lower:
        context["farming_type"] = "organic"
    elif "traditional" in message_lower:
        context["farming_type"] = "traditional"
    
    # Extract income range
    income_patterns = {
        "low": ["50000", "1 lakh", "कम आय"],
        "medium": ["2 lakh", "5 lakh", "मध्यम आय"],
        "high": ["10 lakh", "20 lakh", "अधिक आय"]
    }
    
    for range_type, patterns in income_patterns.items():
        for pattern in patterns:
            if pattern in message_lower:
                context["income_range"] = range_type
                break
    
    return context


def enrich_msme_context(
    current_context: Dict[str, Any],
    message: str
) -> Dict[str, Any]:
    """
    Enrich MSME-specific context from conversation.
    
    This tool extracts and adds MSME-specific information like enterprise size,
    turnover, number of employees, and industry sector.
    
    Args:
        current_context: Current user context
        message: Latest user message
        
    Returns:
        Enriched context dictionary with MSME-specific fields
    """
    context = current_context.copy()
    message_lower = message.lower()
    
    # Extract enterprise size
    size_keywords = {
        "micro": ["micro", "small business", "home-based", "सूक्ष्म"],
        "small": ["small enterprise", "छोटा उद्यम"],
        "medium": ["medium enterprise", "मध्यम उद्यम"]
    }
    
    for size, keywords in size_keywords.items():
        for keyword in keywords:
            if keyword in message_lower:
                context["enterprise_size"] = size
                break
    
    # Extract employee count
    if "employee" in message_lower or "worker" in message_lower:
        import re
        numbers = re.findall(r'\d+', message_lower)
        if numbers:
            emp_count = int(numbers[0])
            context["employee_count"] = emp_count
            
            # Determine size from employee count
            if emp_count < 10:
                context["enterprise_size"] = "micro"
            elif emp_count < 50:
                context["enterprise_size"] = "small"
            else:
                context["enterprise_size"] = "medium"
    
    # Extract turnover
    turnover_keywords = {
        "micro": ["25 lakh", "50 lakh", "1 crore"],
        "small": ["5 crore", "10 crore"],
        "medium": ["50 crore", "100 crore"]
    }
    
    for size, keywords in turnover_keywords.items():
        for keyword in keywords:
            if keyword in message_lower:
                context["turnover_range"] = size
                break
    
    # Extract industry sector
    sectors = {
        "manufacturing": ["manufacturing", "production", "factory"],
        "services": ["services", "consulting", "agency"],
        "trading": ["trading", "retail", "wholesale"],
        "it": ["software", "it", "technology"],
    }
    
    for sector, keywords in sectors.items():
        for keyword in keywords:
            if keyword in message_lower:
                context["industry_sector"] = sector
                break
    
    return context


def get_missing_context_questions(
    persona: str,
    current_context: Dict[str, Any]
) -> str:
    """
    Generate questions to fill missing context.
    
    This tool identifies what context is missing for a user profile
    and generates an appropriate question to gather that information.
    
    Args:
        persona: User persona ("farmer" or "msme")
        current_context: Current context dictionary
        
    Returns:
        A question to ask the user, or empty string if context is complete
    """
    if persona == "farmer":
        # Check farmer context
        if not current_context.get("location", {}).get("state"):
            return "Which state are you farming in?"
        
        if not current_context.get("crop_type"):
            return "What crops do you grow?"
        
        if not current_context.get("farmer_category"):
            return "How much land do you have? (e.g., 2 acres, 10 acres)"
        
        if not current_context.get("gender"):
            return "Are you a male or female farmer? (This helps find specific schemes)"
    
    elif persona == "msme":
        # Check MSME context
        if not current_context.get("location", {}).get("state"):
            return "Which state is your business located in?"
        
        if not current_context.get("business_type"):
            return "What type of business do you run?"
        
        if not current_context.get("enterprise_size"):
            return "How many employees do you have?"
        
        if not current_context.get("gender"):
            return "Are you a male or female entrepreneur? (This helps find women-specific schemes)"
    
    return ""  # Context is complete
