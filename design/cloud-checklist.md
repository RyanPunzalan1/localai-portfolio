# Cloud deployment: checklist, in order

Use this note to know what to do next. Each step says **where** to run it and links to the full
commands in [[cloud-deploy]]. Tick each box when its check passes. Don't skip ahead.

**Where to run:** **Mac** = your Mac's Terminal. **VM** = inside the Lima VM (`limactl shell default`).
**Server** = on the AWS server (`ssh`). **Console** = the AWS website.

## Part A: One-time setup (do once)

- [ ] **A1. Install tools.** Where: Mac. Section: C.0. Check: `terraform -version`, `aws --version`, `limactl --version` all print versions.
- [ ] **A2. Create the AWS account.** Where: Console. Section: C.2 Part 1. Check: you can sign in as `localai-admin` with MFA.
- [ ] **A3. Set the budget and its alerts.** Where: Console. Section: C.2 Part 1. Check: the $10 budget lists alerts at 50%, 80% and 100%.
- [ ] **A4. Create the CLI keys and configure the CLI.** Where: Console, then Mac. Section: [[aws-cli-steps]] Part 1. Check: `aws sts get-caller-identity` shows `localai-admin`.
- [ ] **A5. Create the SSH key.** Where: Mac. Section: C.2 Part 3. Check: `head -1 ~/.ssh/<KEY_NAME>.pem` prints a `-----BEGIN` line.

## Part B: The local VM (every time you work on the app)

- [ ] **B1. Start the VM.** Where: Mac. Section: "Returning to the VM later." Check: `limactl list` shows `Running`.
- [ ] **B2. Open the VM shell.** Where: Mac, then VM. Command: `limactl shell default`. Check: prompt shows `lima-default`.
- [ ] **B3. Check the app.** Where: VM. Command: `docker ps`, then `curl -I http://127.0.0.1:8501/`. Check: `Up` and `200 OK`.

Docker and its group setup are in the **Install Docker** section. Do that once per machine, before B.

## Part C: The AWS server (first time, then as needed)

- [ ] **C1. Create the firewall rule** (SSH from your IP only). Where: Mac. Section: C.2 Part 4.
- [ ] **C2. Launch the server.** Where: Mac. Section: C.2 Part 5. Check: the instance ID is printed.
- [ ] **C3. Install Docker on the server.** Where: Server. Section: **Install Docker**. Check: `docker run hello-world` works.
- [ ] **C4. Copy the project to the server.** Where: Mac, then Server. Section: C.2 Part 6. Check: `ls ~/LocalAI` shows the project files.
- [ ] **C5. Start the app on the server.** Where: Server. Section: C.2 Part 7. Check: container `Up`, `200 OK`.
- [ ] **C6. Open the tunnel and use the app.** Where: Mac. Section: C.2 Part 8, and the session routine. Check: `curl -I http://localhost:8502` gives `200 OK`.
- [ ] **C7. Check the public port is closed.** Where: Mac. Command: `curl -m 5 http://<server IP>:8501`. Check: no page (it fails or times out).

## Part D: Every session (start to finish)

Follow the **Session routine** and the **Starting again after a restart** sections. In short:

1. Mac: start the server, then get its new IP.
2. Mac: open the tunnel on port 8502, and leave the window open.
3. Browser: use http://localhost:8502.
4. Mac: Ctrl+C in the tunnel window, then stop the server.
5. Mac: stop the VM (`limactl stop default`).
6. Mac: check the billing checks, and the next day, check the Billing page.

## Part E: Infrastructure as code (next steps)

- [ ] **E1. Terraform (C.3).** Where: Mac. Section: C.3. **Replaces** the server and firewall from C1 and C2: C.3 Part 1 removes them first, then Terraform builds them again from code. Check: `terraform plan` shows only the expected resources, and `destroy` then `apply` rebuilds the setup.
- [ ] **E2. Logs and one alarm (C.4).** Where: Server, then Console. Section: C.4. Check: the alarm fires on a test blocked action.
- [ ] **E3. Least-privilege role for GitHub (C.5).** Where: Console, then repo. Section: C.5. Check: a workflow runs with the role, and the old key is refused.

## Part F: Finish

- [ ] **F1. Update the threat model** for the cloud. Where: Mac. File: `design/threat-model.md`.
- [ ] **F2. Terminate what you don't need.** Where: Mac. Check: the teardown checklist in the guide is complete.
- [ ] **F3. Write the one-page summary** of the deployment: the design, the decisions, and what you'd change at scale.

## Rules that apply to every step

- **Describe before you change** ([[aws-cli-steps]]).
- **Replace placeholders** like `<SERVER_IP>` with real values, without the angle brackets.
- **Never paste keys, passwords or the private key file** anywhere.
- **Stop the server at the end of every session.**
