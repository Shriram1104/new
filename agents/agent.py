"""
Main agent entry point for ADK Web.
This file exposes the master_agent as root_agent for ADK to discover.
"""

# Import the master agent and expose it as root_agent
# from agents.master_agent.agent import root_agent
from agents.msme_agent.agent import root_agent

# This is what ADK Web looks for
__all__ = ["root_agent"]
