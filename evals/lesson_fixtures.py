"""Dummy lessons and search queries for the recall eval (evals/run_recall_evals.py).

FIXTURES: id -> (title, tags, lesson, why). Built with lessons.build_lesson in a temp folder.
QUERIES:  each has the fixture ids that should appear in the top 3 results, in any order.

group "direct":  the query shares words with the lesson's tags, title, or text.
group "synonym": the meaning matches but no word is shared. These are expected to miss today
                 (keyword matching). They are printed, not gated.

Written before the first run. Add queries; do not edit one to make it pass.
Never uses the real docs/.
"""

FIXTURES = {
    "docker-cache": ("Docker needs no-cache after requirements change", "docker, build",
                     "Rebuild with --no-cache after editing requirements.txt.",
                     "Cached layers kept the old packages."),
    "streamlit-rerun": ("Streamlit reruns the whole script", "streamlit, caching",
                        "Wrap slow setup in st.cache_resource.",
                        "Every click reruns the script."),
    "pin-versions": ("Pin package versions", "pip, requirements",
                     "Pin every version in requirements.txt.",
                     "An unpinned update broke the app."),
    "git-rebase": ("Avoid rebase on shared branches", "git, rebase",
                   "Merge instead of rebasing a branch others use.",
                   "Rebasing rewrote history and caused conflicts."),
    "sqlite-locks": ("SQLite locks on concurrent writes", "sqlite, database",
                     "Use one writer or enable WAL mode.",
                     "Two processes wrote at once and the file locked."),
    "venv": ("Use a virtual environment", "python, venv",
             "Create a .venv for each project.",
             "Global packages clashed between projects."),
    "ollama-host": ("Ollama host inside Docker", "ollama, docker, network",
                    "Set OLLAMA_HOST to host.docker.internal.",
                    "The container could not reach Ollama on localhost."),
    "test-before-commit": ("Run tests before every commit", "testing, git",
                           "Run the whole suite before committing.",
                           "A broken build reached CI."),
    "chroma-telemetry": ("Turn off ChromaDB telemetry", "chromadb, privacy",
                         "Set anonymized_telemetry=False on every client.",
                         "It sends usage data by default."),
    "sys-path": ("Add the project root to sys.path in tests", "testing, imports",
                 "Insert the project root at the top of each test file.",
                 "Tests moved to a folder could not import modules."),
    "windows-names": ("Windows reserves some file names", "windows, filenames",
                      "Reject names like CON and NUL.",
                      "They refer to devices, not files."),
    "short-prompts": ("Keep prompts short for small models", "prompts, hermes",
                      "Use short tool descriptions and prompts.",
                      "A small model loses track of long instructions."),
    "ruff-ci": ("Lint in CI with ruff", "lint, ci",
                "Run ruff check in a CI job.",
                "Real bugs were found by simple rules."),
    "log-counts": ("Log counts, not text", "logging, privacy",
                   "Record lengths and event names, never user text.",
                   "Plain text logs leak private data."),
    "heldout-evals": ("Write held-out eval cases before tuning", "evals, testing",
                      "Add cases you will not tune against.",
                      "A one-case gain can be noise."),
}

QUERIES = [
    # direct
    {"query": "docker build cache", "expect": ["docker-cache"], "group": "direct"},
    {"query": "streamlit cache_resource", "expect": ["streamlit-rerun"], "group": "direct"},
    {"query": "pin versions requirements", "expect": ["pin-versions"], "group": "direct"},
    {"query": "git rebase", "expect": ["git-rebase"], "group": "direct"},
    {"query": "sqlite concurrent writes", "expect": ["sqlite-locks"], "group": "direct"},
    {"query": "virtual environment venv", "expect": ["venv"], "group": "direct"},
    {"query": "ollama host docker", "expect": ["ollama-host"], "group": "direct"},
    {"query": "run tests before commit", "expect": ["test-before-commit"], "group": "direct"},
    {"query": "chromadb telemetry", "expect": ["chroma-telemetry"], "group": "direct"},
    {"query": "sys.path imports tests", "expect": ["sys-path"], "group": "direct"},
    {"query": "windows reserved names", "expect": ["windows-names"], "group": "direct"},
    {"query": "ruff ci", "expect": ["ruff-ci"], "group": "direct"},
    # synonym: same meaning, no shared words
    {"query": "dependency freezing", "expect": ["pin-versions"], "group": "synonym"},
    {"query": "squash commits", "expect": ["git-rebase"], "group": "synonym"},
    {"query": "multi-process access", "expect": ["sqlite-locks"], "group": "synonym"},
    {"query": "sandboxed interpreter", "expect": ["venv"], "group": "synonym"},
    {"query": "scrubbing personal info from output", "expect": ["log-counts"], "group": "synonym"},
]
