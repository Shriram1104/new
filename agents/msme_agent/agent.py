"""
MSME Agent
Specialized agent for MSME and business-related scheme queries.
"""

import os
from google.adk.agents.llm_agent import Agent
from config import settings
from tools import (
    search_msme_schemes,
    get_scheme_details,
    enrich_msme_context,
    get_missing_context_questions,
    manage_scheme_pagination,
    handle_more_request,
    handle_scheme_query,
)
# from tools.parallel_search import search_msme_schemes
from utils import setup_logger
from utils.secrets import get_secret

logger = setup_logger(__name__)

if os.environ.get("TESTING") == 'true':
    # logger.info(f"msme agent testing prompts......")
    from config.msme_agent_prompt import MSME_AGENT_INSTRUCTION
else:
    MSME_AGENT_INSTRUCTION = get_secret("MSME_AGENT_INSTRUCTION")

# Initialize Vertex AI - set environment variables
if settings.google_application_credentials and os.path.exists(settings.google_application_credentials):
    # logger.info(f"MSME agent initializing with Vertex AI")
    os.environ['GOOGLE_CLOUD_PROJECT'] = settings.google_cloud_project
    os.environ['GOOGLE_CLOUD_REGION'] = settings.google_cloud_region
    os.environ['GOOGLE_CLOUD_LOCATION'] = settings.google_cloud_region
    
    # CRITICAL FIX: Tell ADK to use Vertex AI instead of API Key
    os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"
    
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = settings.google_application_credentials


# Define the MSME agent
root_agent = Agent(
    model="gemini-2.5-flash-lite",
    name="msme_agent",
    description=(
        "Specialized agent for MSMEs and business owners. Helps find government "
        "schemes for loans, subsidies, grants, training, and business development."
    ),
    instruction=MSME_AGENT_INSTRUCTION,
    tools=[
        search_msme_schemes,
        get_scheme_details,
        enrich_msme_context,
        get_missing_context_questions,
        manage_scheme_pagination,
        handle_more_request,
        handle_scheme_query,
    ],
)


if __name__ == "__main__":
    """Test the MSME agent locally."""
    from google.adk.runners.in_memory_runner import InMemoryRunner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    
    # Create runner with session service
    session_service = InMemorySessionService()
    runner = InMemoryRunner(
        agent=root_agent,
        session_service=session_service,
        app_name="msme_agent_test",
    )
    
    # Test conversation flow
    test_conversation = [
        "Hi! I run a small textile business in Surat, Gujarat.",
        "I am a woman entrepreneur.",
        "I have 12 employees.",
        "What schemes can help me expand my business?",
        "Yes, show me more options",
        "What is the application process for scheme 1?",
    ]
    
    print("🏭 Testing MSME Agent\n")
    print("=" * 60)
    
    session_id = "msme_test_session"
    
    for i, query in enumerate(test_conversation, 1):
        print(f"\n[Turn {i}]")
        print(f"👤 User: {query}")
        print("-" * 60)
        
        try:
            # Run agent
            for event in runner.run(
                user_id="test_msme",
                session_id=session_id,
                message=query
            ):
                if hasattr(event, "text") and event.text:
                    print(f"🤖 Agent: {event.text}")
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"❌ Error: {e}")
        
        print("-" * 60)
