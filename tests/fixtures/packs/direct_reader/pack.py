"""Fixture: reads files with open(), so it ignores the read list and follows links."""
import agent


def build_tools(gateway):
    def read_note(name: str) -> str:
        """Read a note by name."""
        with open(agent.DOCS / name, encoding="utf-8") as f:
            return f.read()

    def add_note(text: str) -> str:
        """Propose adding a note."""
        gateway.propose_append("notes.md", f"- {text}\n")
        return "Proposed."

    return {"read_note": read_note, "add_note": add_note}
