"""
Enhanced profile analyzer to extract existing schemes and registrations.
This helps avoid showing schemes the user has already benefited from.
"""

import re
from typing import Dict, List, Set, Optional
from utils.logger import setup_logger

logger = setup_logger(__name__)


class UserProfileAnalyzer:
    """Analyzes user profile to extract existing schemes and registrations."""
    
    # Mapping of user profile indicators to scheme keywords to exclude
    EXCLUSION_MAPPING = {
        # Registration-related
        "udyam": {
            "keywords": ["udyam registration scheme", "msme registration scheme", "how to register udyam", "apply for udyam"],
            "reason": "User already has Udyam registration"
        },
        "gstin": {
            "keywords": ["gst registration scheme", "gst registration process", "how to register for gst", "apply for gst"],
            "reason": "User already has GST registration"
        },
        "import_export_code": {
            "keywords": ["iec registration", "import export code"],
            "reason": "User already has IEC"
        },
        "trade_license": {
            "keywords": ["trade license registration"],
            "reason": "User already has trade license"
        },
        "shop_establishment": {
            "keywords": ["shop and establishment registration", "shop act"],
            "reason": "User already has Shop & Establishment registration"
        },
        "fssai": {
            "keywords": ["fssai registration", "food license"],
            "reason": "User already has FSSAI license"
        },
        
        # Business status indicators
        "existing_business": {
            "keywords": ["startup scheme", "new business setup", "starting a business"],
            "reason": "User has an existing business"
        },
        "registered_business": {
            "keywords": ["company registration scheme", "business registration process"],
            "reason": "User's business is already registered"
        },
        
        # Loan/Credit related
        "mudra_loan": {
            "keywords": ["mudra loan", "pradhan mantri mudra yojana"],
            "reason": "User already has MUDRA loan"
        },
        "stand_up_india": {
            "keywords": ["stand-up india"],
            "reason": "User already benefited from Stand-Up India"
        },
        
        # Training/Certification
        "skill_training": {
            "keywords": ["skill training", "skill development program"],
            "reason": "User already completed skill training"
        },
    }
    
    def __init__(self):
        """Initialize profile analyzer."""
        self.existing_registrations: Set[str] = set()
        self.excluded_keywords: Set[str] = set()
        self.exclusion_reasons: List[str] = []
    
    def analyze_profile(self, profile_text: str) -> Dict[str, any]:
        """
        Analyze user profile to identify existing schemes/registrations.
        
        Args:
            profile_text: User's profile description
            
        Returns:
            Dictionary with analysis results
        """
        profile_lower = profile_text.lower()
        
        # Extract Udyam registration
        if self._has_udyam_registration(profile_text):
            self._add_exclusion("udyam")
        
        # Extract GST registration
        if self._has_gst_registration(profile_text):
            self._add_exclusion("gstin")
        
        # Extract Import-Export Code
        if self._has_iec(profile_text):
            self._add_exclusion("import_export_code")
        
        # Check if business is already registered/existing
        if self._is_existing_business(profile_text):
            self._add_exclusion("existing_business")
            self._add_exclusion("registered_business")
        
        # Extract trade license
        if self._has_trade_license(profile_text):
            self._add_exclusion("trade_license")
        
        # Extract Shop & Establishment registration
        if self._has_shop_establishment(profile_text):
            self._add_exclusion("shop_establishment")
        
        # Extract FSSAI
        if self._has_fssai(profile_text):
            self._add_exclusion("fssai")
        
        # Extract loan history (if mentioned)
        if self._has_mudra_loan(profile_text):
            self._add_exclusion("mudra_loan")
        
        if self._has_stand_up_india(profile_text):
            self._add_exclusion("stand_up_india")
        
        # Extract training/certification history
        if self._has_skill_training(profile_text):
            self._add_exclusion("skill_training")
        
        logger.info(f"Profile analysis complete. Found {len(self.existing_registrations)} existing registrations")
        logger.info(f"Excluded keywords: {self.excluded_keywords}")
        
        # CRITICAL: If user has GSTIN or Udyam, they HAVE an existing business!
        has_udyam = "udyam" in self.existing_registrations
        has_gstin = "gstin" in self.existing_registrations
        is_existing = "existing_business" in self.existing_registrations or has_udyam or has_gstin
        
        if is_existing and "existing_business" not in self.existing_registrations:
            self._add_exclusion("existing_business")
            self._add_exclusion("registered_business")
            logger.info("Marked as existing business due to GSTIN/Udyam registration")
        
        return {
            "existing_registrations": list(self.existing_registrations),
            "excluded_keywords": list(self.excluded_keywords),
            "exclusion_reasons": self.exclusion_reasons,
            "has_udyam": has_udyam,
            "has_gstin": has_gstin,
            "is_existing_business": is_existing,
        }
    
    def _add_exclusion(self, registration_type: str):
        """Add exclusion based on registration type."""
        if registration_type in self.EXCLUSION_MAPPING:
            self.existing_registrations.add(registration_type)
            mapping = self.EXCLUSION_MAPPING[registration_type]
            self.excluded_keywords.update(mapping["keywords"])
            self.exclusion_reasons.append(mapping["reason"])
    
    def _has_udyam_registration(self, text: str) -> bool:
        """Check if user has Udyam registration."""
        # More flexible patterns to catch variations
        udyam_patterns = [
            # Standard format: "Udyam No: UDYAM-KA-01-0012345"
            r"udyam[:\s]+(?:no[.:]?|number[.:]?)?[\s]*([A-Z]{2,5}-[A-Z]{2}-\d{2}-\d{7})",
            
            # MSME format: "MSME No: UDYAM-KA-01-0012345" or just "MSME (Udyam No:"
            r"msme[:\s]+(?:no[.:]?|number[.:]?)?[\s]*([A-Z]{2,5}-[A-Z]{2}-\d{2}-\d{7})",
            
            # Flexible format: Just the number "UDYAM-KA-01-0012345" anywhere in text
            r"[A-Z]{2,5}-[A-Z]{2}-\d{2}-\d{7}",
            
            # Any mention of "registered as MSME" or "registered as an MSME"
            r"registered\s+as\s+(?:an?\s+)?msme",
            
            # Udyog Aadhaar (old system)
            r"udyog\s+aa?dhaa?r",
            
            # Hindi patterns
            r"उद्यम",  # Hindi word for Udyam
            r"एमएसएमई.*पंजीकृत",  # "MSME registered" in Hindi
            r"एम\.?\s*एस\.?\s*एम\.?\s*ई",  # M.S.M.E in Hindi
        ]

        for pattern in udyam_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def _has_gst_registration(self, text: str) -> bool:
        """Check if user has GST registration."""
        gst_patterns = [
            r"gst[:\s]+(?:no[.:]?|number[.:]?)?[\s]*(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9][Z][A-Z0-9])",
            r"gstin[:\s]+(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9][Z][A-Z0-9])",
            r"gst[\s-]*registered",
            # Hindi patterns
            r"जी\.?\s*एस\.?\s*टी",  # G.S.T in Hindi
            r"जीएसटी.*पंजीकृत",  # "GST registered" in Hindi
        ]
        for pattern in gst_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def _has_iec(self, text: str) -> bool:
        """Check if user has Import-Export Code."""
        iec_patterns = [
            r"iec[:\s]+(?:no[.:]?|number[.:]?)?[\s]*(\d{10})",
            r"import[:\s]+export[:\s]+code",
            r"importer"
        ]
        for pattern in iec_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def _is_existing_business(self, text: str) -> bool:
        """Check if user has an existing/operational business."""
        existing_indicators = [
            # English patterns
            r"operate[s]?\s+(?:under|a)",
            r"(?:running|operating|managing)\s+(?:a\s+)?business",
            r"business\s+(?:name|owner)",
            r"registered\s+(?:as|under)",
            r"established\s+business",
            r"current\s+business",
            r"i\s+(?:run|operate|manage|own)",
            # Hindi patterns
            r"व्यवसायिक\s*नाम",  # business name
            r"व्अथवावसायिक\s*नाम",  # business name (variant)
            r"काम\s*करता\s*हूं",  # I work/operate
            r"पंजीकृत\s*(?:हूं|है|कार्य)",  # registered
            r"कार्य\s*(?:करता|में)",  # business/work
            r"उद्यम",  # enterprise/business
            r"कारोबार",  # business
            r"व्यापार",  # trade/business
        ]
        for pattern in existing_indicators:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def _has_trade_license(self, text: str) -> bool:
        """Check if user has trade license."""
        return bool(re.search(r"trade\s+license", text, re.IGNORECASE))
    
    def _has_shop_establishment(self, text: str) -> bool:
        """Check if user has Shop & Establishment registration."""
        patterns = [
            r"shop\s+(?:and|&)\s+establishment",
            r"shop\s+act"
        ]
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def _has_fssai(self, text: str) -> bool:
        """Check if user has FSSAI license."""
        patterns = [
            r"fssai[:\s]+(?:no[.:]?|license[.:]?)?[\s]*(\d{14})",
            r"food\s+(?:license|safety)"
        ]
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def _has_mudra_loan(self, text: str) -> bool:
        """Check if user has already taken MUDRA loan."""
        patterns = [
            r"mudra\s+loan",
            r"pradhan\s+mantri\s+mudra\s+yojana",
            r"pmmy\s+loan"
        ]
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def _has_stand_up_india(self, text: str) -> bool:
        """Check if user benefited from Stand-Up India."""
        return bool(re.search(r"stand[\s-]?up\s+india", text, re.IGNORECASE))
    
    def _has_skill_training(self, text: str) -> bool:
        """Check if user completed skill training."""
        patterns = [
            r"(?:completed|undergone|attended)\s+(?:skill\s+)?training",
            r"training\s+(?:certificate|certification)",
            r"certified\s+(?:in|for)"
        ]
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    def build_exclusion_query(self) -> str:
        """
        Build query string with exclusions for datastore search.
        
        Returns:
            String with negative filters (e.g., '-"Udyam Registration" -"GST Registration"')
        """
        if not self.excluded_keywords:
            return ""
        
        # Build exclusion string with negative operators
        exclusions = []
        for keyword in self.excluded_keywords:
            # Use quotes for exact phrase matching
            exclusions.append(f'-"{keyword}"')
        
        return " ".join(exclusions)


