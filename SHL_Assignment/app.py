from fastapi import FastAPI
from pydantic import BaseModel
import json
import re

app = FastAPI()

# Load catalog with proper encoding
with open("catalog.json", "r", encoding="utf-8") as f:
    catalog = json.load(f)

class Message(BaseModel):
    role: str
    content: str

class Recommendation(BaseModel):
    name: str
    url: str
    test_type: str

class ChatRequest(BaseModel):
    messages: list[Message]

class ChatResponse(BaseModel):
    reply: str
    recommendations: list[Recommendation] = []
    end_of_conversation: bool = False

def get_test_type_from_keys(keys):
    """Map SHL keys to single letter test types"""
    if not keys:
        return "O"  # Other
    
    key_mapping = {
        "Ability & Aptitude": "A",
        "Knowledge & Skills": "K",
        "Personality & Behavior": "P",
        "Biodata & Situational Judgment": "B",
        "Assessment Exercises": "E",
        "Simulations": "S",
        "Competencies": "C",
        "Development & 360": "D"
    }
    
    # Return first matching key type
    for key in keys:
        if key in key_mapping:
            return key_mapping[key]
    return "O"

def retrieve_relevant_assessments(query, conversation_history, limit=10):
    """Retrieve relevant assessments from catalog based on query and context"""
    
    # Build full context from all messages
    full_text = query.lower() + " " + " ".join([msg.content.lower() for msg in conversation_history])
    
    scored_items = []
    
    for item in catalog:
        score = 0
        name_lower = item.get("name", "").lower()
        desc_lower = item.get("description", "").lower()
        job_levels_raw = item.get("job_levels_raw", "").lower()
        keys_str = " ".join(item.get("keys", [])).lower()
        
        # Score based on keyword matches
        keywords = [kw for kw in full_text.split() if len(kw) > 2]
        for keyword in keywords:
            if keyword in name_lower:
                score += 5
            if keyword in keys_str:
                score += 3
            if keyword in job_levels_raw:
                score += 2
            if keyword in desc_lower:
                score += 1
        
        if score > 0:
            scored_items.append((score, item))
    
    # Sort by score and return top items
    scored_items.sort(reverse=True, key=lambda x: x[0])
    return [item for _, item in scored_items[:limit]]

def has_enough_context(messages):
    """Check if we have enough context to make recommendations"""
    if not messages:
        return False
    
    full_text = " ".join([msg.content.lower() for msg in messages])
    
    # We need indication of job level or role type, and some assessment need
    has_level_or_role = any(word in full_text for word in [
        "entry-level", "entry level", "junior", "mid", "mid-level", "mid level", "senior", "executive", "director",
        "developer", "sales", "analyst", "manager", "leadership", "graduate", "contact center", "contact centre",
        "financial", "rust", "java", "python", "engineer", "intelligence"
    ])
    
    has_need = any(word in full_text for word in [
        "assessment", "personality", "cognitive", "knowledge", "skill", "behavior", "behaviour",
        "reasoning", "screening", "solution", "recruit", "hiring", "test", "evaluation"
    ])
    
    return has_level_or_role and has_need

def is_off_topic(message):
    """Check if message is asking about off-topic items"""
    lower_msg = message.lower()
    off_topic_keywords = [
        "salary", "compensation", "pay",
        "legal", "lawyer", "law suit",
        "hiring practices", "discrimination",
        "patent", "proprietary",
        "how much does it cost",
        "price"
    ]
    return any(keyword in lower_msg for keyword in off_topic_keywords)

def generate_agent_response(messages, has_recs, turn_number):
    """Generate an appropriate agent response"""
    
    latest_user_msg = messages[-1].content if messages else ""
    lower_msg = latest_user_msg.lower()
    
    if turn_number == 1:
        # First turn - always ask clarifying questions
        return "Happy to help. Could you tell me more about the role, seniority level, and what specific hiring challenges you're facing?"
    
    # Check if user is asking for comparison
    if any(word in lower_msg for word in ["difference", "compare", "vs", "between"]):
        return "Let me explain the key differences between these assessments for your needs."
    
    # Check if user is confirming
    if any(word in lower_msg for word in ["perfect", "great", "thanks", "confirmed", "yes", "exactly"]):
        if has_recs:
            return "Excellent. You're all set with a solid assessment stack."
        return "Great!"
    
    # Check if user is refining
    if any(word in lower_msg for word in ["actually", "also add", "plus", "additionally", "remove"]):
        return "Got it, let me update your recommendations with that refinement."
    
    # Default response  
    if has_recs:
        return "Here are the assessments that best match your hiring needs:"
    else:
        return "To find the right assessments, could you tell me a bit more about the role, experience level, and what you're assessing?"

def should_end_conversation(messages):
    """Determine if conversation should end"""
    if len(messages) < 4:
        return False
    
    latest_msg = messages[-1].content.lower()
    
    # End if user confirms or says they're satisfied
    return any(word in latest_msg for word in ["perfect", "great", "thanks", "that's all", "that covers", "confirmed"])

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat")
def chat(req: ChatRequest) -> ChatResponse:
    """Handle chat requests"""
    
    if not req.messages:
        return ChatResponse(
            reply="Hello! I'm here to help you find the right SHL assessments for your hiring needs. Tell me about the role you're trying to fill, the seniority level, and what you're looking to assess.",
            recommendations=[],
            end_of_conversation=False
        )
    
    # Get latest user message
    user_message = req.messages[-1].content
    
    # Check for off-topic requests
    if is_off_topic(user_message):
        return ChatResponse(
            reply="I can only help with SHL assessment recommendations. I'm not able to assist with that topic.",
            recommendations=[],
            end_of_conversation=False
        )
    
    # Check if we should provide recommendations
    turn_number = (len(req.messages) + 1) // 2  # Count user turns (1, 2, 3, ...)
    should_recommend = has_enough_context(req.messages) and turn_number > 1
    
    recommendations = []
    if should_recommend:
        relevant_items = retrieve_relevant_assessments(user_message, req.messages, limit=10)
        if relevant_items:
            recommendations = []
            for item in relevant_items:
                test_type = get_test_type_from_keys(item.get("keys", []))
                recommendations.append(Recommendation(
                    name=item.get("name", "Unknown"),
                    url=item.get("link", ""),
                    test_type=test_type
                ))
    
    # Generate response
    reply = generate_agent_response(req.messages, bool(recommendations), turn_number)
    
    # Determine if conversation should end
    end_conversation = should_end_conversation(req.messages) and bool(recommendations)
    
    return ChatResponse(
        reply=reply,
        recommendations=recommendations,
        end_of_conversation=end_conversation
    )