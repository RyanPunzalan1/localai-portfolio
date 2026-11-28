"""Fixture: writes a file directly instead of proposing a change."""
import agent


def build_tools(gateway):
    def read_note() -> str:
        """Read the notes."""
        return "ok"

    def add_note(text: str) -> str:
        """Add a note."""
        with open(agent.DOCS / "notes.md", "a", encoding="utf-8") as f:
            f.write(text)
        return "Saved."

    return {"read_note": read_note, "add_note": add_note}
