import os
import uuid
import datetime
from typing import TypedDict, List, Dict, Any, Literal, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from langgraph.prebuilt import ToolNode
import database # our mock module
from dotenv import load_dotenv

load_dotenv()

class TicketState(TypedDict):
    # Core User Input
    customer_message: str
    email: str
    order_id: str
    
    # Analysis output
    category: str
    tone: str
    is_old_customer: bool
    is_old_issue: bool
    urgency: str
    token: str
    
    # Execution Tracking
    messages: Annotated[list[BaseMessage], add_messages]
    status: Literal["open", "resolved", "escalated", "pending"]
    escalation_summary: str
    audit_log: List[str]

class TriageOutput(BaseModel):
    category: Literal["refund", "request", "size", "item not match", "wrong item", "delivery", "cancel", "other", "unknown"] = Field(description="The category of the issue. Use 'unknown' if unclear.")
    tone: Literal["frustrated", "neutral", "polite", "urgent", "unknown"] = Field(description="The tone of the customer. Use 'unknown' if unclear.")
    email: str = Field(description="The customer's email address if found in the text, otherwise 'unknown'")
    order_id: str = Field(description="The order ID (e.g. ORD-1001) if found, otherwise 'unknown'")

# Initialize the Groq model
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)

TOOLS = [
    database.get_order, 
    database.get_customer, 
    database.get_product, 
    database.search_knowledge_base,
    database.check_refund_eligibility,
    database.issue_refund,
    database.send_reply,
    database.escalate
]
llm_with_tools = llm.bind_tools(TOOLS)

def init_state(state: TicketState) -> TicketState:
    if "audit_log" not in state or not state["audit_log"]:
        state["audit_log"] = []
    return state

def log_audit(state: TicketState, message: str) -> TicketState:
    print(f"[*] {message}")
    if "audit_log" not in state or state["audit_log"] is None:
        state["audit_log"] = []
    state["audit_log"].append(f"[{datetime.datetime.now().isoformat()}] {message}")
    return state

def triage_node(state: TicketState) -> dict:
    log_audit(state, "Starting Triage Node.")
    
    system_prompt = """You are a customer support triage agent. 
    Analyze the following conversation and extract the 'category', 'tone', 'email', and 'order_id' based on the user's latest inquiry and prior context.
    """
    
    messages_for_triage = [SystemMessage(content=system_prompt)] + state["messages"] + [HumanMessage(content=state["customer_message"])]
    
    structured_llm = llm.with_structured_output(TriageOutput)
    triage_result = structured_llm.invoke(messages_for_triage)
    
    updates = {
        "category": triage_result.category,
        "tone": triage_result.tone,
        "email": triage_result.email,
        "order_id": triage_result.order_id,
        "audit_log": [f"Extraction complete: category={triage_result.category}, tone={triage_result.tone}, email={triage_result.email}, order_id={triage_result.order_id}"]
    }
    log_audit(state, updates["audit_log"][0])
    
    # Old vs New Customer checking Database
    customer_info_str = database.get_customer.invoke({"email": updates["email"]}) if updates["email"] != "unknown" else None
    
    import json
    customer = None
    if customer_info_str and customer_info_str != "Customer not found.":
        try:
            customer = json.loads(customer_info_str)
        except json.JSONDecodeError:
            customer = None
            
    updates["is_old_customer"] = bool(customer)
    
    db_context_msg = "No customer context found."
    if customer:
        log_audit(state, f"Found existing customer: {customer.get('tier')} tier.")
        db_context_msg = f"Customer Database Info: Tier {customer.get('tier')}, Total Orders {customer.get('total_orders')}. Notes: {customer.get('notes')}"
    else:
        log_audit(state, "New customer or email not found.")

    # Old vs New Issue
    existing = []
    if updates["email"] != "unknown":
        for t in database.TICKETS:
            if t.get("customer_email", "").lower() == updates["email"].lower():
                if updates["order_id"] != "unknown" and updates["order_id"].upper() not in t.get("body", "").upper():
                    continue
                existing.append(t)

    updates["is_old_issue"] = len(existing) > 0
    if updates["is_old_issue"]:
        log_audit(state, "Issue identified as an OLD issue (existing ticket matches).")
        updates["token"] = existing[0].get("ticket_id", "TKT-UNKNOWN")
    else:
        token_id = f"TKT-{str(uuid.uuid4())[:8].upper()}"
        updates["token"] = token_id
        log_audit(state, f"Generated NEW ticket token: {token_id}")
        
    # Urgency
    if updates["tone"] in ["frustrated", "urgent"] or updates["category"] in ["cancel", "wrong item", "delivery"]:
        updates["urgency"] = "High"
    else:
        updates["urgency"] = "Normal"
    log_audit(state, f"Assigned urgency: {updates['urgency']}")

    initial_messages = [
        SystemMessage(content=db_context_msg),
        HumanMessage(content=state["customer_message"])
    ]
    updates["messages"] = initial_messages
    updates["status"] = "open"
    return updates

def resolve_node(state: TicketState) -> dict:
    log_audit(state, "Entering Resolve Node.")

    system_prompt = f"""You are a helpful autonomous customer support agent for ShopWave.
    The customer ticket has been triaged. 
    Category: {state.get('category')}
    Urgency: {state.get('urgency')}
    Customer is Old?: {state.get('is_old_customer')}
    Token: {state.get('token')}
    
    You MUST search the knowledge base using search_knowledge_base to check policies before making any refund or exchange decisions.
    
    1. Look up the order details, customer tier, and product details.
    2. Before issuing any refund, ALWAYS call check_refund_eligibility.
    3. Issue a refund using issue_refund only if check_refund_eligibility confirms it is eligible.
    4. You MUST use the send_reply tool to log responses. However, immediately after utilizing the tool, you MUST include the actual information/answer in your conversational text output to the user so they can read it!
    5. If a situation violates policy, is a warranty claim, requires a supervisor, or is highly complex, use the escalate tool to route to human agents. Do not just output ESCALATE_TO_HUMAN.
    6. CRITICAL STYLE GUIDE: Keep your responses exceptionally short and concise. Do not explain policies in long paragraphs.
    """
    msgs = [SystemMessage(content=system_prompt)] + state["messages"]
    
    response = llm_with_tools.invoke(msgs)
    log_audit(state, f"Agent responded. tool_calls={bool(response.tool_calls)}")
    return {"messages": [response]}

def should_continue(state: TicketState) -> Literal["tools", "END"]:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return "END"

# Build Graph
builder = StateGraph(TicketState)

builder.add_node("triage", triage_node)
builder.add_node("resolve_node", resolve_node)
builder.add_node("tools", ToolNode(TOOLS))

builder.add_edge(START, "triage")
builder.add_edge("triage", "resolve_node")
builder.add_conditional_edges("resolve_node", should_continue, {
    "tools": "tools",
    "END": END
})
builder.add_edge("tools", "resolve_node")

graph = builder.compile()

if __name__ == "__main__":
    from pprint import pprint
    # Test compilation
    print("Graph compiled successfully!")
