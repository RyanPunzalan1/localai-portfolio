# Reviewing and reproducing (Phase 6 gate)

Two roles are needed before release. One person can do both.
- **The external run:** someone who did not build the workbench follows [README.md](README.md) on their own Mac.
- **The outside review:** someone reads the threat model and code with a security eye.

Report what you find to the maintainer, or follow [SECURITY.md](SECURITY.md) for anything security-sensitive.

## Part 1: external run (about 30 to 60 minutes, mostly waiting)

Use only the README. Note every step where you had to guess, ask, or work around something: that is the most useful
output of this part.

1. **Check the machine:**
   - Install what the README's Requirements table lists.
   - Run `.venv/bin/python -m workbench doctor`.
   - Record its output.
2. **Rebuild the reference report** (deterministic):

   ```bash
   .venv/bin/python -m workbench reproduce experiments/workbench_phase6/reference
   ```

   **Pass:** it prints `OK`. The shipped report rebuilds byte for byte, and every number agrees with a recount.
3. **Live run:** run the same scenarios as the reference.

   ```bash
   .venv/bin/python -m workbench run core --pair localai:docker-none --pair hermes:docker-none --pair hermes:sbx-deny-all --trusted-code
   ```

   **Pass:** the batch completes without stopping, and the last line says the numbers agree.
4. **Compare** with the reference:

   ```bash
   .venv/bin/python -m workbench compare experiments/workbench_phase6/reference/results.jsonl ~/.agent-workbench/runs/core-<stamp>/results.jsonl
   ```

   **Pass:**
   - every benign outcome matches, and no case is missing;
   - every listed attack difference has an explanation from its evidence. For example: "the model asked for
     `save_note` this time, so it is *Blocked* instead of *No attempt observed: model held*".
   - A small local model doesn't answer the same way every time, so attack outcomes can differ. An unexplained
     difference fails the gate.
5. **Open the report:**
   - Open `report/report.html` from the live run in a browser, and `report.md` in a Markdown viewer.
   - Check it says what it should: counts with denominators, attempted attacks shown apart, the limitations, and no
     score or ranking.
   - Check that no agent text renders as a link, an image or formatting.

## Part 2: outside review (checklist)

- [ ] [THREAT_MODEL.md](THREAT_MODEL.md): is anything missing that a hostile agent could reach?
- [ ] `workbench/specs.py`: can a profile or scenario produce a sandbox with a host mount, network, socket or
      capability the workbench did not intend?
- [ ] `workbench/isolation.py` and `workbench/tripwire.py`: can a check pass while isolation is broken? Do failures
      to read count as failures?
- [ ] `workbench/verdict.py`: can agent text or a self-report change an outcome?
- [ ] `workbench/scenario.py`: can a scenario file run code, read outside its fixture, or bypass the size limits?
- [ ] `workbench/report.py`: can record text become markup in either format?
- [ ] `experiments/checks/verify_report_numbers.py`: is it independent enough of the report to catch the report's
      mistakes?

## What the maintainer has verified, and what not

The maintainer has done this procedure themself on the development Mac (`design/workbench-phase6-results.md`). That
is not the gate. The gate needs a different person and machine.
