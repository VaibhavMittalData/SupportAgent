# 🌊 ShopWave Autonomous AI Support Agent

An intelligent, fully autonomous customer support agent built using **LangGraph** and **Streamlit**. Designed to efficiently handle e-commerce queries, execute conditional company policies, and interact seamlessly with file-based mock databases—escalating only when required.

## 🚀 Features

* **Multi-Stage Ticket Triage:** Utilizes LangGraph state nodes to analyze incoming messages, parse user tone, and cleanly assess ticket urgency before actively responding to the customer.
* **Dynamic Policy Adherence:** Operates off a custom RAG-style `company_policy.md` handbook. It automatically cross-references product return windows, strict hygiene policies, and assesses customer VIP exceptions at runtime.
* **Autonomous Database Writing:** Reads existing localized JSON payloads for Customers, Orders, and Products. More importantly, when an issue must be escalated to human operators, the AI will build a tracked payload and actively write the formatted logs directly to the `tickets.json` database!
* **Escalation & Deadlock Prevention:** Features strict guardrails structured to prevent premature AI escalation requests. If the agent hits a firm policy wall, it gracefully halts execution, documents the block, and seamlessly hands the interactive form over to a manual support team.
* **Modern UI Console:** Leverages Streamlit to display detailed structural triage telemetry alongside the core interactive chat interface. 

## 🛠️ Technology Stack

* **Core Frameworks:** LangChain & LangGraph
* **Frontend Interface:** Streamlit
* **LLM Engine:** LangChain Groq (`llama-3.3-70b-versatile`)
* **Data Storage:** JSON local records (`sample_data/`)

## ⚙️ Quick Start Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/VaibhavMittalData/SupportAgent.git
   cd SupportAgent
   ```

2. **Install core dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Setup:**
   Create a root `.env` file and securely inject your Groq API key:
   ```env
   GROQ_API_KEY="your_groq_api_key_here"
   ```

4. **Launch the Support Console:**
   ```bash
   streamlit run app.py
   ```

---
*Built via Agentic AI prototyping!*
