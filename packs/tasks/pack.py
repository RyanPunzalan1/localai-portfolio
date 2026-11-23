"""
The tasks pack: list, add, and complete tasks in docs/tasks.md. Design: design/packs.md.

Tools only propose changes through the gateway; nothing is written until the user approves.
The tool descriptions (docstrings) and the messages returned to the model are kept identical to
the original TaskAgent, because the small model chooses tools from them (roadmap 5.3).
"""

TASKS_FILE = "tasks.md"
MAX_TASK_CHARS = 200


def build_tools(gateway):
    def _tools():
        def list_tasks() -> str:
            """List the current tasks."""
            try:
                return gateway.read_text(TASKS_FILE)
            except FileNotFoundError:
                return "(no tasks yet)"

        def add_task(text: str) -> str:
            """Propose adding a task. The user must approve it before it is saved.

            Args:
                text: The task, in one short line.
            """
            clean = " ".join(str(text).split())[:MAX_TASK_CHARS]
            if not clean:
                return "Error: the task text is empty."
            gateway.propose_append(TASKS_FILE, f"- [ ] {clean}\n")
            return "Proposed a new task. It is NOT saved yet; waiting for the user to approve."

        def complete_task(text: str) -> str:
            """Propose marking an open task as done. The user must approve it first.

            Args:
                text: The task text, as it appears in the list.
            """
            clean = " ".join(str(text).split())[:MAX_TASK_CHARS]
            if not clean:
                return "Error: the task text is empty."
            open_line = f"- [ ] {clean}"
            if not gateway.has_line(TASKS_FILE, open_line):
                return "Error: no open task with that text. Call list_tasks to check."
            gateway.propose_mark_done(TASKS_FILE, open_line)
            return "Proposed marking the task done. It is NOT changed yet; waiting for the user to approve."

        return {"list_tasks": list_tasks, "add_task": add_task, "complete_task": complete_task}

    return _tools()
