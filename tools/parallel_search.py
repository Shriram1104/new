import os
import concurrent.futures
from config.settings import settings
from langchain_google_community import VertexAISearchRetriever

# CONFIGURATION
# Project ID
PROJECT_ID = settings.google_cloud_project
# Structured Datastore
MSME_STRUCTURED_ID = settings.msme_datastore_id
# Unstructured Datastore 
MSME_UNSTRUCTURED_ID = settings.msme_unstructured_id

# -OPTIMIZED FETCH FUNCTION 
def fetch_from_store(store_id, query, is_structured):
    """
    Fetches raw data segments from Vertex AI Search.
    
    Optimization: 
    - max_documents=3 (Reduces payload size)
    - get_extractive_answers=False (Skips Google's internal AI, saving ~1-2s latency)
    """
    try:
        if not store_id:
            print(f"Missing Datastore ID for {'Structured' if is_structured else 'Unstructured'}")
            return ""

        retriever = VertexAISearchRetriever(
            project_id=PROJECT_ID,
            location_id="global",
            data_store_id=store_id,
            max_documents=3, 
            engine_data_type=1 if is_structured else 0,
            get_extractive_answers=False, # Critical for speed
            max_extractive_answer_count=1
        )
        
        docs = retriever.invoke(query)
        if not docs:
            return ""
        
        # Tag the source clearly so Gemini knows which is which
        source_tag = "[Database Record]" if is_structured else "[Official Document]"
        
        # Join the content efficiently
        return "\n".join([f"{source_tag} {d.page_content}" for d in docs])
        
    except Exception as e:
        print(f"Error fetching from store {store_id}: {e}")
        return ""

# PARALLEL SEARCH
def search_msme_schemes(query: str):
    """
    Executes a Parallel Hybrid Search.
    
    Logic:
    Instead of guessing which datastore to use, we query BOTH the 
    Structured (CSV/DB) and Unstructured (PDF/Docs) stores simultaneously.
    This ensures we get both specific facts (limits, rates) and 
    descriptive context (process, guidelines).
    """
    print(f"--- [Search] Processing Query: {query} ---")
    
    # Basic validation
    if not query or len(query.strip()) < 2:
        return "Please provide more details for your search."

    context = ""
    
    # PARALLEL EXECUTION BLOCK 
    # ThreadPoolExecutor runs both fetch functions at the exact same time.
    # Total Latency = Time taken by the slowest datastore (not the sum of both).
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        
        # 1. Submit Tasks (Non-Blocking)
        # These lines execute instantly
        future_struct = executor.submit(fetch_from_store, MSME_STRUCTURED_ID, query, True)
        future_unstruct = executor.submit(fetch_from_store, MSME_UNSTRUCTURED_ID, query, False)
        
        # 2. Retrieve Results (Blocking)
        # We use a timeout to ensure the agent doesn't hang if Vertex AI is slow
        try:
            # Get Structured Data
            res_struct = future_struct.result(timeout=10)
            if res_struct:
                context += f"STRUCTURED DATA:\n{res_struct}\n\n"
        except Exception as e:
            print(f"Structured Search Failed: {e}")

        try:
            # Get Unstructured Data
            res_unstruct = future_unstruct.result(timeout=10)
            if res_unstruct:
                context += f"UNSTRUCTURED DATA:\n{res_unstruct}\n\n"
        except Exception as e:
            print(f"Unstructured Search Failed: {e}")

    # Final Check
    if not context:
        return "No specific schemes or documents found for this query in the database."
        
    return context