"""
Common helper functions and utilities.
"""

import re
from typing import Dict, List, Any, Optional
from langdetect import detect, LangDetectException


def extract_location_info(text: str) -> Dict[str, Optional[str]]:
    """
    Extract location information from text.
    
    Args:
        text: Input text
        
    Returns:
        Dictionary with state, district, city information
    """
    # Indian state patterns
    states = {
        "maharashtra": ["maharashtra", "mh", "महाराष्ट्र"],
        "rajasthan": ["rajasthan", "rj", "राजस्थान"],
        "gujarat": ["gujarat", "gj", "गुजरात"],
        "punjab": ["punjab", "pb", "पंजाब"],
        "haryana": ["haryana", "hr", "हरियाणा"],
        "uttar pradesh": ["uttar pradesh", "up", "उत्तर प्रदेश"],
        "madhya pradesh": ["madhya pradesh", "mp", "मध्य प्रदेश"],
        "karnataka": ["karnataka", "ka", "कर्नाटक"],
        "tamil nadu": ["tamil nadu", "tn", "तमिलनाडु"],
        "andhra pradesh": ["andhra pradesh", "ap", "आंध्र प्रदेश"],
        "telangana": ["telangana", "tg", "तेलंगाना"],
        "west bengal": ["west bengal", "wb", "पश्चिम बंगाल"],
        "bihar": ["bihar", "br", "बिहार"],
        "odisha": ["odisha", "or", "ओडिशा"],
        "kerala": ["kerala", "kl", "केरल"],
    }
    
    text_lower = text.lower()
    location = {
        "state": None,
        "district": None,
        "city": None
    }
    
    # Find state
    for state, patterns in states.items():
        for pattern in patterns:
            if pattern in text_lower:
                location["state"] = state.title()
                break
        if location["state"]:
            break
    
    # Extract city/district (simplified - looks for capitalized words)
    words = text.split()
    for i, word in enumerate(words):
        if word[0].isupper() and len(word) > 3:
            if i > 0 and words[i-1].lower() in ["in", "at", "from", "near"]:
                location["city"] = word
                break
    
    return location


def extract_gender(text: str) -> Optional[str]:
    """
    Extract gender from text.
    
    Args:
        text: Input text
        
    Returns:
        "male", "female", or None
    """
    text_lower = text.lower()
    
    female_keywords = ["woman", "female", "lady", "महिला", "स्त्री", "பெண்", "మహిళ"]
    male_keywords = ["man", "male", "gentleman", "पुरुष", "आदमी", "ஆண்", "పురుషుడు"]
    
    for keyword in female_keywords:
        if keyword in text_lower:
            return "female"
    
    for keyword in male_keywords:
        if keyword in text_lower:
            return "male"
    
    return None


def extract_business_type(text: str) -> Optional[str]:
    """
    Extract business type from text.
    
    Args:
        text: Input text
        
    Returns:
        Business type or None
    """
    text_lower = text.lower()
    
    business_types = {
        "manufacturing": ["manufacturing", "production", "factory", "निर्माण"],
        "services": ["services", "consulting", "सेवा"],
        "trading": ["trading", "retail", "wholesale", "व्यापार"],
        "food_processing": ["food", "khakra", "snacks", "खाद्य प्रसंस्करण"],
        "textile": ["textile", "garment", "fabric", "कपड़ा"],
        "it": ["software", "it", "technology", "सूचना प्रौद्योगिकी"],
        "agriculture": ["agro", "agricultural", "कृषि"],
    }
    
    for biz_type, keywords in business_types.items():
        for keyword in keywords:
            if keyword in text_lower:
                return biz_type
    
    return None


def extract_crop_type(text: str) -> Optional[str]:
    """
    Extract crop type from text.
    
    Args:
        text: Input text
        
    Returns:
        Crop type or None
    """
    text_lower = text.lower()
    
    crops = {
        "wheat": ["wheat", "गेहूं"],
        "rice": ["rice", "paddy", "धान", "चावल"],
        "cotton": ["cotton", "कपास"],
        "sugarcane": ["sugarcane", "गन्ना"],
        "pulses": ["pulses", "lentils", "दाल"],
        "vegetables": ["vegetables", "सब्जी"],
        "fruits": ["fruits", "फल"],
        "millets": ["millet", "bajra", "jowar", "बाजरा"],
    }
    
    for crop, keywords in crops.items():
        for keyword in keywords:
            if keyword in text_lower:
                return crop
    
    return None


