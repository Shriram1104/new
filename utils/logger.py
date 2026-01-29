"""
Structured logging configuration using ADK logger and Python logging.
"""

import logging
import sys
from typing import Any, Dict
from config.settings import settings

# Configure logging based on settings
LOG_LEVEL = getattr(logging, settings.log_level.upper(), logging.INFO)


def setup_logger(name: str) -> logging.Logger:
    """
    Set up a logger with consistent formatting.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(LOG_LEVEL)
    
    # Create formatter
    if settings.log_format == "json":
        formatter = logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        )
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger


def log_agent_event(
    logger: logging.Logger,
    event_type: str,
    agent_name: str,
    data: Dict[str, Any]
) -> None:
    """
    Log an agent event with structured data.
    
    Args:
        logger: Logger instance
        event_type: Type of event (e.g., 'tool_call', 'response', 'error')
        agent_name: Name of the agent
        data: Event data
    """
    log_data = {
        "event_type": event_type,
        "agent": agent_name,
        **data
    }
    
    if event_type == "error":
        logger.error(f"{event_type}: {log_data}")
    elif event_type == "warning":
        logger.warning(f"{event_type}: {log_data}")
    else:
        logger.info(f"{event_type}: {log_data}")


def log_tool_call(
    logger: logging.Logger,
    tool_name: str,
    parameters: Dict[str, Any],
    duration_ms: float = None
) -> None:
    """
    Log a tool call with parameters.
    
    Args:
        logger: Logger instance
        tool_name: Name of the tool
        parameters: Tool parameters
        duration_ms: Execution duration in milliseconds
    """
    log_data = {
        "tool": tool_name,
        "parameters": parameters,
    }
    
    if duration_ms is not None:
        log_data["duration_ms"] = duration_ms
    
    logger.info(f"Tool call: {log_data}")


def log_datastore_query(
    logger: logging.Logger,
    datastore_id: str,
    query: str,
    result_count: int,
    duration_ms: float = None
) -> None:
    """
    Log a datastore query.
    
    Args:
        logger: Logger instance
        datastore_id: Datastore identifier
        query: Search query
        result_count: Number of results returned
        duration_ms: Query duration in milliseconds
    """
    log_data = {
        "datastore": datastore_id,
        "query": query,
        "results": result_count,
    }
    
    if duration_ms is not None:
        log_data["duration_ms"] = duration_ms
    
    logger.info(f"Datastore query: {log_data}")


# Default logger for the application
default_logger = setup_logger("scheme_advisor")
