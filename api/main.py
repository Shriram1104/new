import os
import uuid
import json
import logging
from typing import Optional, AsyncGenerator, List, Dict, Any, Set
from datetime import datetime

from fastapi import FastAPI, HTTPException, Body, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi import BackgroundTasks

# Firestore imports
from google.cloud import firestore
from google.cloud.firestore import AsyncClient

try:
    from google.adk.runners import InMemoryRunner
except ImportError:
    from google.adk.runners.in_memory_runner import InMemoryRunner

try:
    from google.genai import types
except ImportError:
    try:
        from google.adk.core import types
    except ImportError:
        from types import SimpleNamespace as types

try:
    from google.adk.sessions import InMemorySessionService
except ImportError:
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

# Import Agent
from agents.master_agent.agent import root_agent
from google.adk.agents.run_config import RunConfig, StreamingMode


# --- CONFIG ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
APP_NAME = "scheme_advisor"

app = FastAPI(title="Scheme Advisor Agent API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing (restrict in production)
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods including OPTIONS, POST, GET
    allow_headers=["*"],  # Allow all headers including X-Partner-Code
    expose_headers=["*"]  # Expose headers in response
)

# Initialize Firestore
db = AsyncClient()

# Initialize Runner
runner = InMemoryRunner(
    agent=root_agent,
    app_name=APP_NAME,
)
session_service = runner.session_service

# --- MODELS ---
class CreateSessionRequest(BaseModel):
    session: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None

class AgentQueryRequest(BaseModel):
    query: str


# --- HELPER FUNCTIONS ---
def get_partner_code(header_value: Optional[str] = None) -> str:
    """
    Extract and validate partner code from header.
    Returns 'unknown' if not provided.
    
    Args:
        header_value: Value from X-Partner-Code header
        
    Returns:
        Cleaned partner code string
    """
    if header_value:
        # Clean and lowercase the partner code
        partner_code = header_value.strip().lower()
        
        # Optional: Validate against allowed partners
        # allowed_partners = ["flipkart_001", "amazon_002", "meesho_003"]
        # if partner_code not in allowed_partners:
        #     logger.warning(f"Unknown partner code: {partner_code}")
        #     return "unknown"
        
        return partner_code
    
    return "unknown"


