# EAGV3: Growing-Graph Multi-Agent Orchestration & Browser Cascade (Session 9)

An advanced multi-agent orchestrator framework designed to execute complex tasks by dynamically generating and executing Directed Acyclic Graphs (DAGs) of specialized agent skills. It integrates a **three-tier Browser Skill cascade** (Extract, Accessibility tree, and Vision) with robust runtime recovery mechanisms and cost-attribution tracking.

---

## 🏗️ Solution Architecture

The framework coordinates task execution by separating graph orchestration, skill execution, recovery routing, and LLM provider gateway management. Below is the solution architecture diagram:

```mermaid
flowchart TD
    %% Styling
    classDef orchestrator fill:#e6f4ea,stroke:#137333,stroke-width:2px;
    classDef skill fill:#fef7e0,stroke:#b06000,stroke-width:2px;
    classDef gateway fill:#f3e8fd,stroke:#681da8,stroke-width:2px;
    classDef recovery fill:#fce8e6,stroke:#c5221f,stroke-width:2px;
    classDef output fill:#e8f0fe,stroke:#1967d2,stroke-width:2px;

    User([User Query]) --> Flow[Orchestrator: flow.py]
    
    subgraph Orchestration [DAG Orchestration Engine]
        Flow --> Planner[Planner Agent]
        Planner --> DAG[DAG Node Graph]
        DAG --> ExecLoop{Next Node Ready?}
        ExecLoop -- Yes --> RunNode[Run Skill Node]
        ExecLoop -- No / Finished --> FinalOut([Final Output Markdown])
    end
    
    subgraph Skills [Skill Registry]
        RunNode --> SkillRegistry{Skill Name?}
        SkillRegistry -- browser --> BrowserSkill[Browser Skill]
        SkillRegistry -- researcher --> ResearcherSkill[Researcher Skill]
        SkillRegistry -- distiller --> DistillerSkill[Distiller Skill]
        SkillRegistry -- formatter --> FormatterSkill[Formatter Skill]
        SkillRegistry -- summariser --> SummariserSkill[Summariser Skill]
    end

    subgraph BrowserCascade [Browser Skill Cascade - browser/skill.py]
        BrowserSkill --> Layer1[Layer 1: Extract HTTP GET]
        Layer1 -- Success --> BrowserSuccess[Browser Success]
        Layer1 -- Fail / Insufficient --> Layer2[Layer 2: Accessibility Tree Playwright]
        Layer2 -- Success --> BrowserSuccess
        Layer2 -- CAPTCHA / Blocked --> Blocked[Gateway Blocked error_code]
        Layer2 -- No Interactive Elements / Failed --> Layer3[Layer 3: Vision Playwright Screenshots]
        Layer3 -- Success --> BrowserSuccess
        Layer3 -- Fail --> BrowserFail[Node Failure]
    end

    subgraph GatewaySub [LLM Gateway & Cost Ledger]
        Planner -.-> Gateway[LLM Gateway V9 :8109]
        BrowserSkill -.-> Gateway
        Gateway --> Ledger[(SQLite Cost/Token DB)]
    end

    subgraph RecoverySub [Recovery & Route-Around]
        Blocked --> RecoverFlow[recovery.py: plan_recovery]
        BrowserFail --> RecoverFlow
        RecoverFlow --> PlannerReinvoke[Re-invoke Planner]
        PlannerReinvoke --> NewDAG[Route-around DAG]
        NewDAG --> ExecLoop
    end

    class Flow,Planner,DAG,ExecLoop,RunNode orchestrator;
    class BrowserSkill,ResearcherSkill,DistillerSkill,FormatterSkill,SummariserSkill skill;
    class Gateway,Ledger,Blocked gateway;
    class RecoverFlow,PlannerReinvoke,NewDAG recovery;
    class FinalOut,Output output;
```

---

## 🛠️ Core Components

