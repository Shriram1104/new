"""
Progressive disclosure tools for showing schemes in paginated format.
"""

from typing import Dict, List, Any, Tuple
from config.settings import settings
from utils.helpers import chunk_list, format_scheme_response
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ProgressiveDisclosureManager:
    """Manager for progressive disclosure of schemes."""
    
    def __init__(self, schemes_per_page: int = None):
        """
        Initialize progressive disclosure manager.
        
        Args:
            schemes_per_page: Number of schemes to show per page
        """
        self.schemes_per_page = schemes_per_page or settings.schemes_per_page
        self.max_pages = settings.max_scheme_pages
    
    def paginate_schemes(
        self,
        schemes: List[Dict[str, Any]],
        page: int = 0
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Get a page of schemes.
        
        Args:
            schemes: Full list of schemes
            page: Page number (0-indexed)
            
        Returns:
            Tuple of (schemes_on_page, pagination_info)
        """
        total_schemes = len(schemes)
        total_pages = min(
            (total_schemes + self.schemes_per_page - 1) // self.schemes_per_page,
            self.max_pages
        )
        
        # Validate page number
        if page < 0 or page >= total_pages:
            page = 0
        
        # Get schemes for this page
        start_idx = page * self.schemes_per_page
        end_idx = start_idx + self.schemes_per_page
        page_schemes = schemes[start_idx:end_idx]
        
        # Build pagination info
        pagination_info = {
            "current_page": page,
            "total_pages": total_pages,
            "schemes_per_page": self.schemes_per_page,
            "total_schemes": total_schemes,
            "has_next": page < total_pages - 1,
            "has_previous": page > 0,
            "schemes_shown": len(page_schemes),
            "total_shown_so_far": end_idx
        }
        
        return page_schemes, pagination_info
    
    def format_page_response(
        self,
        schemes: List[Dict[str, Any]],
        pagination_info: Dict[str, Any],
        language: str = "en"
    ) -> str:
        """
        Format a page of schemes as a response.
        
        Args:
            schemes: Schemes on current page
            pagination_info: Pagination metadata
            language: Response language
            
        Returns:
            Formatted response string
        """
        response_parts = []
        
        # Add schemes
        for i, scheme in enumerate(schemes, 1):
            global_idx = (pagination_info["current_page"] * 
                         pagination_info["schemes_per_page"] + i)
            
            scheme_text = self._format_single_scheme(scheme, global_idx, language)
            response_parts.append(scheme_text)
        
        # Add pagination prompt
        if pagination_info["has_next"]:
            prompt = self._get_more_prompt(language)
            response_parts.append(prompt)
        else:
            # No more schemes
            end_msg = self._get_end_message(
                pagination_info["total_schemes"],
                language
            )
            response_parts.append(end_msg)
        
        return "\n\n".join(response_parts)
    
    def _format_single_scheme(
        self,
        scheme: Dict[str, Any],
        index: int,
        language: str
    ) -> str:
        """Format a single scheme."""
        name = scheme.get("name", "Unknown Scheme")
        benefit = scheme.get("benefit", "Information not available")
        eligibility = scheme.get("eligibility", "Contact scheme office for details")
        
        if language == "hi":
            return f"""**योजना {index}: {name}**
📝 लाभ: {benefit}
✅ पात्रता: {eligibility}"""
        else:
            return f"""**Scheme {index}: {name}**
📝 Benefit: {benefit}
✅ Eligibility: {eligibility}"""
    
    def _get_more_prompt(self, language: str) -> str:
        """Get prompt for showing more schemes."""
        if language == "hi":
            return '📋 अधिक योजनाएँ उपलब्ध हैं! अतिरिक्त विकल्प देखने के लिए "show more" लिखें।'
        else:
            return '📋 More schemes are available! Type "show more" to see additional options.'
    
    def _get_end_message(self, total_count: int, language: str) -> str:
        """Get end of schemes message."""
        if language == "hi":
            return "✅ यही सभी योजनाएँ हैं जो आपकी प्रोफ़ाइल से मेल खाती हैं।"
        else:
            return "✅ These are all the schemes matching your profile."


def manage_scheme_pagination(
    schemes: List[Dict[str, Any]],
    current_page: int,
    session_state: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Manage progressive disclosure of schemes across conversation turns.
    
    This tool handles pagination state across conversation turns, ensuring
    users see 3 schemes at a time and can request more progressively.
    
    Args:
        schemes: Full list of schemes to paginate
        current_page: Current page number (0-indexed)
        session_state: Session state dictionary
        
    Returns:
        Dictionary with:
            - schemes_to_show: Schemes for current page
            - pagination: Pagination metadata
            - formatted_response: Formatted text response
    """
    manager = ProgressiveDisclosureManager()
    
    # Get current page
    page_schemes, pagination_info = manager.paginate_schemes(schemes, current_page)
    
    # Get language from session
    language = session_state.get("language", "en")
    
    # Format response
    formatted = manager.format_page_response(page_schemes, pagination_info, language)
    
    # Store pagination state in session
    session_state["current_page"] = current_page
    session_state["total_schemes"] = len(schemes)
    session_state["all_schemes"] = schemes  # Store for next page request
    
    logger.info(f"Showing page {current_page + 1}, {len(page_schemes)} schemes")
    
    return {
        "schemes_to_show": page_schemes,
        "pagination": pagination_info,
        "formatted_response": formatted
    }


def handle_more_request(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle user request to see more schemes.
    
    This tool is called when user says "yes", "show more", "more schemes", etc.
    It advances to the next page of schemes.
    
    Args:
        session_state: Session state containing pagination info
        
    Returns:
        Dictionary with next page of schemes
    """
    # Get stored schemes and current page
    all_schemes = session_state.get("all_schemes", [])
    current_page = session_state.get("current_page", 0)
    
    if not all_schemes:
        return {
            "error": "No schemes available",
            "message": "Please search for schemes first."
        }
    
    # Advance to next page
    next_page = current_page + 1
    
    return manage_scheme_pagination(all_schemes, next_page, session_state)


def handle_scheme_query(
    scheme_reference: str,
    session_state: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Handle queries about previously shown schemes.
    
    This tool identifies which scheme the user is referring to and retrieves
    its full details. Handles references like "the first scheme", "scheme 2",
    "PM-KISAN", etc.
    
    Args:
        scheme_reference: How user referred to the scheme
        session_state: Session state with shown schemes
        
    Returns:
        Dictionary with scheme details
    """
    all_schemes = session_state.get("all_schemes", [])
    
    if not all_schemes:
        return {
            "error": "No schemes in context",
            "message": "Please search for schemes first."
        }
    
    # Try to parse scheme number
    import re
    numbers = re.findall(r'\d+', scheme_reference)
    
    if numbers:
        # User referred to scheme by number
        scheme_num = int(numbers[0]) - 1  # Convert to 0-indexed
        if 0 <= scheme_num < len(all_schemes):
            return {
                "scheme": all_schemes[scheme_num],
                "found": True
            }
    
    # Try to match by name
    reference_lower = scheme_reference.lower()
    for scheme in all_schemes:
        if reference_lower in scheme.get("name", "").lower():
            return {
                "scheme": scheme,
                "found": True
            }
    
    # Default to most recently mentioned scheme
    current_page = session_state.get("current_page", 0)
    schemes_per_page = settings.schemes_per_page
    
    # Get the first scheme from current page
    start_idx = current_page * schemes_per_page
    if start_idx < len(all_schemes):
        return {
            "scheme": all_schemes[start_idx],
            "found": True,
            "note": "Referring to the most recently discussed scheme"
        }
    
    return {
        "error": "Could not identify scheme",
        "message": "Please specify which scheme you're asking about."
    }
