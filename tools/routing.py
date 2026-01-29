"""
Routing logic for the Master Agent.
"""
import asyncio
import threading
import json
from utils import setup_logger

# --- SPECIFIC IMPORTS ---
try:
    from tools import search_farmer_schemes
    from tools.parallel_search import search_msme_schemes
except ImportError as e:
    print(f"Import Warning: {e}")
    async def search_farmer_schemes(**kwargs): return "{}"
    def search_msme_schemes(**kwargs): return "{}"

logger = setup_logger(__name__)

# --- GLOBAL BACKGROUND LOOP ---
_search_loop = None
_search_thread = None

def _start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

def get_persistent_loop():
    global _search_loop, _search_thread
    if _search_loop is None:
        _search_loop = asyncio.new_event_loop()
        _search_thread = threading.Thread(target=_start_background_loop, args=(_search_loop,), daemon=True)
        _search_thread.start()
    return _search_loop

def run_async_safe(coro):
    loop = get_persistent_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

# --- HELPER: VERIFY MATCH ---
def is_valid_match(search_result_json: str, user_query: str) -> bool:
    """
    Parses the search result and checks if the scheme name actually matches.
    Prevents vector search from returning irrelevant "similar" results.
    """
    try:
        data = json.loads(search_result_json)
        schemes = data.get("schemes", [])
        
        if not schemes:
            return False
            
        # Check if any returned scheme name contains the user's key terms
        query_terms = user_query.lower().split()
        for scheme in schemes:
            scheme_name = scheme.get("name", "").lower()
            # If the scheme name contains at least one significant word from the query
            if any(term in scheme_name for term in query_terms if len(term) > 3):
                return True
                
        return False
    except Exception:
        return False

# --- ROUTING LOGIC ---
def check_scheme_and_route(scheme_name: str) -> str:
    """Determines the correct agent by searching datastores.

    Args:
        scheme_name: The name of the government scheme.

    Returns:
        Routing instructions for the Master Agent.
    """
    logger.info(f"Routing Check: Searching for '{scheme_name}' in databases...")

    # 1. CHECK FARMER DATASTORE
    try:
        try:
            farmer_result = run_async_safe(search_farmer_schemes(query=scheme_name, state=""))
        except TypeError:
            farmer_result = run_async_safe(search_farmer_schemes(query=scheme_name))
    except Exception:
        farmer_result = "{}"
    
    # Strict Check: Only route if names match
    is_in_farmer = is_valid_match(farmer_result, scheme_name)
    
    if is_in_farmer:
        return (
            f"DECISION: The scheme '{scheme_name}' was found in the Agriculture Database. "
            "ACTION: Please transfer the user to the 'farmer_agent' immediately."
        )

    # 2. CHECK MSME DATASTORE
    try:
        msme_result = search_msme_schemes(query=scheme_name)
    except TypeError:
         msme_result = "{}"
    
    # Strict Check: Only route if names match
    is_in_msme = is_valid_match(msme_result, scheme_name)

    if is_in_msme:
        return (
            f"DECISION: The scheme '{scheme_name}' was found in the MSME/Business Database. "
            "ACTION: Please transfer the user to the 'msme_agent' immediately."
        )

    # 3. NOT FOUND
    return (
        f"DECISION: I searched both databases and found NO scheme matching '{scheme_name}'. "
        "ACTION: Tell the user you couldn't find that specific scheme. "
        "THEN, immediately ask: 'To help me find the right information for you, could you tell me what's your occupation? if you are a Farmer or a Business Owner?'"
    )