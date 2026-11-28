"""Fixture: forwards whatever name the model gives. Safe only because the gateway checks the reduced name too."""


def build_tools(gateway):
    def read_note(name: str) -> str:
        """Read a note by name."""
        return gateway.read_text(name)

    def add_note(name: str, text: str) -> str:
        """Propose a new note."""
        return gateway.propose_create(name, text)

    return {"read_note": read_note, "add_note": add_note}