# --- FIRESTORE HELPERS ---
async def save_session_to_firestore(
    session_id: str,
    user_id: str,
    query: str,
    response: str,
    state: str,
    partner_code: Optional[str] = None,  # NEW: Partner code parameter
    session_history: list = None
):
    """
    Save session data to Firestore after completion with partner tracking.
    
    Args:
        session_id: Unique session identifier
        user_id: User identifier
        query: User query text
        response: Agent response text
        state: Session state (COMPLETED, FAILED, etc.)
        partner_code: Partner identifier (e.g., 'flipkart_001')
        session_history: Full conversation history
    """
    try:
        # Reference to the session document
        session_ref = db.collection('sessions').document(session_id)
        
        # Get existing session data or create new
        session_doc = await session_ref.get()
        
        if session_doc.exists:
            # Update existing session
            update_data = {
                'updated_at': firestore.SERVER_TIMESTAMP,
                'last_state': state,
                'query_count': firestore.Increment(1)
            }
            
            # Add partner_code only if not already set (preserve original partner)
            existing_data = session_doc.to_dict()
            if partner_code and not existing_data.get('partner_code'):
                update_data['partner_code'] = partner_code
            
            await session_ref.update(update_data)
        else:
            # Create new session document
            session_data = {
                'user_id': user_id,
                'session_id': session_id,
                'created_at': firestore.SERVER_TIMESTAMP,
                'updated_at': firestore.SERVER_TIMESTAMP,
                'last_state': state,
                'query_count': 1
            }
            
            # NEW: Add partner code to session
            if partner_code:
                session_data['partner_code'] = partner_code
            
            await session_ref.set(session_data)
        
        # Save the query and response to queries subcollection
        query_ref = session_ref.collection('queries').document()
        query_data = {
            'query': query,
            'response': response,
            'state': state,
            'timestamp': firestore.SERVER_TIMESTAMP,
            'created_at': datetime.utcnow().isoformat()
        }
        
        # NEW: Add partner code to each query for granular tracking
        if partner_code:
            query_data['partner_code'] = partner_code
        
        await query_ref.set(query_data)
        
        # Optionally save the full session history if provided
        if session_history:
            history_ref = session_ref.collection('history').document('full_history')
            await history_ref.set({
                'messages': session_history,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
        
        logger.info(f"Session {session_id} saved to Firestore for partner {partner_code}")
        
    except Exception as e:
        logger.error(f"Error saving to Firestore: {str(e)}")


async def get_session_history_from_memory(session_id: str, user_id: str):
    """
    Retrieve session history from InMemorySessionService.
    """
    try:
        # Get the session from memory
        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id
        )
        
        if session and hasattr(session, 'history'):
            # Convert history to serializable format
            history = []
            for msg in session.history:
                msg_dict = {
                    'role': getattr(msg, 'role', 'unknown'),
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                # Extract text content
                if hasattr(msg, 'text'):
                    msg_dict['text'] = msg.text
                elif hasattr(msg, 'content'):
                    if hasattr(msg.content, 'parts'):
                        texts = []
                        for part in msg.content.parts:
                            if hasattr(part, 'text') and part.text:
                                texts.append(part.text)
                        msg_dict['text'] = ' '.join(texts)
                elif hasattr(msg, 'parts'):
                    texts = []
                    for part in msg.parts:
                        if hasattr(part, 'text') and part.text:
                            texts.append(part.text)
                    msg_dict['text'] = ' '.join(texts)
                
                history.append(msg_dict)
            
            return history
        
        return []
        
    except Exception as e:
        logger.error(f"Error retrieving session history: {str(e)}")
        return []


async def get_user_sessions(user_id: str, limit: int = 50):
    """
    Retrieve all sessions for a specific user from Firestore.
    """
    try:
        sessions_ref = db.collection('sessions')
        
        query = sessions_ref.where('user_id', '==', user_id).order_by(
            'updated_at', direction=firestore.Query.DESCENDING
        ).limit(limit)
        
        sessions = []
        async for doc in query.stream():
            session_data = doc.to_dict()
            session_data['session_id'] = doc.id
            sessions.append(session_data)
        
        return sessions
        
    except Exception as e:
        logger.error(f"Error retrieving user sessions: {str(e)}")
        return []


# --- ENDPOINTS ---

@app.post("/agent/sessions/create")
async def create_session(
    request: CreateSessionRequest,
    x_partner_code: Optional[str] = Header(None, alias="X-Partner-Code")  # NEW
):
    """
    Create a new session with partner tracking.
    
    Headers:
        X-Partner-Code: Partner identifier (optional)
        Example: X-Partner-Code: flipkart_001
    
    Request Body:
        {
            "user_id": "string",
            "session_id": "string (optional)",
            "session": "string (optional display name)"
        }
    """
    try:
        # Extract partner code from header
        partner_code = get_partner_code(x_partner_code)

        session_id = request.session_id or str(uuid.uuid4().int)[:19]
        display_name = request.session or "New Session"
        user_id = request.user_id

        await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id
        )
        
        # Create session record in Firestore with partner code
        session_ref = db.collection('sessions').document(session_id)
        session_data = {
            'user_id': user_id,
            'session_id': session_id,
            'display_name': display_name,
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP,
            'state': 'IN_PROGRESS',
            'query_count': 0
        }
        
        # NEW: Add partner code to session
        if partner_code:
            session_data['partner_code'] = partner_code
        
        await session_ref.set(session_data)
        
        # Log partner activity
        logger.info(f"Session {session_id} created for partner: {partner_code}")
        
        return {
            "results": {
                "state": "IN_PROGRESS",
                "userId": user_id,
                "session_id": session_id,
                "displayName": display_name,
                "partner_code": partner_code  # Return partner code for confirmation
            }
        }
    except Exception as e:
        logger.error(f"Error creating session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agent/search/answer/{user_id}/{session_id}")
async def agent_search_answer(
    user_id: str,
    session_id: str,
    request: AgentQueryRequest,
    x_partner_code: Optional[str] = Header(None, alias="X-Partner-Code")  # NEW
):
    """
    Standard (Non-Streaming) Agent Answer Endpoint with partner tracking.
    
    Headers:
        X-Partner-Code: Partner identifier (optional)
        Example: X-Partner-Code: flipkart_001
    """
    try:
        # Extract partner code from header
        partner_code = get_partner_code(x_partner_code)

        # Message Creation
        if hasattr(types, "Content") and hasattr(types, "Part"):
             user_msg = types.Content(role="user", parts=[types.Part(text=request.query)])
        elif hasattr(types, "Message"):
             user_msg = types.Message(role="user", text=request.query)
        else:
            from types import SimpleNamespace
            part = SimpleNamespace(text=request.query)
            user_msg = SimpleNamespace(role="user", parts=[part])

        # Execution
        full_text = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_msg 
        ):
            if hasattr(event, "text") and event.text:
                full_text.append(event.text)
            elif hasattr(event, "content") and event.content:
                 if hasattr(event.content, "parts") and event.content.parts:
                      for part in event.content.parts:
                           if hasattr(part, "text") and part.text:
                                full_text.append(part.text)
            elif hasattr(event, "parts") and event.parts:
                for part in event.parts:
                     if hasattr(part, "text") and part.text:
                          full_text.append(part.text)

        response_text = "".join(full_text)
        
        if not response_text:
            response_text = "Task completed (No text response generated)."

        state = "COMPLETED"
        
        # Save to Firestore with partner code
        session_history = await get_session_history_from_memory(
            session_id=session_id,
            user_id=user_id
        )
        
        await save_session_to_firestore(
            session_id=session_id,
            user_id=user_id,
            query=request.query,
            response=response_text,
            state=state,
            partner_code=partner_code,  # NEW: Pass partner code
            session_history=session_history
        )

        return {
            "results": response_text
        }

    except Exception as e:
        logger.error(f"Error in agent search: {str(e)}")
        
        # Extract partner code for error logging
        partner_code = get_partner_code(x_partner_code)
        
        await save_session_to_firestore(
            session_id=session_id,
            user_id=user_id,
            query=request.query,
            response=f"Error: {str(e)}",
            state="FAILED",
            partner_code=partner_code,  # NEW: Track failures by partner
            session_history=[]
        )
        
        return {
            "results": {
                "answer": f"Error: {str(e)}",
                "state": "FAILED"
            }
        }


