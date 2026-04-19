# ShopWave Support Agent - Architecture Breakdown

This file outlines the internal mechanics, structural pipelines, and logic flows powering the ShopWave Autonomous AI Support Agent. 

## 1. High-Level Component Stack

The system embraces a strictly decoupled design: separating the user interface, state management, localized logic, and database schemas.

```mermaid
graph LR
    UI[Streamlit UI] <--> LG[LangGraph Engine]
    
    subgraph Backend Execution
        LG <--> LLM[Groq: llama-3.3-70b]
    end
    
    subgraph Data Layer
        LG <--> DB[(Local JSON Database)]
        DB <--> Pol[(company_policy.md)]
    end
```

* **Streamlit UI (`app.py`)**: Intercepts chat, manages user display, and seamlessly parses tool call metadata to show real-time agent responses. 
* **LangGraph Engine (`agent.py`)**: The central state-machine that routes information, processes history, and builds JSON context before querying the model.
* **LLM Engine**: Powers the semantic reasoning, utilizing specific tool calls via the Groq endpoint.
* **Company Policy (`company_policy.md`)**: A deterministic rulebook securely accessed via semantic search tools rather than static prompt injection.
* **JSON Database (`database.py`)**: Local JSON structures mocking a standard SQL database for isolated writes and reads.

---

## 2. Core LangGraph State Machine

The agent doesn't just guess responses. It is built as a cyclic graph (state machine) using `LangGraph`. Below is the exact logical routing mapping out how the agent decides its next behavior based on conditional edges.

```mermaid
graph TD
    classDef startend fill:#4ECDC4,stroke:#333,stroke-width:2px;
    classDef node fill:#1A1A1A,stroke:#FF6B6B,stroke-width:2px,color:#fff;
    classDef tools fill:#FFD166,stroke:#333,stroke-width:2px,color:#000;

    Start((START)):::startend --> Triage(triage_node):::node
    
    Triage --> Resolve(resolve_node):::node
    
    Resolve --> COND{should_continue}
    
    COND -- calls_tool --> Tools[/Tool Node/]::tools
    Tools --> Resolve
    
    COND -- conversational_reply --> End((END)):::startend
```

### Node Explanations
1. **`triage_node`**: Acts as a gateway proxy. It intercepts the raw user text and statically extracts data (`category`, `tone`, `email`, `order_id`). It immediately interfaces with the database natively via standard python functions to inject "Old Customer/Issue" flags before the core model ever talks.
2. **`resolve_node`**: The core "brain" of the agent. It securely interpolates context parameters dynamically and prompts the model to make decisions. Unlike legacy versions, it relies ENTIRELY on dynamic lookups via the `search_knowledge_base` tool to access policy logic, saving immense prompt token space.
3. **`Tool Node`**: Automatically binds tools divided into two classes:
   - **READ / LOOKUP**: `get_order`, `get_customer`, `get_product`, `search_knowledge_base`.
   - **WRITE / ACT**: `check_refund_eligibility`, `issue_refund`, `send_reply`, `escalate`.
   LangGraph routes requests here, builds the JSON payload, executes Python, and returns the result back to `resolve_node` for final translation.

---

## 3. Escalation & Guardrail Workflows

To prevent premature escalation or prompt hijacking, the architecture employs aggressive sequence routing leveraging specific Write/Act tools:

```mermaid
sequenceDiagram
    participant User
    participant Streamlit UI
    participant Agent Pipeline
    participant JSON Database
    
    User->>Streamlit UI: "I want a refund. Talk to a human."
    Streamlit UI->>Agent Pipeline: Initial TicketState Payload
    
    Agent Pipeline->>Agent Pipeline: triage_node evaluates Tone=Frustrated
    
    Agent Pipeline->>JSON Database: check_refund_eligibility tool assesses dates/tiers
    JSON Database-->>Agent Pipeline: Returns Policy/Eligibility Blockers
    
    note over Agent Pipeline: Model assesses context
    
    alt Premature Guardrail Hit
        Agent Pipeline->>JSON Database: send_reply("What specific issue are you having?")
        Agent Pipeline-->>Streamlit UI: Reads output and prompts user
    else Policy Blocked & VIP
        Agent Pipeline->>JSON Database: escalate Tool (Updates JSON Status)
        Agent Pipeline-->>Streamlit UI: Flag: status=escalated
        Streamlit UI-->>User: 🚨 ESCALATED!
    end
```
