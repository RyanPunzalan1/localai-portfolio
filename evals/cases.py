"""Eval cases for routing and tool choice. Each case is one user request.

route:  the agent the coordinator should pick.
tool:   the tool that agent should call. None means it should answer without a tool
        (only checked for the route, not the tool).
heldout: True for cases written before the lessons prompt and purpose were tuned. Never tune
        against these; they show whether a change helps requests it was not fitted to.
contains: optional, for save_lesson. Words (lowercase) that must appear in the proposed lesson,
        so the model keeps the user's own details and does not invent its own.
Keep prompts plain and realistic. Add cases; do not edit a case to make it pass.
"""

CASES = [
    # Tasks: add
    {"prompt": "Add a task: buy milk on the way home", "route": "TaskAgent", "tool": "add_task"},
    {"prompt": "New task: renew passport before March", "route": "TaskAgent", "tool": "add_task"},
    {"prompt": "Put 'email Sam about the lease' on my list", "route": "TaskAgent", "tool": "add_task"},
    # Tasks: list
    {"prompt": "What tasks do I have?", "route": "TaskAgent", "tool": "list_tasks"},
    {"prompt": "Show me my task list", "route": "TaskAgent", "tool": "list_tasks"},
    # Tasks: complete
    {"prompt": "Mark 'buy milk' as done", "route": "TaskAgent", "tool": "complete_task"},
    {"prompt": "Check off 'email Sam' on my list", "route": "TaskAgent", "tool": "complete_task"},
    # Notes: list, read, save
    {"prompt": "What files do I have?", "route": "DocAgent", "tool": "list_files"},
    {"prompt": "Show me what is in ideas.md", "route": "DocAgent", "tool": "read_file"},
    {"prompt": "Save a note called plan.md that says: ship phase 5", "route": "DocAgent",
     "tool": "save_note"},
    {"prompt": "Open ideas.md and tell me what it says", "route": "DocAgent", "tool": "read_file"},
    {"prompt": "What does ideas.md contain?", "route": "DocAgent", "tool": "read_file"},
    {"prompt": "Write a note named plan2.md with: buy a domain name", "route": "DocAgent",
     "tool": "save_note"},
    {"prompt": "Create a note called meeting.md that says: agenda is budget review",
     "route": "DocAgent", "tool": "save_note"},
    # Lessons: save (the proposed note must keep the user's own words)
    {"prompt": "Remember this: Docker builds need --no-cache after changing requirements.txt, "
               "because old layers were cached.", "route": "LessonsAgent", "tool": "save_lesson",
     "contains": ["no-cache"]},
    {"prompt": "Lesson learned: always pin package versions in requirements.txt. "
               "An unpinned update broke my app.", "route": "LessonsAgent", "tool": "save_lesson",
     "contains": ["pin"]},
    {"prompt": "Save a lesson: Streamlit reruns the whole script on every click, so wrap slow "
               "setup in st.cache_resource.", "route": "LessonsAgent", "tool": "save_lesson",
     "contains": ["cache_resource"]},
    {"prompt": "Note for future projects: turn off ChromaDB telemetry with "
               "anonymized_telemetry=False.", "route": "LessonsAgent", "tool": "save_lesson",
     "contains": ["anonymized_telemetry"]},
    {"prompt": "I want to remember that git rebase on a shared branch caused conflicts for the team.",
     "route": "LessonsAgent", "tool": "save_lesson", "contains": ["rebase"]},
    # Lessons: find and list
    {"prompt": "What did I learn about docker?", "route": "LessonsAgent", "tool": "find_lessons"},
    {"prompt": "Any lessons about Streamlit?", "route": "LessonsAgent", "tool": "find_lessons"},
    {"prompt": "Do I have a lesson about pinning versions?", "route": "LessonsAgent",
     "tool": "find_lessons"},
    {"prompt": "Remind me what I know about caching", "route": "LessonsAgent", "tool": "find_lessons"},
    {"prompt": "List all my coding lessons", "route": "LessonsAgent", "tool": "find_lessons"},
    # Lessons, held out (written before tuning; do not tune against these)
    {"prompt": "Lesson: run the tests before every commit so a broken build never reaches CI.",
     "route": "LessonsAgent", "tool": "save_lesson", "contains": ["commit"], "heldout": True},
    {"prompt": "Remember for next time: ollama needs OLLAMA_HOST set when the app runs in Docker.",
     "route": "LessonsAgent", "tool": "save_lesson", "contains": ["ollama_host"], "heldout": True},
    {"prompt": "Make a note of this for future projects: use python3 -m venv .venv so dependencies "
               "stay isolated.", "route": "LessonsAgent", "tool": "save_lesson",
     "contains": ["venv"], "heldout": True},
    {"prompt": "Gotcha: sqlite locks the database file when two processes write at once. "
               "Write that down as a lesson.", "route": "LessonsAgent", "tool": "save_lesson",
     "contains": ["sqlite"], "heldout": True},
    {"prompt": "What have I learned about testing?", "route": "LessonsAgent", "tool": "find_lessons",
     "heldout": True},
    {"prompt": "Show me my lessons on git", "route": "LessonsAgent", "tool": "find_lessons",
     "heldout": True},
]