def extract_query_from_message(text: str) -> str:
    """
    Extract just the query part from a message with profile.
    
    Args:
        text: Full message text
        
    Returns:
        Query text only (after "Seller Query:" or full text if no profile)
    """
    if "Seller Query:" in text:
        # Extract only the query part
        parts = text.split("Seller Query:")
        if len(parts) > 1:
            return parts[1].strip()
    
    # If no profile section, return full text
    return text


def is_devanagari(text: str) -> bool:
    """
    Check if text contains Devanagari script (Hindi/Marathi).
    
    Args:
        text: Input text
        
    Returns:
        True if text has significant Devanagari content
    """
    if not text or len(text.strip()) == 0:
        return False
    
    # Count Devanagari characters (U+0900 to U+097F)
    devanagari_count = sum(1 for char in text if '\u0900' <= char <= '\u097F')
    total_chars = len([c for c in text if c.isalnum()])
    
    if total_chars == 0:
        return False
    
    # If more than 30% is Devanagari, consider it an Indian language
    devanagari_percentage = (devanagari_count / total_chars) * 100
    
    # For very short text (like "हाँ"), even one Devanagari character is enough
    if len(text.strip()) <= 5 and devanagari_count > 0:
        return True
    
    return devanagari_percentage > 30


def detect_language(text: str) -> str:
    """
    Detect language of text from query only (not profile).
    Enhanced to detect Devanagari script reliably for mid-conversation switches.
    
    Args:
        text: Input text (may include profile + query)
        
    Returns:
        Language code (default: "en")
    """
    # Extract just the query portion to avoid profile influencing detection
    query_text = extract_query_from_message(text)
    
    # First, check for Devanagari script (more reliable for short text like "हाँ")
    if is_devanagari(query_text):
        # Try to distinguish between Hindi and Marathi using langdetect
        try:
            lang = detect(query_text)
            if lang == "mr":
                return "mr"  # Marathi
            return "hi"  # Default to Hindi for Devanagari
        except LangDetectException:
            return "hi"  # Default to Hindi if detection fails
    
    # If no Devanagari, use langdetect
    try:
        lang = detect(query_text)
        # Map to supported languages
        if lang in ["hi", "mr", "gu", "ta", "te", "kn", "ml", "bn", "pa", "or"]:
            return lang
        return "en"
    except LangDetectException:
        return "en"


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Split a list into chunks.
    
    Args:
        lst: Input list
        chunk_size: Size of each chunk
        
    Returns:
        List of chunks
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def format_scheme_response(
    schemes: List[Dict[str, Any]],
    show_count: int = 3
) -> str:
    """
    Format schemes for display.
    
    Args:
        schemes: List of scheme dictionaries
        show_count: Number of schemes to show
        
    Returns:
        Formatted string
    """
    if not schemes:
        return "No schemes found matching your criteria."
    
    response_parts = []
    
    for i, scheme in enumerate(schemes[:show_count], 1):
        scheme_text = f"""**Scheme {i}: {scheme.get('name', 'Unknown')}**
📝 Benefit: {scheme.get('benefit', 'N/A')}
✅ Eligibility: {scheme.get('eligibility', 'N/A')}
"""
        response_parts.append(scheme_text)
    
    if len(schemes) > show_count:
        response_parts.append("\n💬 Would you like to see more schemes?")
    
    return "\n".join(response_parts)


def sanitize_input(text: str) -> str:
    """
    Sanitize user input by removing potentially harmful content.
    
    Args:
        text: Input text
        
    Returns:
        Sanitized text
    """
    # Remove any HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Remove any script tags
    text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Limit length
    if len(text) > 5000:
        text = text[:5000]
    
    return text.strip()


def validate_session_id(session_id: str) -> bool:
    """
    Validate session ID format.
    
    Args:
        session_id: Session identifier
        
    Returns:
        True if valid, False otherwise
    """
    # Session ID should be alphanumeric and reasonable length
    pattern = r'^[a-zA-Z0-9_-]{8,128}$'
    return bool(re.match(pattern, session_id))