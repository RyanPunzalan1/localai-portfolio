"""Fixture: a well-behaved pack."""


def build_tools(gateway):
    def read_note() -> str:
        """Read the notes."""
        try:
            return gateway.read_text("notes.md")
        except FileNotFoundError:
            return "(no notes)"

    def add_note(text: str) -> str:
        """Propose adding a note."""
        gateway.propose_append("notes.md", f"- {text}\n")
        return "Proposed."

    return {"read_note": read_note}