@app.post("/agent/search/answer/stream/{user_id}/{session_id}")
async def agent_search_answer_stream(
    user_id: str,
    session_id: str,
    request: AgentQueryRequest,
    background_tasks: BackgroundTasks,
    x_partner_code: Optional[str] = Header(None, alias="X-Partner-Code")  # NEW
):
    """
    True streaming using run_async() with StreamingMode.SSE and partner tracking.
    
    Headers:
        X-Partner-Code: Partner identifier (optional)
        Example: X-Partner-Code: flipkart_001
    """
    # Extract partner code from header (outside generator for logging)
    partner_code = get_partner_code(x_partner_code)
    logger.info(f"Streaming request from partner: {partner_code}")

    async def event_generator() -> AsyncGenerator[str, None]:
        accumulated_text = ""  # Track total text sent so far
        
        try:
            # Message Creation
            if hasattr(types, "Content") and hasattr(types, "Part"):
                user_msg = types.Content(role="user", parts=[types.Part(text=request.query)])
            elif hasattr(types, "Message"):
                user_msg = types.Message(role="user", text=request.query)
            else:
                from types import SimpleNamespace
                part = SimpleNamespace(text=request.query)
                user_msg = SimpleNamespace(role="user", parts=[part])

            # Create RunConfig with SSE streaming
            run_config = RunConfig(
                streaming_mode=StreamingMode.SSE,
                max_llm_calls=50
            )

            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_msg,
                run_config=run_config
            ):
                chunk_text = ""
                
                if hasattr(event, "text") and event.text:
                    chunk_text = event.text
                elif hasattr(event, "content") and event.content:
                    if hasattr(event.content, "parts") and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, "text") and part.text:
                                chunk_text += part.text
                elif hasattr(event, "parts") and event.parts:
                    for part in event.parts:
                        if hasattr(part, "text") and part.text:
                            chunk_text += part.text
                
                logger.info(f"Streaming data*******: {chunk_text}")
                if chunk_text:
                    # --- FIXED DEDUPLICATION LOGIC ---
                    
                    # 1. Exact Duplicate Check
                    if chunk_text == accumulated_text:
                        continue
                    
                    # 2. Perfect Snapshot Check
                    # If new chunk strictly contains old chunk, send only difference.
                    if len(chunk_text) > len(accumulated_text) and chunk_text.startswith(accumulated_text):
                        new_content = chunk_text[len(accumulated_text):]
                        accumulated_text = chunk_text
                        if new_content:
                            data = {"results": new_content}
                            yield f"data: {json.dumps(data)}\n\n"
                        continue

                    # 3. Fuzzy Snapshot Guard (Blocks the "Double Output" bug)
                    # If new chunk is huge and contains the end of our current text, it's likely a repeat.
                    if len(accumulated_text) > 50 and accumulated_text[-50:] in chunk_text:
                        overlap_idx = chunk_text.find(accumulated_text[-50:])
                        if overlap_idx != -1:
                            potential_new_start = overlap_idx + 50
                            if potential_new_start < len(chunk_text):
                                new_content = chunk_text[potential_new_start:]
                                accumulated_text += new_content
                                data = {"results": new_content}
                                yield f"data: {json.dumps(data)}\n\n"
                            else:
                                continue # Pure duplicate found, skip it.
                    
                    # 4. Standard Delta (New text piece)
                    else:
                        accumulated_text += chunk_text
                        data = {"results": chunk_text}
                        yield f"data: {json.dumps(data)}\n\n"

            if accumulated_text:
                yield "data: [DONE]\n\n"
            
            # Save to Firestore with partner code
            session_history = await get_session_history_from_memory(
                session_id=session_id,
                user_id=user_id
            )

            background_tasks.add_task(
                save_session_to_firestore, 
                session_id,
                user_id,
                request.query,
                accumulated_text,
                "COMPLETED",
                partner_code,  # NEW: Pass partner code
                session_history
            )

        except Exception as e:
            logger.error(f"Stream Error for partner {partner_code}: {e}")
            error_data = {"error": str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Partner-Code": partner_code  # NEW: Echo partner code back in response
        }
    )


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """
    Retrieve a specific session and all its queries from Firestore.
    """
    try:
        session_ref = db.collection('sessions').document(session_id)
        session_doc = await session_ref.get()
        
        if not session_doc.exists:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session_data = session_doc.to_dict()
        
        # Get all queries in this session
        queries = []
        queries_ref = session_ref.collection('queries')
        async for query_doc in queries_ref.stream():
            query_data = query_doc.to_dict()
            query_data['id'] = query_doc.id
            queries.append(query_data)
        
        session_data['queries'] = queries
        
        return {"session": session_data}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/{user_id}/sessions")
