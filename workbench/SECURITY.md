# Security policy

## Reporting a vulnerability in the workbench

Please report privately, not in a public issue:
- use GitHub's "Report a vulnerability" (private security advisory) on this repository;
- include the workbench version (`workbench/record.py`, `WORKBENCH_VERSION`), the sbx and Docker versions, and the
  steps to reproduce.

These count as vulnerabilities:
- a way for a tested agent to reach the host, the network or Ollama;
- a way for an agent to change evidence or a report's outcome;
- a scenario file that runs code or reads outside its fixture;
- report output that renders agent text as markup.

There is no bug bounty. This is a pre-release personal project, so responses are best effort.

## Findings about agents or sandbox runtimes

The workbench may show a third-party agent or runtime misbehaving:
- **Agent or runtime findings:** report them to that project through its own security process first, and don't publish
  a scenario that exploits an unfixed issue (threat T13).
- **Suspected sandbox escape:** the workbench stops the batch and keeps the evidence. In the VM tier, report it to the
  sandbox runtime's project. In the Docker tier, treat the host or Docker Desktop's VM as possibly compromised.

## Safe use

- **Use the VM tier (`sbx-deny-all`) for third-party agents.** The Docker tier is for code you trust.
- **Run on a machine with nothing you can't afford to expose.** Isolation lowers the risk; it doesn't remove it.
- **Keep private scenario packs** (including the held-out set) outside any git repository.
- **Treat a report as evidence for one setup on one day,** not as a certification.
