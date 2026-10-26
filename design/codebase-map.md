# Codebase map

Written for: the project owner, to learn the codebase by reading diagrams.

## How to read these charts

- **Read top to bottom.** Each coloured band is one stage, in order.
- **Inside a band, read left to right** for the steps that happen together.
- **Every arrow has a label** that says what passes along it.
- **Every decision is a question** (a box with a `{ }` shape). Each branch is labeled in words.
- **Icons add meaning:** 💬 you, 🧠🔧 model, 📜 rules, 📥 waiting, 📝 your file, ⛔ refused, ✅ passed.

## Legend (colours)

| Colour | Means | Examples |
|---|---|---|
| Blue | You | Typing, clicking Approve |
| Grey | The app's core code | Startup, the rules reader, the activity log |
| Green | Packs and their agents | The tasks and lessons packs |
| Purple | The model | hermes3, which only suggests |
| Orange | A decision or approval gate | A check, or your Approve button |
| Yellow | Files on disk | `docs/`, the manifests |
| Red | Refused or cancelled | A request that was stopped |

## 1. Startup

**What it shows:** the app reads each pack's rules and registers the agents that pass.

```mermaid
flowchart TB
    subgraph S1["1 · START"]
        direction LR
        A1["🚀 App starts<br/>(app.py)"]:::core
        A2[("📁 packs/ folder<br/>one folder per pack")]:::store
        A1 -->|"asks for each pack"| A2
    end
    subgraph S2["2 · LOAD (each pack, one at a time)"]
        direction LR
        B1["📜 Read manifest.toml"]:::core
        B2{"Do the rules pass<br/>every check?"}:::gate
        B3["✅ Agent registered"]:::pack
        B4["⚠️ Warning shown,<br/>pack skipped"]:::refuse
        B1 -->|"checks the rules"| B2
        B2 -->|"yes, all rules valid"| B3
        B2 -->|"no, a rule is wrong"| B4
    end
    S1 -->|"folder list read"| S2
classDef human fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
classDef core fill:#e5e7eb,stroke:#374151,color:#111827
classDef pack fill:#dcfce7,stroke:#166534,color:#14532d
classDef model fill:#ede9fe,stroke:#5b21b6,color:#4c1d95
classDef gate fill:#ffedd5,stroke:#c2410c,color:#7c2d12
classDef store fill:#fef9c3,stroke:#854d0e,color:#713f12
classDef refuse fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
```

**Key:** a *manifest* is a pack's rules file. A *registry* is the list of agents the coordinator can use.

## 2. One request: "Add a task: buy milk"

**What it shows:** the path of one request through four bands. Two gates stop it: the route approval and the write approval.

```mermaid
flowchart TB
    subgraph S1["1 · ASK (nothing changes yet)"]
        direction LR
        A1["💬 You type:<br/>Add a task: buy milk"]:::human
        A2["🧠 Model suggests<br/>TaskAgent"]:::model
        A1 -->|"sent to the model"| A2
    end
    subgraph S2["2 · APPROVE THE ROUTE (gate 1)"]
        direction LR
        B1{"Do you approve<br/>the route?"}:::gate
        B2["▶️ Route runs"]:::pack
        B3["✋ Cancelled,<br/>nothing runs"]:::refuse
        B1 -->|"yes, Approve clicked"| B2
        B1 -->|"no, Cancel clicked"| B3
    end
    subgraph S3["3 · STAGE (proposed, not saved)"]
        direction LR
        C1["🔧 Model calls<br/>add_task"]:::model
        C2{"Does the manifest<br/>allow this write?"}:::gate
        C3["📥 Staged in<br/>Approvals list"]:::pack
        C4["⛔ Refused, error<br/>goes back to model"]:::refuse
        C1 -->|"checks the request"| C2
        C2 -->|"yes, append to tasks.md"| C3
        C2 -->|"no, not allowed"| C4
    end
    subgraph S4["4 · WRITE (gate 2)"]
        direction LR
        D1{"Do you click Approve<br/>on the staged item?"}:::gate
        D2[("📝 docs/tasks.md<br/>line added")]:::store
        D3["🗑️ Nothing written"]:::refuse
        D1 -->|"yes, Approve clicked"| D2
        D1 -->|"no, Reject clicked"| D3
    end
    S1 -->|"model suggested a route"| S2
    S2 -->|"route approved, model runs"| S3
    S3 -->|"item waits for you"| S4
classDef human fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
classDef core fill:#e5e7eb,stroke:#374151,color:#111827
classDef pack fill:#dcfce7,stroke:#166534,color:#14532d
classDef model fill:#ede9fe,stroke:#5b21b6,color:#4c1d95
classDef gate fill:#ffedd5,stroke:#c2410c,color:#7c2d12
classDef store fill:#fef9c3,stroke:#854d0e,color:#713f12
classDef refuse fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
```