async def get_user_sessions_endpoint(user_id: str, limit: int = 50):
    """
    Retrieve all sessions for a specific user.
    """
    try:
        sessions = await get_user_sessions(user_id, limit)
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        logger.error(f"Error retrieving user sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# --- NEW: PARTNER ANALYTICS ENDPOINTS ---

@app.get("/analytics/partner/{partner_code}/sessions")
async def get_partner_sessions(
    partner_code: str,
    limit: int = 100,
    x_partner_code: Optional[str] = Header(None, alias="X-Partner-Code")
):
    """
    Get all sessions for a specific partner.
    
    Args:
        partner_code: Partner identifier
        limit: Maximum number of sessions to return
        
    Headers:
        X-Partner-Code: Partner identifier for authentication (optional)
    """
    try:
        # Optional: Validate requesting partner matches queried partner
        requesting_partner = get_partner_code(x_partner_code)
        # if requesting_partner != partner_code and requesting_partner != "admin":
        #     raise HTTPException(status_code=403, detail="Unauthorized")
        
        sessions_ref = db.collection('sessions')
        query = sessions_ref.where('partner_code', '==', partner_code)\
                           .order_by('updated_at', direction=firestore.Query.DESCENDING)\
                           .limit(limit)
        
        sessions = []
        async for doc in query.stream():
            session_data = doc.to_dict()
            session_data['session_id'] = doc.id
            sessions.append(session_data)
        
        return {
            "partner_code": partner_code,
            "sessions": sessions,
            "count": len(sessions)
        }
        
    except Exception as e:
        logger.error(f"Error retrieving partner sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analytics/partner/{partner_code}/stats")
async def get_partner_stats(
    partner_code: str,
    x_partner_code: Optional[str] = Header(None, alias="X-Partner-Code")
):
    """
    Get usage statistics for a partner.
    
    Returns:
        {
            "partner_code": "flipkart_001",
            "total_sessions": 150,
            "total_queries": 450,
            "average_queries_per_session": 3.0
        }
    """
    try:
        sessions_ref = db.collection('sessions')
        query = sessions_ref.where('partner_code', '==', partner_code)
        
        total_sessions = 0
        total_queries = 0
        
        async for doc in query.stream():
            total_sessions += 1
            session_data = doc.to_dict()
            total_queries += session_data.get('query_count', 0)
        
        return {
            "partner_code": partner_code,
            "total_sessions": total_sessions,
            "total_queries": total_queries,
            "average_queries_per_session": total_queries / total_sessions if total_sessions > 0 else 0
        }
        
    except Exception as e:
        logger.error(f"Error calculating partner stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analytics/partners/all")
async def get_all_partners_stats(
    x_partner_code: Optional[str] = Header(None, alias="X-Partner-Code")
):
    """
    Get usage statistics for all partners.
    Useful for admin dashboard.
    
    Returns:
        [
            {"partner_code": "flipkart_001", "sessions": 150, "queries": 450},
            {"partner_code": "amazon_002", "sessions": 200, "queries": 600}
        ]
    """
    try:
        # Optional: Require admin authentication
        # requesting_partner = get_partner_code(x_partner_code)
        # if requesting_partner != "admin":
        #     raise HTTPException(status_code=403, detail="Admin access required")
        
        partners_stats = {}
        
        sessions_ref = db.collection('sessions')
        async for doc in sessions_ref.stream():
            session_data = doc.to_dict()
            partner = session_data.get('partner_code', 'unknown')
            
            if partner not in partners_stats:
                partners_stats[partner] = {
                    'partner_code': partner,
                    'sessions': 0,
                    'queries': 0
                }
            
            partners_stats[partner]['sessions'] += 1
            partners_stats[partner]['queries'] += session_data.get('query_count', 0)
        
        # Convert to list and sort by sessions
        partners_list = list(partners_stats.values())
        partners_list.sort(key=lambda x: x['sessions'], reverse=True)
        
        return {
            "partners": partners_list,
            "total_partners": len(partners_list)
        }
        
    except Exception as e:
        logger.error(f"Error getting all partners stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting Scheme Advisor API on port {port}...")
    uvicorn.run("api.main:app", host="0.0.0.0", port=port, reload=False)