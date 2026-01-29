"""
Master Agent (Orchestrator)
Main entry point that routes users to specialized agents.
"""

import os
import vertexai 
from google.adk.agents.llm_agent import Agent
from config import settings
from tools import (
    extract_user_context,
    classify_user_persona,
)
from tools.routing import (
    check_scheme_and_route,
)

from utils import setup_logger
from utils.secrets import get_secret
logger = setup_logger(__name__)

if os.environ.get("TESTING") == 'true':
    # logger.info(f"master agent testing prompts......")
    from config.master_agent_prompt import MASTER_AGENT_INSTRUCTION
else:
    MASTER_AGENT_INSTRUCTION = get_secret("MASTER_AGENT_INSTRUCTION")

# Import sub-agents
from agents.farmer_agent.agent import root_agent as farmer_agent
from agents.msme_agent.agent import root_agent as msme_agent

logger = setup_logger(__name__)

# MODEL SELECTION LOGIC 
# If a Tuned Endpoint is configured, use it and force the correct region.
if settings.master_tuned_endpoint:
    active_model = settings.master_tuned_endpoint
    # Force Environment Variables for ADK Framework
    os.environ['GOOGLE_CLOUD_PROJECT'] = settings.google_cloud_project
    os.environ['GOOGLE_CLOUD_REGION'] = "us-central1"
    os.environ['GOOGLE_CLOUD_LOCATION'] = "us-central1"
    os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"   
    # Fine-tuned endpoints exist in 'us-central1', not 'global'.
    vertexai.init(project=settings.google_cloud_project, location="us-central1")
    # logger.info(f"Master Agent using Fine-Tuned Endpoint: {active_model}")
else:
    active_model = settings.model_string
    # Default initialization logic for standard models
    if settings.google_application_credentials and os.path.exists(settings.google_application_credentials):
        # logger.info(f"Initializing with Vertex AI - Project: {settings.google_cloud_project}")
        os.environ['GOOGLE_CLOUD_PROJECT'] = settings.google_cloud_project
        os.environ['GOOGLE_CLOUD_REGION'] = settings.google_cloud_region
        os.environ['GOOGLE_CLOUD_LOCATION'] = settings.google_cloud_region
        os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

        if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = settings.google_application_credentials

# Define the master orchestrator agent
root_agent = Agent(
    model=active_model,
    name="master_agent",
    description=(
        "Main orchestrator agent that analyzes user context and routes to "
        "appropriate specialized agents (Farmer or MSME)."
    ),
    instruction=MASTER_AGENT_INSTRUCTION,
    tools=[
        extract_user_context,
        classify_user_persona,
        check_scheme_and_route,
    ],
    sub_agents=[
        farmer_agent,
        msme_agent,
    ],
)

if __name__ == "__main__":
    """Test the master agent locally."""
    from google.adk.runners.in_memory_runner import InMemoryRunner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    
    # Create runner with session service
    session_service = InMemorySessionService()
    runner = InMemoryRunner(
        agent=root_agent,
        session_service=session_service,
        app_name="scheme_advisor",
    )
    
    # Test queries
    test_queries = [
        "Hello! I am a farmer from Maharashtra growing wheat.",
        "मैं जयपुर में मिलेट-आधारित खाखरा बेचने वाली एक महिला हूं",  # Hindi
        "I have a small manufacturing business in Gujarat with 8 employees.",
    ]
    
    print("🔍 Testing Master Agent\n")
    print("=" * 60)
    
    for query in test_queries:
        print(f"\n📝 Query: {query}")
        print("-" * 60)
        
        try:
            # Run agent
            for event in runner.run(
                user_id="test_user",
                session_id="test_session",
                message=query
            ):
                if hasattr(event, "text") and event.text:
                    print(f"🤖 Response: {event.text}")
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"❌ Error: {e}")
        
        print("-" * 60)
