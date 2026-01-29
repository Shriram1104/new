"""
Farmer Agent
Specialized agent for farmer-related scheme queries.
"""

import os
from google.adk.agents.llm_agent import Agent
from config import settings
from tools import (
    search_farmer_schemes,
    get_scheme_details,
    enrich_farmer_context,
    get_missing_context_questions,
    manage_scheme_pagination,
    handle_more_request,
    handle_scheme_query,
)
from utils import setup_logger
from utils.secrets import get_secret
logger = setup_logger(__name__)

if os.environ.get("TESTING") == 'true':
    logger.info(f"farmer agent testing prompts......")
    from config.farmer_agent_prompt import FARMER_AGENT_INSTRUCTION
else:
    FARMER_AGENT_INSTRUCTION = get_secret("FARMER_AGENT_INSTRUCTION")

# Initialize Vertex AI - set environment variables
if settings.google_application_credentials and os.path.exists(settings.google_application_credentials):
    logger.info(f"Farmer agent initializing with Vertex AI")
    os.environ['GOOGLE_CLOUD_PROJECT'] = settings.google_cloud_project
    os.environ['GOOGLE_CLOUD_REGION'] = settings.google_cloud_region
    os.environ['GOOGLE_CLOUD_LOCATION'] = settings.google_cloud_region
    
    # CRITICAL FIX: Tell ADK to use Vertex AI instead of API Key
    os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"
    
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = settings.google_application_credentials


# Define the farmer agent
root_agent = Agent(
    model="gemini-2.5-flash-lite",
    name="farmer_agent",
    description=(
        "Specialized agent for farmers. Helps farmers find government schemes "
        "for agriculture, livestock, subsidies, loans, and farming equipment."
    ),
    instruction=FARMER_AGENT_INSTRUCTION,
    tools=[
        search_farmer_schemes,
        get_scheme_details,
    ],
)


if __name__ == "__main__":
    """Test the farmer agent locally."""
    from google.adk.runners.in_memory_runner import InMemoryRunner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    
    # Create runner with session service
    session_service = InMemorySessionService()
    runner = InMemoryRunner(
        agent=root_agent,
        session_service=session_service,
        app_name="farmer_agent_test",
    )
    
    # Test conversation flow
    test_conversation = [
        "Hello! I grow wheat in Punjab.",
        "I have about 5 acres of land.",
        "What loan schemes am I eligible for?",
        "Yes, show me more schemes",
        "Tell me the process for the first scheme",
    ]
    
    print("🌾 Testing Farmer Agent\n")
    print("=" * 60)
    
    session_id = "farmer_test_session"
    
    for i, query in enumerate(test_conversation, 1):
        print(f"\n[Turn {i}]")
        print(f"👤 User: {query}")
        print("-" * 60)
        
        try:
            # Run agent
            for event in runner.run(
                user_id="test_farmer",
                session_id=session_id,
                message=query
            ):
                if hasattr(event, "text") and event.text:
                    print(f"🤖 Agent: {event.text}")
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"❌ Error: {e}")
        
        print("-" * 60)
