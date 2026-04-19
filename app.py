import streamlit as st
import os
from agent import graph
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage

load_dotenv()

st.set_page_config(page_title="ShopWave Support Agent", page_icon="🌊", layout="wide")

# Modern Streamlit UI Design
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .stAppHeader { display: none; }
    
    .title-container {
        text-align: center;
        margin-bottom: 2rem;
        padding: 2rem 0;
        background: linear-gradient(180deg, rgba(78,205,196,0.1) 0%, rgba(255,255,255,0) 100%);
        border-radius: 15px;
    }

    .title-text {
        background: -webkit-linear-gradient(45deg, #FF6B6B, #4ECDC4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 3.5rem;
        margin-bottom: 0.2rem;
        letter-spacing: -1px;
    }
    
    .subtitle-text {
        font-size: 1.1rem;
        color: #888;
        font-weight: 400;
    }

    /* Elegant Card Design for Metrics */
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        color: #4ECDC4 !important;
        font-weight: 800 !important;
    }
    
    div[data-testid="metric-container"] {
        background: rgba(0, 0, 0, 0.03);
        border-radius: 12px;
        padding: 15px;
        border: 1px solid rgba(0, 0, 0, 0.05);
        transition: all 0.3s ease;
    }
    
    @media (prefers-color-scheme: dark) {
        div[data-testid="metric-container"] {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
    }
    
    div[data-testid="metric-container"]:hover {
        transform: translateY(-5px);
        box-shadow: 0 10px 20px rgba(0,0,0,0.1);
    }

    /* Responsive Chat Input */
    div[data-testid="stChatInput"] {
        padding-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# State initialization
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [{"role": "assistant", "content": "👋 Welcome to the ShopWave AI Support Console. How can I help you today? Please include your order ID and email where applicable."}]
if "last_state" not in st.session_state:
    st.session_state.last_state = None

st.markdown('''
<div class="title-container">
    <div class="title-text">✨ ShopWave Agent</div>
    <div class="subtitle-text">Your intelligent, autonomous retail support assistant</div>
</div>
''', unsafe_allow_html=True)

# Sidebar mapping directly to our Triage details
with st.sidebar:
    st.header("Agent Triage Analytics")
    st.markdown("Real-time extraction via `LangGraph`")
    st.divider()
    
    state = st.session_state.last_state
    if state:
        col1, col2 = st.columns(2)
        col1.metric("Token ID", state.get("token", "N/A"))
        
        urgency = state.get("urgency", "Normal")
        col2.metric("Urgency", urgency, delta="Escalated" if urgency=="High" else None, delta_color="inverse")
        
        col3, col4 = st.columns(2)
        col3.metric("Category", str(state.get("category")).capitalize())
        col4.metric("Tone", str(state.get("tone")).capitalize())
        
        st.divider()
        st.subheader("Database Status")
        st.metric("Customer Type", "Returning (Old)" if state.get("is_old_customer") else "New")
        st.metric("Issue Match", "Existing Ticket Found" if state.get("is_old_issue") else "New Issue")
            
    else:
        st.info("Awaiting initial user query to populate triage telemetry...")

# Main Chat Interface
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("Enter your request... (e.g. Cancel order ORD-1012)")

if user_input:
    # Show user message
    st.chat_message("user").markdown(user_input)
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    
    if st.session_state.get("is_escalated", False):
        with st.chat_message("assistant"):
            reply = f"Thank you. We have recorded your number as {user_input}. A representative will reach out shortly."
            st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
    else:
        with st.chat_message("assistant"):
            with st.spinner("Agent is analyzing and executing tools..."):
            
                # Build memory context from session chat history (excluding the current user input)
                chat_history_msgs = []
                for msg in st.session_state.chat_history[:-1]:
                    if msg["role"] == "user":
                        chat_history_msgs.append(HumanMessage(content=msg["content"]))
                    elif msg["role"] == "assistant":
                        chat_history_msgs.append(AIMessage(content=msg["content"]))
                        
                initial_state = {
                    "customer_message": user_input,
                    "email": "unknown",
                    "order_id": "unknown",
                    "category": "",
                    "tone": "",
                    "is_old_customer": False,
                    "is_old_issue": False,
                    "urgency": "Normal",
                    "token": "",
                    "messages": chat_history_msgs,
                    "status": "open",
                    "escalation_summary": "",
                    "audit_log": []
                }
                
                try:
                    final_state = graph.invoke(initial_state, config={"recursion_limit": 50})
                    st.session_state.last_state = final_state
                    
                    # Check Escalation
                    if final_state.get("status") == "escalated":
                        st.session_state["is_escalated"] = True
                        phone = "on record"
                        email = final_state.get("email")
                        if email and email != "unknown":
                            try:
                                import json
                                with open("sample_data/customers.json", "r") as f:
                                    customers = json.load(f)
                                    for c in customers:
                                        if c.get("email").lower() == email.lower():
                                            phone = c.get("phone")
                                            break
                            except Exception:
                                pass
                        reply = f"🚨 **ESCALATED**: A person will contact you within 5 minutes on your mobile number ({phone}). If you would like us to call a particular number, please enter it below."
                    else:
                        reply = None
                        for msg in reversed(final_state["messages"]):
                            if msg.type == "human":
                                break
                            if getattr(msg, "tool_calls", None):
                                for tc in msg.tool_calls:
                                    if tc.get("name") == "send_reply":
                                        reply = tc.get("args", {}).get("message")
                                        break
                                if reply: break
                        
                        if not reply:
                            last_msg = final_state["messages"][-1]
                            reply_content = last_msg.content
                            if isinstance(reply_content, list):
                                reply = "".join(item.get("text", "") for item in reply_content if isinstance(item, dict) and "text" in item)
                                if not reply:
                                    reply = str(reply_content)
                            else:
                                reply = str(reply_content)
                        
                    st.markdown(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    
                    # Render Audit Log Expander right below
                    with st.expander("Show Graph Audit Log"):
                        for log in final_state.get("audit_log", []):
                            st.text(log)
                            
                    st.rerun()
                    
                except Exception as e:
                    err_msg = f"❌ Error executing graph: {e}"
                    st.error(err_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": err_msg})