def extract_profile_exclusions(profile_text: str) -> Dict[str, any]:
    """
    Main function to extract profile exclusions.
    
    Args:
        profile_text: User's profile description
        
    Returns:
        Dictionary with exclusion analysis
    """
    analyzer = UserProfileAnalyzer()
    return analyzer.analyze_profile(profile_text)


def build_smart_query(
    base_query: str,
    profile_text: Optional[str] = None,
    existing_exclusions: Optional[Set[str]] = None
) -> str:
    """
    Build an intelligent search query with negative filters.
    
    Args:
        base_query: Basic search query (e.g., "loan schemes Karnataka")
        profile_text: User's profile text (optional)
        existing_exclusions: Pre-computed exclusions (optional)
        
    Returns:
        Enhanced query string with exclusions
    """
    exclusion_string = ""
    
    if profile_text:
        analyzer = UserProfileAnalyzer()
        analyzer.analyze_profile(profile_text)
        # exclusion_string = analyzer.build_exclusion_query()
    elif existing_exclusions:
        exclusions = [f'-"{kw}"' for kw in existing_exclusions]
        # exclusion_string = " ".join(exclusions)
    
    # Combine base query with exclusions
    if exclusion_string:
        smart_query = f"{base_query} {exclusion_string}"
        logger.info(f"Built smart query: {smart_query}")
        return smart_query
    
    return base_query