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
    database.get_customer_info, 
    database.get_order_details, 
    database.get_product_policy, 
    database.check_existing_tickets,
    database.process_refund,
    database.process_exchange,
    database.create_ticket
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
    customer_info_str = database.get_customer_info.invoke({"email": updates["email"]}) if updates["email"] != "unknown" else None
    
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
    existing_tickets_str = database.check_existing_tickets.invoke({"email": updates["email"], "order_id": updates["order_id"] if updates["order_id"] != "unknown" else None}) if updates["email"] != "unknown" else "[]"
    
    existing = []
    if existing_tickets_str and existing_tickets_str != "No existing tickets found.":
        try:
            existing = json.loads(existing_tickets_str)
        except json.JSONDecodeError:
            existing = []

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
    policy_path = os.path.join(os.path.dirname(__file__), "company_policy.md")
    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            company_policy = f.read()
    except FileNotFoundError:
        company_policy = "Policy documentation not found. Escalate everything to human."

    system_prompt = f"""You are a helpful autonomous customer support agent for ShopWave.
    The customer ticket has been triaged. 
    Category: {state.get('category')}
    Urgency: {state.get('urgency')}
    Customer is Old?: {state.get('is_old_customer')}
    Token: {state.get('token')}
    
    You have tools to look up order details, product policies, and to process refunds or exchanges.
    1. If the user provided an order ID, strongly verify the order details. Once you have the order details, you MUST look up the product policy for the specific product_id in the order.
    2. Evaluate the customer's request rigidly against the official ShopWave Employee Policy Handbook provided below.
    3. If you resolve the issue, inform the user directly, focusing ONLY on the status of their request without revealing internal classifications like "standard tier" or "VIP".
    4. CRITICAL STYLE GUIDE: Keep your responses exceptionally short and concise (under 2 sentences). Do not write long paragraphs explaining policies. Be extremely brief.
    5. DO NOT ESCALATE PREMATURELY: If a customer demands a human but has NOT provided an order ID or explicitly stated their issue, you MUST ask them what their issue is first. Never output ESCALATE_TO_HUMAN instantly.
    
    --- COMPANY POLICY HANDBOOK ---
    {company_policy}
    --- END OF COMPANY POLICY HANDBOOK ---
    """
    msgs = [SystemMessage(content=system_prompt)] + state["messages"]
    
    response = llm_with_tools.invoke(msgs)
    log_audit(state, f"Agent responded. tool_calls={bool(response.tool_calls)}")
    return {"messages": [response]}

def should_continue(state: TicketState) -> Literal["tools", "escalate_node", "END"]:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    msg_content = str(last_message.content).upper()
    if "ESCALATE_TO_HUMAN" in msg_content:
        return "escalate_node"
    return "END"

def escalate_node(state: TicketState) -> dict:
    log_audit(state, "Escalating ticket to human.")
    summary = f"Escalation required. Ticket {state.get('token')} | Context: unable to autonomously resolve."
    return {"escalation_summary": summary, "status": "escalated"}

# Build Graph
builder = StateGraph(TicketState)

builder.add_node("triage", triage_node)
builder.add_node("resolve_node", resolve_node)
builder.add_node("tools", ToolNode(TOOLS))
builder.add_node("escalate_node", escalate_node)

builder.add_edge(START, "triage")
builder.add_edge("triage", "resolve_node")
builder.add_conditional_edges("resolve_node", should_continue, {
    "tools": "tools",
    "escalate_node": "escalate_node",
    "END": END
})
builder.add_edge("tools", "resolve_node")
builder.add_edge("escalate_node", END)

graph = builder.compile()

if __name__ == "__main__":
    from pprint import pprint
    # Test compilation
    print("Graph compiled successfully!")
