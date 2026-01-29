import os
import concurrent.futures
import numpy as np
from config.settings import settings
from langchain_google_community import VertexAISearchRetriever
from langchain_google_vertexai import VertexAIEmbeddings
from langchain_core.tools import tool

# CONFIGURATION
# Project ID
PROJECT_ID = settings.google_cloud_project
# Structured Datastore
MSME_STRUCTURED_ID = settings.msme_datastore_id
# Unstructured Datastore 
MSME_UNSTRUCTURED_ID = settings.msme_unstructured_id

# HELPER: GENERIC RETRIEVER
def fetch_from_store(store_id, query, is_structured=False):
    """Fetch from a specific Vertex AI Data Store"""
    try:
        retriever = VertexAISearchRetriever(
            project_id=PROJECT_ID,
            location_id="global",
            data_store_id=store_id,
            max_documents=4, # Fetch enough context
            engine_data_type=1 if is_structured else 0, # 1=Struct, 0=Unstruct
            get_extractive_answers=False # Speed Optimization
        )
        docs = retriever.invoke(query)
        if not docs:
            return ""
        # Format: Add source tag so LLM knows where it came from
        source_tag = "[Database Result]" if is_structured else "[Document Excerpt]"
        return "\n".join([f"{source_tag} {d.page_content}" for d in docs])
    except Exception as e:
        print(f"Error fetching from {store_id}: {e}")
        return ""

# THE SEMANTIC ROUTER (ADVANCED NLP) 
class SemanticRouter:
    _instance = None 
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SemanticRouter, cls).__new__(cls)
            print("--- [Router] Initializing Embeddings Model... ---")
            # Uses Google's latest embedding model for high accuracy
            cls._instance.embeddings = VertexAIEmbeddings(model_name="text-embedding-004")
            
            # DEFINING ROBUST INTENT CLUSTERS
            cls._instance.routes = {
                "structured_data": [
                    # User wants a LIST or SPECIFIC FACT (Best for Spreadsheet/DB)
                    "list of schemes", "search for loans", "find subsidies", 
                    "maximum loan amount", "interest rate percentage", "scheme code", 
                    "guid", "eligibility criteria", "subsidy limit", 
                    "schemes for women", "schemes for maharashtra", "textile business loans",
                    "manufacturing sector schemes", "trading business loans", 
                    "caste based schemes", "sc/st schemes", "loan for machinery"
                ],
                "unstructured_docs": [
                    # User wants PROCESS or KNOWLEDGE (Best for PDFs/Docs)
                    "how do i apply", "what is the application process", "step by step guide",
                    "list of documents required", "documentation checklist", "user manual",
                    "policy guidelines", "detailed explanation", "terms and conditions",
                    "what is udyam registration", "how to register", "definitions",
                    "grievance redressal", "contact details", "helpline number",
                    "success stories", "detailed project report guide"
                ]
            }
            
            # Pre-compute vectors (Cache them for speed)
            cls._instance.route_vectors = {}
            for category, phrases in cls._instance.routes.items():
                cls._instance.route_vectors[category] = cls._instance.embeddings.embed_documents(phrases)
        return cls._instance
            
    def get_route(self, query):
        """Calculates Similarity Scores to decide the route"""
        query_vector = self.embeddings.embed_query(query)
        scores = {}
        for category, vectors in self.route_vectors.items():
            # Dot Product = Semantic Similarity
            similarities = [np.dot(query_vector, v) for v in vectors]
            scores[category] = max(similarities) # Take the best match
        
        print(f"--- [Router Scores] Struct: {scores['structured_data']:.2f} | Docs: {scores['unstructured_docs']:.2f} ---")
        
        # LOGIC MATRIX
        # If the scores are close (within 0.05), search BOTH to be safe.
        diff = abs(scores['structured_data'] - scores['unstructured_docs'])
        
        if diff < 0.05: 
            return "both"
        elif scores['structured_data'] > scores['unstructured_docs']:
            return "structured"
        else:
            return "unstructured"

# THE MAIN TOOL FUNCTION
def search_msme_schemes(query: str):
    """
    Primary Search Tool for MSME Agent.
    
    This tool uses Semantic Routing to intelligently query:
    1. The Scheme Database (for lists, loans, subsidies, IDs)
    2. The Policy Documents (for guidelines, process, rules)
    
    Args:
        query: The user's question or keywords (e.g., "loan for shoe shop in maharashtra")
    """
    router = SemanticRouter()
    route = router.get_route(query)
    print(f"--- [Router] Selected Route: {route.upper()} ---")
    
    context = ""
    
    # PARALLEL EXECUTION (Speed Optimization)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_struct = None
        future_unstruct = None
        
        # 1. Trigger Structured Search?
        if route in ["structured", "both"]:
            print("--- [Fetch] Querying Structured DB... ---")
            future_struct = executor.submit(fetch_from_store, MSME_STRUCTURED_ID, query, True)
        
        # 2. Trigger Unstructured Search?
        if route in ["unstructured", "both"]:
            print("--- [Fetch] Querying Document DB... ---")
            future_unstruct = executor.submit(fetch_from_store, MSME_UNSTRUCTURED_ID, query, False)
            
        # 3. Gather Results
        if future_struct:
            res = future_struct.result()
            if res: context += f"### SCHEME DATABASE RESULTS:\n{res}\n\n"
            
        if future_unstruct:
            res = future_unstruct.result()
            if res: context += f"### POLICY DOCUMENT RESULTS:\n{res}\n\n"

    if not context:
        return "No specific schemes or documents found for this query."
        
    return context