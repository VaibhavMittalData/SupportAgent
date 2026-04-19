import json
import os
import datetime
from pathlib import Path
from langchain_core.tools import tool
from typing import Dict, Any, Optional, List

DATA_DIR = Path(__file__).parent / "sample_data"

def load_json(filename: str) -> list:
    filepath = DATA_DIR / filename
    if not filepath.exists():
        print(f"Warning: Data file {filepath} not found.")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(filename: str, data: list):
    filepath = DATA_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

CUSTOMERS = load_json("customers.json")
ORDERS = load_json("orders.json")
PRODUCTS = load_json("products.json")
TICKETS = load_json("tickets.json")

def _find_customer_by_email(email: str) -> Optional[Dict[str, Any]]:
    for c in CUSTOMERS:
        if c.get("email", "").lower() == email.lower():
            return c
    return None

def _find_customer_by_id(customer_id: str) -> Optional[Dict[str, Any]]:
    for c in CUSTOMERS:
        if c.get("customer_id", "").upper() == customer_id.upper():
            return c
    return None

def _find_order_by_id(order_id: str) -> Optional[Dict[str, Any]]:
    for o in ORDERS:
        if o.get("order_id", "").upper() == order_id.upper():
            return o
    return None

def _find_product_by_id(product_id: str) -> Optional[Dict[str, Any]]:
    for p in PRODUCTS:
        if p.get("product_id", "").upper() == product_id.upper():
            return p
    return None

# ------------- READ / LOOKUP -------------

@tool
def get_order(order_id: str) -> str:
    """Order details, status, timestamps"""
    res = _find_order_by_id(order_id)
    return json.dumps(res) if res else "Order not found."

@tool
def get_customer(email: str) -> str:
    """Customer profile, tier, history"""
    res = _find_customer_by_email(email)
    return json.dumps(res) if res else "Customer not found."

@tool
def get_product(product_id: str) -> str:
    """Product metadata, category, warranty"""
    res = _find_product_by_id(product_id)
    return json.dumps(res) if res else "Product not found."

@tool
def search_knowledge_base(query: str) -> str:
    """Policy & FAQ semantic search"""
    policy_path = Path(__file__).parent / "company_policy.md"
    if not policy_path.exists():
        return "Knowledge base not found."
    with open(policy_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    query_words = set(query.lower().split())
    sections = content.split("## ")
    
    scored_sections = []
    for section in sections:
        score = sum(1 for w in query_words if w in section.lower())
        if score > 0:
            scored_sections.append((score, "## " + section))
            
    if scored_sections:
        scored_sections.sort(key=lambda x: x[0], reverse=True)
        return "\n".join([s[1] for s in scored_sections[:2]])
    else:
        return content

# ------------- WRITE / ACT -------------

@tool
def check_refund_eligibility(order_id: str) -> str:
    """Returns eligibility + reason. May throw errors."""
    order = _find_order_by_id(order_id)
    if not order:
        return json.dumps({"eligible": False, "reason": "Order not found."})
        
    product = _find_product_by_id(order.get("product_id", ""))
    customer = _find_customer_by_id(order.get("customer_id", ""))
    
    if not product or not customer:
        return json.dumps({"eligible": False, "reason": "Missing product or customer context."})
        
    if order.get("refund_status") == "refunded":
        return json.dumps({"eligible": False, "reason": "Already refunded."})
        
    delivery_date_str = order.get("delivery_date")
    if not delivery_date_str:
        return json.dumps({"eligible": False, "reason": "Order not yet delivered."})
    
    return_deadline_str = order.get("return_deadline")
    if return_deadline_str:
        try:
            deadline = datetime.datetime.strptime(return_deadline_str, "%Y-%m-%d").date()
            # Assuming sample data refers to 2024, let's use today's date if it were realistic,
            # but since sample data is fixed to March 2024, we'll compare dynamically vs today.
            today = datetime.datetime.now().date()
            if today > deadline:
                tier = customer.get("tier", "standard").lower()
                if tier == "vip":
                    return json.dumps({"eligible": True, "reason": "Outside return window, but customer is VIP."})
                elif tier == "premium":
                    if (today - deadline).days <= 3:
                        return json.dumps({"eligible": True, "reason": "Outside return window, but Premium tier 1-3 day grace period applies."})
                    return json.dumps({"eligible": False, "reason": f"Past return window ({deadline}). Premium grace period exceeded."})
                else:
                    return json.dumps({"eligible": False, "reason": f"Past return window ({deadline})."})
            return json.dumps({"eligible": True, "reason": "Within return window."})
        except Exception as e:
             return json.dumps({"eligible": False, "reason": str(e)})

    return json.dumps({"eligible": True, "reason": "Eligible for refund."})

@tool
def issue_refund(order_id: str, amount: float) -> str:
    """IRREVERSIBLE - must check eligibility first"""
    order = _find_order_by_id(order_id)
    if not order:
        return f"Order {order_id} not found."
    
    if order.get("refund_status") == "refunded":
        return f"Order {order_id} has already been refunded."
        
    for o in ORDERS:
        if o.get("order_id", "").upper() == order_id.upper():
            o["refund_status"] = "refunded"
            o["refund_amount"] = amount
            break
            
    save_json("orders.json", ORDERS)
    return f"Refund of ${amount} for order {order_id} processed successfully."

@tool
def send_reply(ticket_id: str, message: str) -> str:
    """Sends response to the customer"""
    for t in TICKETS:
        if t.get("ticket_id") == ticket_id:
            if "replies" not in t:
                t["replies"] = []
            t["replies"].append({"from": "agent", "message": message, "timestamp": datetime.datetime.now().isoformat()})
            save_json("tickets.json", TICKETS)
            return "Reply sent successfully."
            
    new_ticket = {
        "ticket_id": ticket_id,
        "status": "open",
        "replies": [{"from": "agent", "message": message, "timestamp": datetime.datetime.now().isoformat()}]
    }
    TICKETS.append(new_ticket)
    save_json("tickets.json", TICKETS)
    return f"Ticket {ticket_id} created and reply sent successfully."

@tool
def escalate(ticket_id: str, summary: str, priority: str) -> str:
    """Routes to human with full context"""
    for t in TICKETS:
        if t.get("ticket_id") == ticket_id:
            t["status"] = "escalated"
            t["escalation_summary"] = summary
            t["priority"] = priority
            save_json("tickets.json", TICKETS)
            return "Ticket escalated successfully."
            
    new_ticket = {
        "ticket_id": ticket_id,
        "status": "escalated",
        "escalation_summary": summary,
        "priority": priority
    }
    TICKETS.append(new_ticket)
    save_json("tickets.json", TICKETS)
    return f"Ticket {ticket_id} escalated successfully."
