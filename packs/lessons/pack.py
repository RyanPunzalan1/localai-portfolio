"""
The lessons pack: save a lesson for approval, and find saved lessons. Design: design/packs.md.

save_lesson only proposes a note; the user approves it in the approvals inbox. find_lessons reads
lesson files through the gateway and ranks them with lessons.search_entries (the same ranking the
recall eval measures). Descriptions and returned messages are kept identical to the original
LessonsAgent, because the small model chooses tools from them (roadmap 5.3).
"""

from lessons import MAX_READ, build_lesson, search_entries


def build_tools(gateway):
    def _tools():
        def save_lesson(title: str, tags: str, lesson: str, why: str) -> str:
            """Propose saving a coding lesson. The user must approve it before it is saved.

            Args:
                title: A short title.
                tags: A few plain words, separated by commas.
                lesson: What to do or avoid, in one or two sentences.
                why: What happened, or the reason.
            """
            try:
                name, text = build_lesson(title, tags, lesson, why)
                gateway.propose_create(name, text)
            except ValueError as e:
                return f"Error: {e}"
            return "Proposed a new lesson. It is NOT saved yet; waiting for the user to approve."

        def find_lessons(query: str) -> str:
            """Find saved lessons that match some key words. An empty query lists all titles.

            Args:
                query: A few key words.
            """
            entries = [(name, gateway.read_raw(name)[:MAX_READ]) for name in gateway.list_names()]
            return search_entries(entries, query)

        return {"save_lesson": save_lesson, "find_lessons": find_lessons}

    return _tools()