**Key:** a *route* is which agent handles the request. A *tool* is a function the model can call. *Staged* means waiting, not saved.

## 3. Lessons: save

```mermaid
flowchart TB
    subgraph S1["1 · ASK"]
        direction LR
        A1["💬 You: save a lesson"]:::human
        A2["🔧 Model calls<br/>save_lesson"]:::model
        A1 -->|"model reads the request"| A2
    end
    subgraph S2["2 · CHECK"]
        direction LR
        B1{"Are all four fields<br/>valid and in limits?"}:::gate
        B2["⛔ Refused, error<br/>goes back to model"]:::refuse
        B3["📥 Staged in<br/>Approvals"]:::pack
        B1 -->|"no, a field is invalid"| B2
        B1 -->|"yes, all fields valid"| B3
    end
    subgraph S3["3 · APPROVE"]
        direction LR
        C1{"Do you click<br/>Approve?"}:::gate
        C2[("📝 docs/lesson-*.md<br/>written")]:::store
        C3["🗑️ Nothing written<br/>(rejection is logged)"]:::refuse
        C1 -->|"yes, Approve clicked"| C2
        C1 -->|"no, Reject or left waiting"| C3
    end
    S1 -->|"model sends the fields"| S2
    S2 -->|"staged, waiting for you"| S3
classDef human fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
classDef core fill:#e5e7eb,stroke:#374151,color:#111827
classDef pack fill:#dcfce7,stroke:#166534,color:#14532d
classDef model fill:#ede9fe,stroke:#5b21b6,color:#4c1d95
classDef gate fill:#ffedd5,stroke:#c2410c,color:#7c2d12
classDef store fill:#fef9c3,stroke:#854d0e,color:#713f12
classDef refuse fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
```

## 4. Lessons: find

Finding only reads, so there's no approval step.

```mermaid
flowchart TB
    subgraph S1["1 · ASK"]
        direction LR
        A1["💬 You: find lessons<br/>about docker"]:::human
        A2["🔧 Model calls<br/>find_lessons"]:::model
        A1 -->|"model reads the request"| A2
    end
    subgraph S2["2 · READ ONLY (nothing changes)"]
        direction LR
        B1[("📚 docs/lesson-*.md<br/>only these files")]:::store
        B2["🔍 Score each lesson:<br/>tags, title, then text"]:::pack
        B3["🏅 Keep the best 3"]:::pack
        B1 -->|"text of each file"| B2
        B2 -->|"highest scores first"| B3
    end
    subgraph S3["3 · ANSWER"]
        direction LR
        C1["📤 Matches go back<br/>to the model"]:::model
        C2["💬 Model answers you"]:::human
        C1 -->|"model writes the reply"| C2
    end
    S1 -->|"model sends key words"| S2
    S2 -->|"top 3 matches"| S3
classDef human fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
classDef core fill:#e5e7eb,stroke:#374151,color:#111827
classDef pack fill:#dcfce7,stroke:#166534,color:#14532d
classDef model fill:#ede9fe,stroke:#5b21b6,color:#4c1d95
classDef gate fill:#ffedd5,stroke:#c2410c,color:#7c2d12
classDef store fill:#fef9c3,stroke:#854d0e,color:#713f12
classDef refuse fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
```

