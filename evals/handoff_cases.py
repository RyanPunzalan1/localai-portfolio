"""Cases for the TaskAgent -> DocAgent "Save as a note" handoff.

Each case is the raw text the first agent's read tool returned. After the second agent runs, the
proposed note must (1) exist, (2) have a new .md name that is not one of the source names, and
(3) contain every source line, with nothing else added. Dummy data only.
"""

CASES = [
    {"id": "three-tasks", "label": "tasks", "source_names": {"tasks.md"},
     "lines": ["- [ ] buy milk", "- [ ] call the dentist", "- [ ] email Sam"]},
    {"id": "six-tasks-mixed", "label": "tasks", "source_names": {"tasks.md"},
     "lines": ["- [ ] renew passport before March", "- [x] book flights", "- [ ] water the plants",
               "- [ ] pay rent", "- [x] call mom", "- [ ] fix the faucet"]},
    {"id": "punctuation", "label": "tasks", "source_names": {"tasks.md"},
     "lines": ['- [ ] email "Sam": lease (urgent!)', "- [ ] buy milk & eggs, 2% only", "- [ ] 10:30 call - Dr. Lee"]},
    {"id": "note-text", "label": "ideas.md", "source_names": {"ideas.md"},
     "lines": ["Ideas: a local chess club app.", "Needs: a booking page and a member list."]},
    {"id": "one-task", "label": "tasks", "source_names": {"tasks.md"},
     "lines": ["- [ ] buy milk"]},
]
