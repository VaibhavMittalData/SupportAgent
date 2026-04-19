import json
import os
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

# Helper function to find a customer by email
def _find_customer_by_email(email: str) -> Optional[Dict[str, Any]]:
    for c in CUSTOMERS:
        if c.get("email", "").lower() == email.lower():
            return c
    return None

@tool
def get_customer_info(email: str) -> str:
    """Get customer information by email. Includes their VIP status, total spent, and any special notes."""
    res = _find_customer_by_email(email)
    return json.dumps(res) if res else "Customer not found."

@tool
def get_order_details(order_id: str) -> str:
    """Get order details by order ID. Includes product ID, order status, return deadline, and refund status."""
    for o in ORDERS:
        if o.get("order_id", "").upper() == order_id.upper():
            return json.dumps(o)
    return "Order not found."

@tool
def get_product_policy(product_id: str) -> str:
    """Get the return policy and product details for a given product ID."""
    for p in PRODUCTS:
        if p.get("product_id", "").upper() == product_id.upper():
            return json.dumps({
                "name": p.get("name"),
                "category": p.get("category"),
                "return_window_days": p.get("return_window_days"),
                "returnable": p.get("returnable"),
                "notes": p.get("notes")
            })
    return "Product not found."

@tool
def check_existing_tickets(email: str, order_id: Optional[str] = None) -> str:
    """Check if there are any existing tickets for this user and optionally for a specific order."""
    results = []
    for t in TICKETS:
        if t.get("customer_email", "").lower() == email.lower():
            # If order_id is provided, only return tickets mentioning that order ID
            if order_id and order_id.upper() not in t.get("body", "").upper():
                continue
            results.append(t)
    return json.dumps(results) if results else "No existing tickets found."

@tool
def process_refund(order_id: str, reason: str) -> str:
    """Process a refund for an order. Use this tool ONLY if the return policy allows it, or the customer is a VIP with an exception."""
    order = None
    for o in ORDERS:
        if o.get("order_id", "").upper() == order_id.upper():
            order = o
            break
            
    if not order:
        return f"Order {order_id} not found."
    
    if order.get("refund_status") == "refunded":
        return f"Order {order_id} has already been refunded."
        
    order["refund_status"] = "refunded"
    return f"Refund for order {order_id} processed successfully. Reason logged: {reason}"

@tool
def process_exchange(order_id: str, issue: str) -> str:
    """Process an product exchange/replacement for an order. E.g., for wrong size, wrong color, or damaged item."""
    return f"Exchange initiated for order {order_id}. Reason: {issue}. A return label has been generated."

@tool
def create_ticket(email: str, issue: str, order_id: Optional[str] = None) -> str:
    """Create a new support ticket in the database. Call this tool when an issue cannot be resolved autonomously and needs to be escalated or tracked."""
    import uuid
    ticket_id = f"TKT-NEW-{str(uuid.uuid4())[:8].upper()}"
    new_ticket = {
        "ticket_id": ticket_id,
        "customer_email": email,
        "order_id": order_id,
        "status": "open",
        "body": issue
    }
    TICKETS.append(new_ticket)
    save_json("tickets.json", TICKETS)
    return f"Ticket {ticket_id} created successfully."