## 5. What the app keeps

```mermaid
flowchart TB
    subgraph S1["WHERE THINGS ARE KEPT"]
        direction LR
        A1["📜 Manifest<br/>rules for one pack"]:::pack
        A2["⏳ Pending item<br/>proposed text"]:::gate
        A3[("📝 Your notes<br/>docs/")]:::store
        A4["🧾 Activity log<br/>names and counts only"]:::core
    end
    A1 -->|"limits what the pack may propose"| A2
    A2 -->|"written only after you click Approve"| A3
    A2 -->|"approve or reject is logged"| A4
classDef human fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
classDef core fill:#e5e7eb,stroke:#374151,color:#111827
classDef pack fill:#dcfce7,stroke:#166534,color:#14532d
classDef model fill:#ede9fe,stroke:#5b21b6,color:#4c1d95
classDef gate fill:#ffedd5,stroke:#c2410c,color:#7c2d12
classDef store fill:#fef9c3,stroke:#854d0e,color:#713f12
classDef refuse fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
```

## 6. File access

**What it shows:** how a file request is checked, and where it can be stopped.

```mermaid
flowchart TB
    subgraph S1["1 · ASK"]
        direction LR
        A1["🤖 Model asks for<br/>a file by name"]:::model
    end
    subgraph S2["2 · CHECK THE MANIFEST"]
        direction LR
        B1{"Is the name listed<br/>in the pack's manifest?"}:::gate
        B2["⛔ Refused:<br/>not in the manifest"]:::refuse
        B1 -->|"no, not listed"| B2
    end
    subgraph S3["3 · CHECK THE NAME"]
        direction LR
        C1{"Is the name safe?<br/>no folders, no shortcuts"}:::gate
        C2["⛔ Refused:<br/>unsafe name or shortcut"]:::refuse
        C1 -->|"no, unsafe"| C2
    end
    subgraph S4["4 · ALLOWED"]
        direction LR
        D1["📖 Read: text returned"]:::pack
        D2["📥 Write: staged for approval"]:::pack
    end
    S1 -->|"request arrives"| S2
    S2 -->|"yes, listed"| S3
    S3 -->|"yes, safe"| S4
classDef human fill:#dbeafe,stroke:#1e40af,color:#1e3a8a
classDef core fill:#e5e7eb,stroke:#374151,color:#111827
classDef pack fill:#dcfce7,stroke:#166534,color:#14532d
classDef model fill:#ede9fe,stroke:#5b21b6,color:#4c1d95
classDef gate fill:#ffedd5,stroke:#c2410c,color:#7c2d12
classDef store fill:#fef9c3,stroke:#854d0e,color:#713f12
classDef refuse fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d
```

**Key:** the *gateway* is the one code path packs use to reach files. A *shortcut* (symlink) is refused, because it can point outside `docs/`.

## Where the code is

| Chart | Start reading here |
|---|---|
| 1. Startup | `app.py`, then `packs_registry.py` |
| 2. One request | `brain.py` (routing), `packs/tasks/pack.py` (the tool), `agent.py` (`approve_write`) |
| 3. Lessons save | `packs/lessons/pack.py`, then `lessons.py` (`build_lesson`) |
| 4. Lessons find | `packs/lessons/pack.py`, then `lessons.py` (`search_entries`) |
| 5. What the app keeps | `packs/*/manifest.toml`, `pending_store.py`, `brain.py` (`ActivityLog`) |
| 6. File access | `packs_gateway.py`, then `agent.py` (`_safe_path`) |

Update a chart in the same change as the code it shows.