1. **Orchestrator Engine ([flow.py](file:///c:/manish/SchoolOfAI/session9/S9SharedCode/code/flow.py))**
   - Parses the query and runs a NetworkX Directed Acyclic Graph (DAG) loop.
   - Manages execution paths, resolves outputs, and manages node states (`pending`, `running`, `complete`, `skipped`).
   - Splicing of dynamic successors, critic checks, and recovery paths at runtime.

2. **Skill Registry ([skills.py](file:///c:/manish/SchoolOfAI/session9/S9SharedCode/code/skills.py))**
   - Routes executions to specialized sub-agents:
     - **Browser**: Interacts with websites through Playwright or fast parser.
     - **Researcher**: Standard web search (using DuckDuckGo or Tavily search).
     - **Distiller**: Extracts specific schema fields or lists from raw text.
     - **Formatter**: Prepares final user-facing responses.
     - **Summariser**: Summarizes long text inputs.

3. **Browser Skill Cascade ([browser/skill.py](file:///c:/manish/SchoolOfAI/session9/S9SharedCode/code/browser/skill.py))**
   - **Layer 1 (Extract)**: Local parsing of static content using `trafilatura` to avoid LLM cost and browser spin-up.
   - **Layer 2 (Accessibility - a11y)**: Launches a Playwright browser instance, parses the Accessibility tree, and runs step-by-step element actions (click, fill, scroll, drag) with LLM instruction feedback.
   - **Layer 3 (Vision)**: Escalates to visual mode when elements cannot be discovered in the DOM (e.g. canvas elements). Captures page screenshots, overlays coordinate highlights, and interacts using vision LLM models.
   - **CAPTCHA Detection**: Inspects DOM/A11y signatures for gateway challenges (e.g. Cloudflare, Redfin blockages) and throws `gateway_blocked` to trigger orchestrator route-around.

4. **Error Recovery ([recovery.py](file:///c:/manish/SchoolOfAI/session9/S9SharedCode/code/recovery.py))**
   - Intercepts failed nodes (e.g. Captchas or runtime failures).
   - Dynamically re-invokes the Planner to calculate alternate path options (e.g. route-around from Browser to Researcher) instead of looping indefinitely.

5. **LLM Gateway V9 ([llm_gatewayV9/main.py](file:///c:/manish/SchoolOfAI/session9/llm_gatewayV9/main.py))**
   - Central LLM call routing service running locally on port `8109`.
   - Directs prompts to different LLM Backends (Gemini, GitHub Models, Groq) with failover.
   - Records detailed token usage metrics and dollar cost tracking by agent signature (`browser`, `planner`, `distiller`, etc.).

---

## 🚀 Getting Started

### 📋 Prerequisites

Ensure Python `3.11+` and `uv` package manager are installed.

```bash
# Verify uv installation
uv --version
```

### ⚙️ Setup Environment

1. Clone or navigate to the project root.
2. Initialize environment files:
   ```bash
   cp S9SharedCode/code/.env.example S9SharedCode/code/.env
   ```
3. Set your API credentials in `S9SharedCode/code/.env` (e.g., Gemini / GitHub / Groq keys).

4. Install dependencies:
   ```bash
   cd S9SharedCode/code
   uv sync
   uv run playwright install chromium
   ```

### 🖥️ Running the LLM Gateway

The gateway must be active on port `8109` before executing queries.

```bash
cd llm_gatewayV9
uv run main.py
```

### 🏃 Running Queries

You can execute queries via the orchestration entry point [flow.py](file:///c:/manish/SchoolOfAI/session9/S9SharedCode/code/flow.py):

```bash
cd S9SharedCode/code
uv run python flow.py "Compare top 3 Hugging Face text-generation models sorted by likes."
```

---

## 🧪 Demonstration Scenarios

The test framework includes a series of pre-configured demo cases in `S9SharedCode/run_demo.sh` to exercise different capabilities:

| Command | Target Scenario / Flow | Demonstrated Capability |
| :--- | :--- | :--- |
| `bash run_demo.sh tests` | Pytest suite execution | Validates agent graph state recovery, critic injection, and recovery logic. |
| `bash run_demo.sh hello` | `planner -> formatter` | Minimal DAG. Directly formats a response without researching. |
| `bash run_demo.sh shannon` | `planner -> researcher -> formatter` | Single-step information retrieval and formatting. |
| `bash run_demo.sh populations` | `planner -> researcher x 3 (parallel) -> formatter` | Parallel worker routing and strict local scoping (preventing prompt leak). |
| `bash run_demo.sh structured` | `planner -> researcher -> distiller -> critic -> formatter` | Structured field parsing and automatic runtime injection of a Critic agent. |
| `bash run_demo.sh fail` | `planner -> formatter` (graceful exit) | Graceful fail-by-planning when inputs are impossible (e.g. nonexistent paths). |
| `bash run_demo.sh browser` | `planner -> browser -> distiller -> formatter` | Browser skill cascade exercising Extract, A11y, or Vision paths. |
| `bash run_demo.sh wipe` | System reset | Wipes session logs, output artifacts, and FAISS vector index database. |

---

## 🧹 Local State Reset

To clear old execution memory, output artifacts, and vector indices:

```bash
cd S9SharedCode
bash run_demo.sh wipe
```
