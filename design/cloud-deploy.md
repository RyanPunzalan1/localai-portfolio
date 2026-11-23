# Design: deploying LocalAI to AWS (step-by-step guide)

Written for: the project owner, to follow line by line.
Status: **Proposed.** Nothing here is built. Each step that creates or changes cloud resources needs
the owner's approval first. These steps are C.0 to C.5 in `design/architecture.md`.

**Start with the checklist:** [[cloud-checklist]] lists every step in order, with where to run each one. Use this guide for the full commands.

**Running AWS commands:** see [[aws-cli-steps]] for setup, the check-before-change routine, error meanings, and the cost checks. Every AWS command here follows it.

**How to use this guide**
- Type each command yourself. Copy the output into your learning notes.
- Run each **Check** before moving on. If a check fails, stop and read the **If it fails** line.
- Lines starting with `#` are comments. Don't type them.
- Replace anything in `<angle brackets>` with your own value.

**Reading this in Obsidian:** open the `design` vault, open this note, and press **Cmd+E** to switch
between editing and reading. In reading view the code blocks are easy to copy. Updated copies appear
as soon as the file is saved, so reopen the note if the old text still shows.

## Session routine: from opening Terminal to closing it

Follow this order every time you work on the cloud part. Each step says what you should see.

**Part A: start**

1. **Open Terminal** (Spotlight: press Cmd+Space, type `Terminal`, press Enter).
2. **Go to the project folder:**
   ```
   cd ~/LocalAI
   ```
3. **Check your AWS account and region:**
   ```
   aws sts get-caller-identity
   aws configure get region
   ```
   **Expect:** your account ID and `localai-admin`, and the region you chose (for example `us-west-2`).
   **If not:** stop. Don't continue until you know why.
4. **Start the local VM** (if it isn't running):
   ```
   limactl list
   limactl start default
   ```
   **Expect:** the `default` row shows `Running`.
5. **Open a shell inside the VM:**
   ```
   limactl shell default
   ```
   **Expect:** your prompt changes to the VM.
6. **Check Docker and the app inside the VM:**
   ```
   docker ps
   curl -I http://127.0.0.1:8501/
   ```
   **Expect:** the `localai` container is `Up`, and the first line of the `curl` output is `HTTP/1.1 200 OK`.
   **If the container isn't there:** `cd ~/LocalAI && docker compose up -d`, then check again.
7. **Leave the VM's shell** for now:
   ```
   exit
   ```
   **Expect:** your prompt returns to your Mac.
8. **Start the AWS server:**
   ```
   aws ec2 start-instances --instance-ids <INSTANCE_ID>
   aws ec2 wait instance-running --instance-ids <INSTANCE_ID>
   ```
   **Expect:** the second command returns with no error once the server is running.
9. **Get the server's current IP** (it changes each time the server starts):
   ```
   aws ec2 describe-instances --instance-ids <INSTANCE_ID> --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
   ```
   Write it down as `<SERVER_IP>`.
10. **Open the tunnel**, in a **new Terminal window** (leave it open):
    ```
    ssh -i ~/.ssh/<KEY_NAME>.pem -N -L 8501:127.0.0.1:8501 ubuntu@<SERVER_IP>
    ```
    **Expect:** the window doesn't return to a prompt. That's the tunnel working.
11. **Open the app** in your browser: http://localhost:8501

**Part B: use it**

12. Use the app. Keep the tunnel window open the whole time.

**Part C: stop, in this order**

13. **Close the tunnel:** click the tunnel's Terminal window and press **Ctrl+C**.
14. **Stop the AWS server:**
    ```
    aws ec2 stop-instances --instance-ids <INSTANCE_ID>
    aws ec2 wait instance-stopped --instance-ids <INSTANCE_ID>
    ```
    **Expect:** the second command returns with no error once the server is stopped.
15. **Confirm it's stopped:**
    ```
    aws ec2 describe-instances --instance-ids <INSTANCE_ID> --query 'Reservations[0].Instances[0].State.Name' --output text
    ```
    **Expect:** `stopped`. If it says anything else, run step 14 again.
16. **Stop the local VM:**
    ```
    limactl stop default
    ```
    **Expect:** the command finishes, and `limactl list` shows `Stopped`.
17. **Check the cost checks** (once a week, or after a long session):
    ```
    aws ec2 describe-instances --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output table
    aws ec2 describe-addresses --query 'Addresses[].[PublicIp,AssociationId]' --output table
    ```
    **Expect:** the server is `stopped`, and no address is listed without an association.
18. **Close Terminal:** type `exit` in each window, or press Cmd+Q.

**If you forget step 14:** the server keeps charging. The budget action at 100% is the backstop, but don't rely
on it. Check step 15 the next time you open Terminal.

### Starting again after you restart your Mac or shut down

After a restart, nothing is running: the tunnel is closed, the Lima VM is stopped (unless you left it running), and
the AWS server is stopped (if you ran step 14 of the session routine). Start in this order.

1. **Open Terminal** and go to the project folder: `cd ~/LocalAI`
2. **Check AWS works:** `aws sts get-caller-identity`. You should see your account and `localai-admin`.
3. **Start the VM:** `limactl start default`, then `limactl list` should show `Running`.
4. **Check the app inside the VM:** `limactl shell default`, then `docker ps`. The `localai` container should
   be `Up` by itself. If not, run `cd ~/LocalAI && docker compose up -d`.
5. **Leave the VM:** `exit`.
6. **Start the AWS server (only when you need it):**
   `aws ec2 start-instances --instance-ids <INSTANCE_ID>`, then
   `aws ec2 wait instance-running --instance-ids <INSTANCE_ID>`.
7. **Get the new IP:** the IP changes each time the server starts (session routine, step 9).
8. **Open the tunnel and the app:** session routine, steps 10 and 11.

**You don't need to start the AWS server to work on the project.** Start it only for the parts that need it,
such as checking the deployment or running a Terraform step. For everything else, the local app is enough.

### How to know nothing is billing

Stopping the server is the main step, but it doesn't stop every charge. Use this table to know what's billing:

| What | Billing while stopped? | What to do |
|---|---|---|
| The AWS server (EC2 instance), stopped | No compute charge | Leave it stopped between sessions |
| The server's disk (EBS volume, 8 GB) | **Yes, a small amount** | Terminate the server if you won't use it for days |
| An Elastic IP address | Yes, when not attached | Don't create one (rule 3) |
| Snapshots | Yes | Delete any you don't need |
| Terraform stack | Yes, while it exists | `terraform destroy` when you're done for a while |
| CloudWatch logs and alarms | Small | Delete them when the step is finished |
| Lima VM on your Mac | **No.** It's free | Stop it with `limactl stop default` |

**Checks to run when you finish** (these are the answers to "is anything billing?"):
```
aws ec2 describe-instances --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output table
aws ec2 describe-volumes --query 'Volumes[].[VolumeId,State,Size]' --output table
aws ec2 describe-addresses --query 'Addresses[].[PublicIp,AssociationId]' --output table
aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[].[SnapshotId,VolumeSize]' --output table
```
**Expected:**
- Instances: `stopped`, or no rows if terminated.
- Volumes: one, if the server is only stopped; none if terminated.
- Addresses: no rows.
- Snapshots: no rows.

**When to exit everything (the rule):** when you stop using the cloud part for the day, run the four checks above
and stop the server. Then close Terminal. If you won't use the cloud part for several days, terminate the server
(`aws ec2 terminate-instances --instance-ids <INSTANCE_ID>`), so the disk stops billing too. You can rebuild it
later with Terraform (C.3), which is why C.3 comes before you need it.

**Check the Billing page** the next day (Billing and Cost Management → Bills). Budget data can lag by hours,
so the Billing page is the real answer.

### When to keep things running, and when to stop them

| Thing | Where it runs | Cost | Keep it on? |
|---|---|---|---|
| Lima VM | Your Mac | Free, but uses memory, battery and fan | **No.** Stop it when you finish a session. Start it when you need it. |
| The app inside the VM | Your Mac (through the VM) | Free | Only while the VM is running. |
| AWS server | AWS | **Charges while running** | **No.** Stop it every session. Terminate it when the step is finished. |
| CloudWatch logs and alarms | AWS | Small, but not zero | Keep only while you're testing C.4. Delete after. |
| Terraform stack | AWS | Charges while it exists | Destroy at the end of each session that doesn't need it. |

**Rules of thumb:**
- The **VM** is free to leave off, so stop it whenever you aren't using it. Nothing is lost when it stops.
- The **AWS server** is the one that costs money. Stop it at the end of every session without exception.
- If your Mac **sleeps**, the VM pauses with it. That's safe, but the tunnel drops, so reconnect after you wake the Mac.

**What survives a stop:**
- Your project files in `~/LocalAI` stay on the VM's disk after `limactl stop` and `aws ec2 stop-instances`.
- The app comes back by itself after the VM starts: Docker starts when the VM boots, and the compose file sets
  `restart: unless-stopped`, so the container restarts. Check with `docker ps`.
- The AWS server's **public IP changes** when it's stopped and started. Look it up again each session.

**What doesn't survive:**
- `limactl delete` removes the VM and everything in it.
- `terraform destroy` or `aws ec2 terminate-instances` removes the AWS server. Its disk is deleted with it.

> **Start here every time.** The session routine below is what you follow each time you work on the cloud part.
> It only works after C.2 is set up, because it uses your server's instance ID and your SSH key. Until then,
> follow C.0 to C.2 in order.

## Rules for this project

1. **No public port.** The app has no login. Port 8501 stays closed to the internet. You reach it
   through an SSH tunnel, and the app stays bound to `127.0.0.1` on the server.
2. **Budget first.** Set a monthly budget alert (step C.2, part 1) before creating any resource.
3. **Tear down every session.** Each step ends with a teardown. Nothing runs overnight.
4. **No secrets in files or git.** Keys stay in `~/.ssh/` and the AWS credentials file, never in the repo.
5. **Approve each cloud change.** Get the owner's OK before creating or changing a resource.
6. **Write it down.** For each step: what you ran, what you expected, what happened.

## Cost control (read before creating anything)

The aim is to pay as little as possible. These rules keep the bill near zero. Check the
[AWS Free Tier page](https://aws.amazon.com/free) and the pricing pages for current terms, since they change.

1. **Stop the server every time you finish a session.** Closing SSH does not stop billing. Only
   `aws ec2 stop-instances` does (see the session routine below).
2. **Use the smallest server.** `t3.micro` with an 8 GB disk. Don't change this without a reason.
3. **No Elastic IP address.** A reserved public IP costs money when it isn't attached to a running server.
   The public IP changes each time you stop and start the server, so re-check it every session.
4. **No NAT gateway, no load balancer.** Both cost money every hour even when idle. This guide doesn't need them.
5. **Keep logs short.** CloudWatch logs are kept 14 days (set in C.4). Delete the log group when you finish.
6. **Delete snapshots and unused volumes.** They keep charging after the server is gone.
7. **Budget alerts at 50%, 80% and 100%**, plus a budget action that stops the server at 100% (C.2 Part 1).
8. **Check the Billing page every few days,** not just the alerts. Budget data can lag by several hours.

**Session routine:** the full steps, from opening Terminal to closing it, are under
"Session routine: from opening Terminal to closing it" further down. Use that one. Starting after a restart
is under "Starting again after you restart your Mac or shut down".

## Decisions (make these before C.2)

| #   | Decision             | Recommendation                                                                                                                                                                        |
| --- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D.1 | Region               | `us-west-2` (Oregon) or the closest region to you. Use it everywhere.                                                                                                                 |
| D.2 | Server               | One small EC2 instance (`t3.micro`). Simpler than containers.                                                                                                                         |
| D.3 | Where the model runs | On your Mac, not the server. A server model needs a GPU and costs far more. The app on the server will show a model error until the tunnel to Ollama is set up (see the note in C.2). |
| D.4 | Access               | SSH tunnel (rule 1).                                                                                                                                                                  |

---

## C.0: Install the tools on your Mac

**Goal:** the command-line tools you need for C.1 to C.5 are installed.

**Prerequisite:** Homebrew. Check with `brew --version`. If you see "command not found", install it from
https://brew.sh and follow the steps it prints at the end.

**Do:**

```
brew install lima
brew install awscli
brew install terraform
```

**Check:**

```
limactl --version
aws --version
terraform -version
```

Each command should print a version number.

**If it fails:** `command not found` means Homebrew didn't finish. Run `brew doctor`, and paste its output
to the owner.

**Record:** the three version numbers.

**Teardown:** none.

---

## Install Docker (used by C.1 and C.2)

Docker runs the app as a container. You need it on **each Linux machine that runs the app**: the Lima VM
(C.1) and the AWS server (C.2). These steps are the same on both. Install it once per machine.

**Where to run these:**
- **Lima VM:** open the shell with `limactl shell default`, then run the commands. Your prompt shows the VM.
- **AWS server:** connect with `ssh -i ~/.ssh/<KEY_NAME>.pem ubuntu@<SERVER_IP>`, then run the commands.

**Before you start, check whether Docker is already there:**
```
docker --version
```
If it prints a version, skip to the check at the end of this section. If it says `command not found`, continue.

**Run the install** (one block at a time; enter your password if asked):

```
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

```
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

Leave the VM and come back, so the new group takes effect:
```
exit
limactl shell default
```

**Check:**
```
docker run hello-world
```
You should see `Hello from Docker!`.

**If it fails with "permission denied":** you didn't log out and back in after `usermod`. Run `exit`,
then `limactl shell default`, and try again.

Log out and back in, so the new `docker` group takes effect:
```
exit
```
Then reconnect the same way you did before (`limactl shell default` on the VM, or `ssh` to the server).

**Check:**
```
docker run hello-world
```
You should see `Hello from Docker!`.

**If it fails with "permission denied":** you didn't log out and back in after `usermod`. Run `exit`, reconnect,
and try again.

**If `apt-get` can't find the Docker packages:** the repository line didn't save. Check the `docker.list`
file exists: `cat /etc/apt/sources.list.d/docker.list`. It should show one `deb` line for download.docker.com.

**Record:** the Docker version (`docker --version`).

---

## C.1: Run the app on a Linux VM (Lima)

**Goal:** the app runs on Linux, and you know which ports it opens.

### Part 1: Open the VM

Your Lima VM is named `default`.

```
limactl list
```

**Check:** the `default` row shows `Running`.

**If it says `Stopped`:**
```
limactl start default
```

Then open a shell inside it:
```
limactl shell default
```

Your prompt changes to show you're inside the VM (for example `<USER>@lima-default:~$`). Everything
in Part 2 and Part 3 is typed **inside** this shell. Type `exit` to leave it.

**Check (inside the VM):**
```
uname -a
```
The output mentions `Linux`.

### Part 2: Install Docker inside the VM

Install Docker first, using the **Install Docker** section above (run it inside the VM).
When that's done and `docker run hello-world` works, continue to Part 3.

### Part 3: Copy the project into the VM

**Important:** copy the code, **not** `docs/` or `logs/`, which hold your private data.

On your **Mac**, in Terminal (not inside the VM):
```
cd ~/LocalAI
git archive HEAD | limactl shell default -- sh -c 'mkdir -p ~/LocalAI && tar -x -C ~/LocalAI'
```
Note: the `cd` line is on your Mac, where the project's git folder is. Your Mac's project folder is `~/LocalAI`
too, so this command reads the code from there and copies it into the VM's own `~/LocalAI`.

This sends the last commit of the code, and nothing that isn't committed.

Then inside the VM, create the two folders the app needs, empty:
```
cd ~/LocalAI
mkdir -p docs logs
ls
```

**Check:** `ls` shows `app.py`, `Dockerfile`, `docker-compose.yml`, `docs`, `logs`.

**If the first command fails:** note the error and stop. Don't try another way of copying the data.

### Part 4: Start the app

Inside the VM, in `~/LocalAI`:
```
docker compose up -d --build
```

The first build takes several minutes. When it finishes:
```
docker ps
```
You should see a container named like `localai-localai-1` with status `Up`.

**Check the port is bound to 127.0.0.1 only:**
```
ss -tlnp | grep 8501
```
The address must be `127.0.0.1:8501`. If you see `0.0.0.0:8501` or `*:8501`, stop and tell the owner.

**Check the app answers:**
```
curl -I http://127.0.0.1:8501/
```
The first line should be `HTTP/1.1 200 OK`.

**Check it from your Mac:** open http://localhost:8501 in a browser. Lima forwards the port, so the page
should load. If the VM check passed but the browser shows nothing, note that as a port-forwarding issue.

**Note:** the model (Ollama) runs on your Mac, not in the VM, so chat will show a model error. That's
expected for C.1. The page itself should load.

**Record:** the port list and the `ss` output.

**Teardown (C.1):** inside the VM, `docker compose down`. Keep the VM for C.2 practice.

---

### Returning to the VM later (every new session)

Use this whenever you come back to the VM in a new Terminal window.

**1. Check the VM's state**
```
limactl list
```
Look at the `default` row. It shows `Running` or `Stopped`.

**2. If it says `Stopped`, start it**
```
limactl start default
```
This takes a minute or two. Wait until the command finishes and returns to the prompt.

**3. Open a shell inside the VM**
```
limactl shell default
```
Your prompt changes to show you're inside the VM. Everything typed now runs in the VM, not on your Mac.

**4. Check Docker and the app**
```
sudo systemctl status docker
cd ~/LocalAI
docker ps
```
- Docker should show `active (running)`. If not: `sudo systemctl start docker`.
- `docker ps` should show the `localai` container as `Up`. If the list is empty, start the app:
  `docker compose up -d`

**5. Check the app answers**
```
curl -I http://127.0.0.1:8501/
```
The first line should be `HTTP/1.1 200 OK`.

**6. Leave the VM and stop it when you're done**
```
exit
limactl stop default
```
`exit` closes the shell inside the VM. `limactl stop default` shuts the VM down and frees your Mac's memory.

**If `limactl shell` fails:**
- `limactl list` shows `Broken` or something unexpected: run `limactl start default` again, and read the messages it prints.
- The VM won't start at all: note the error message, and check that Lima is up to date with `brew upgrade lima`.

**Warning:** `limactl delete default` removes the VM and everything inside it, including the project copy
in `~/LocalAI`. Don't run it unless you mean to start over.

## C.2: Deploy to one AWS server, reachable only through a tunnel

**Goal:** the app runs on an AWS server. You reach it through an SSH tunnel. Nothing else is open.

### Part 1: Set up the account and a budget (do this first)

1. Sign in to the AWS Console at https://console.aws.amazon.com as the root user.
2. Turn on **MFA** for the root user: your account name (top right) → **Security credentials** → **Assign MFA device**.
3. Create an admin user for daily work: **IAM** → **Users** → **Create user**. Name it `localai-admin`. Tick
   **Provide user access to the AWS Management Console**. Attach the policy **AdministratorAccess**
   (for practice only). Turn on MFA for that user too.
4. Create a budget: **Billing and Cost Management** → **Budgets** → **Create budget** → **Use a template**
   → **Monthly cost budget**. Set the amount to **$10**. Add your email as the alert address.
5. Add alerts at 50%, 80% and 100%: in the budget, open **Alerts** and add a threshold for each, all sent to your email.
6. Add the stop action: in the budget, open **Budget actions** → **Create action** → **Apply action when a
   threshold is met** → choose **Stop EC2 instances** and select the `localai` instance. This is the
   hard stop: it switches the server off if spending reaches the 100% threshold.

**Note:** an alert or action can run several hours after the spending happened. The session routine (below)
is the main protection; the budget is the backstop.

**Check:** you can sign in as `localai-admin`, and the budget shows in the Budgets list.

### Part 2: Connect the command line to AWS

1. In the console, as `localai-admin`: **IAM** → **Users** → `localai-admin` → **Security credentials** →
   **Create access key** → **Command Line Interface (CLI)**. Save the key pair somewhere safe, outside the repo.
2. On your **Mac**:
   ```
   aws configure
   ```
   Enter the access key ID, the secret key, `<your region>` (for example `us-west-2`), and `json` for the output format.
3. Confirm it works:
   ```
   aws sts get-caller-identity
   ```
   The output shows your account and `localai-admin`.

**Check:** the `aws sts` command prints your account, not an error.

**If it fails with "InvalidClientTokenId":** the key was copied wrong. Run `aws configure` again.

**Record:** the account ID is fine to keep in notes. Never store the secret key in the repo.

**Teardown:** when you're done with the key, delete it in IAM → Security credentials.

### Part 3: Create an SSH key pair

On your **Mac**:
```
aws ec2 create-key-pair --key-name <KEY_NAME> --query 'KeyMaterial' --output text > ~/.ssh/<KEY_NAME>.pem
chmod 400 ~/.ssh/<KEY_NAME>.pem
```

**Check:**
```
ls -l ~/.ssh/<KEY_NAME>.pem
```
The permissions start with `-r--------`.

### Part 4: Create a firewall rule that allows only your IP

1. Find your IP address:
   ```
   curl -s https://checkip.amazonaws.com
   ```
   Write it down. You'll use it as `<MY_IP>` below.
2. Find the default network (VPC):
   ```
   aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text
   ```
   Write it down as `<VPC_ID>`.
3. Create the security group:
   ```
   aws ec2 create-security-group --group-name localai-ssh --description "SSH from my IP only" --vpc-id <VPC_ID> --query GroupId --output text
   ```
   Write the output as `<SG_ID>`.
4. Allow SSH from your IP only:
   ```
   aws ec2 authorize-security-group-ingress --group-id <SG_ID> --protocol tcp --port 22 --cidr <MY_IP>/32
   ```

**Check:**
```
aws ec2 describe-security-groups --group-ids <SG_ID> --query 'SecurityGroups[0].IpPermissions'
```
You should see one rule: port 22, from `<MY_IP>/32`. Nothing else.

**If your IP changes later:** the SSH rule won't match. Update it with `aws ec2 revoke-security-group-ingress`
and `authorize-security-group-ingress` using the new IP.

### Part 5: Launch one server

1. Find the latest Ubuntu 24.04 image:
   ```
   aws ec2 describe-images --owners 099720109477 --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" "Name=state,Values=available" --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text
   ```
   Write the output as `<AMI_ID>`.
2. Launch the instance:
   ```
   aws ec2 run-instances --image-id <AMI_ID> --instance-type t3.micro --key-name <KEY_NAME> --security-group-ids <SG_ID> --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=localai}]' --query 'Instances[0].InstanceId' --output text
   ```
   Write the output as `<INSTANCE_ID>`. This launches with the default disk. To keep the disk small, add
   `--block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=8,VolumeType=gp3}'` to the command above.
3. Wait until it's running, then get its public IP. The IP changes each time you stop and start the server, so
   check it every session:
   ```
   aws ec2 describe-instances --instance-ids <INSTANCE_ID> --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
   ```
   Write it down as `<SERVER_IP>`.

**Check:** the instance is `running` (`aws ec2 describe-instances --instance-ids <INSTANCE_ID> --query 'Reservations[0].Instances[0].State.Name' --output text`).

**Cost note:** `t3.micro` may be free-tier eligible, but check the Billing page. Expect a small charge if
it's not, and stop the instance between sessions.

**Record:** the instance ID, the region, and the monthly cost you see on the Billing page after one day.

### Part 6: Install Docker and copy the project to the server

From your **Mac**:
```
ssh -i ~/.ssh/<KEY_NAME>.pem ubuntu@<SERVER_IP>
```
Type `yes` if asked about the host key. You're now on the server.

On the **server**, install Docker using the **Install Docker** section near the top of this guide (run it on the server, not your Mac). Then check it works:
```
exit
ssh -i ~/.ssh/<KEY_NAME>.pem ubuntu@<SERVER_IP>
docker run hello-world
```

Copy the project. From your **Mac**, in the project folder:
```
git archive HEAD | ssh -i ~/.ssh/<KEY_NAME>.pem ubuntu@<SERVER_IP> 'mkdir -p ~/LocalAI && tar -x -C ~/LocalAI && mkdir -p ~/LocalAI/docs ~/LocalAI/logs'
```

### Part 7: Start the app on the server

On the **server** (SSH in again):
```
cd ~/LocalAI
docker compose up -d --build
docker ps
curl -I http://127.0.0.1:8501/
```
The `curl` should show `HTTP/1.1 200 OK`.

### Part 8: Open the tunnel and use the app

On your **Mac**, in a new terminal window, keep this running:
```
ssh -i ~/.ssh/<KEY_NAME>.pem -N -L 8501:127.0.0.1:8501 ubuntu@<SERVER_IP>
```
The window will look stuck. That's expected. It's the tunnel.

Then open http://localhost:8501 in your browser. The app should load.

**Check the public port is closed.** From your Mac, in another window:
```
curl -m 5 http://<SERVER_IP>:8501
```
This must **fail or time out**. If it returns a page, stop and tell the owner, because the port is open to the internet.

**Model note:** chat shows a model error, because the model runs on your Mac. Connecting the server to your
Mac's Ollama needs a second tunnel, which is a later decision (D.3).

**Record:** the result of both checks, and a screenshot of the working app if you like.

**Teardown (C.2):** close the tunnel window (Ctrl+C). On the server, `docker compose down`.
Then in Part 9, terminate the server.

### Part 9: Stop or remove the server

To stop it (this is the normal end of every session, and it stops the compute charges):
```
aws ec2 stop-instances --instance-ids <INSTANCE_ID>
```

To remove it completely:
```
aws ec2 terminate-instances --instance-ids <INSTANCE_ID>
aws ec2 delete-security-group --group-id <SG_ID>
aws ec2 delete-key-pair --key-name <KEY_NAME>
```
Delete the security group only after the instance is fully terminated. If it errors with "DependencyViolation",
wait a minute and try again.

---

## C.3: Define the same setup in Terraform

open**Goal:** a file describes the server and its firewall. `terraform apply` builds them, and `terraform destroy` removes them. The file is the setup, so you can rebuild it at any time.

**What Terraform is, in plain terms:** you write what you want (one server, one firewall rule), Terraform compares it with what exists in AWS, and it creates, changes or removes resources to match. It keeps a record of what it made in a **state file** on your Mac, so it knows which resources are its own.

**Prerequisites:** C.0 (Terraform installed, check with `terraform -version`) and C.2 Part 2 (the AWS CLI works, check with `aws sts get-caller-identity`).

**Where to run everything in this section:** your **Mac**, in Terminal.

### Part 1: Remove the server and firewall you made by hand

Terraform only manages resources it created, and the names would clash with the ones you made in C.2. So remove those first. Your SSH key pair (`<KEY_NAME>`) stays; Terraform uses it by name.

1. **Check the old server's ID:**
   ```
   aws ec2 describe-instances --query 'Reservations[].Instances[].[InstanceId,State.Name,Tags[?Key==`Name`]|[0].Value]' --output table
   ```
   Find the row named `localai`. Note its `InstanceId`, which starts with `i-`.

2. **Terminate it** (this deletes the server's disk too):
   ```
   aws ec2 terminate-instances --instance-ids <OLD_INSTANCE_ID>
   aws ec2 wait instance-terminated --instance-ids <OLD_INSTANCE_ID>
   ```

3. **Delete the security group** you created in C.2. You must do this after step 2, because AWS won't delete a group that's still in use:
   ```
   aws ec2 delete-security-group --group-name localai-ssh
   ```

**Check:** both commands finish with no error. Then `aws ec2 describe-security-groups --filters Name=group-name,Values=localai-ssh` returns no groups.

**If step 3 says "DependencyViolation":** the instance hasn't finished terminating. Wait a minute, then run step 3 again.

### Part 2: Find your public IP

Terraform needs it to limit SSH to your address.

```
curl -s https://checkip.amazonaws.com
```

Write the address down (for example `203.0.113.5`). You'll use it in the plan and apply commands. If your internet changes, your IP changes, and you must update this value.

### Part 3: Create the folder and the file

1. **Create the folder** inside the project:
   ```
   cd ~/LocalAI
   mkdir -p infra
   cd infra
   ```

2. **Create the file.** Use either editor:
   - **VS Code:** `code main.tf`
   - **Terminal:** `nano main.tf`

3. **Paste this** into the file, then save (in nano: Ctrl+O, Enter, Ctrl+X; in VS Code: Cmd+S):

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "region" {
  default = "us-west-2"
}

variable "my_ip" {
  description = "Your public IP address, for example 203.0.113.5"
  type        = string
}

provider "aws" {
  region = var.region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "aws_security_group" "localai_ssh" {
  name        = "localai-ssh"
  description = "SSH from my IP only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${var.my_ip}/32"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "localai" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "t3.micro"
  key_name               = "<KEY_NAME>"
  vpc_security_group_ids = [aws_security_group.localai_ssh.id]

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
  }

  tags = {
    Name = "localai"
  }
}

output "server_ip" {
  value = aws_instance.localai.public_ip
}
```

**What each part means:**

| Block                           | What it does                                                                           |
| ------------------------------- | -------------------------------------------------------------------------------------- |
| `terraform { ... }`             | Says which plugin to download: the AWS provider, version 5.                            |
| `variable "region"`             | The AWS region, `us-west-2`. Change it here only.                                      |
| `variable "my_ip"`              | Your IP. You give it on the command line, so it isn't saved in the file.               |
| `provider "aws"`                | Tells Terraform to use the region above and your AWS credentials from `aws configure`. |
| `data "aws_vpc"`                | Finds your default network. It reads existing resources; it creates nothing.           |
| `data "aws_ami"`                | Finds the latest Ubuntu 24.04 image from Canonical (owner `099720109477`).             |
| `resource "aws_security_group"` | The firewall: SSH (port 22) from your IP only, and outbound traffic allowed.      |
| `resource "aws_instance"`       | The server: `t3.micro`, 8 GB disk, your key pair, and the firewall above.              |
| `output "server_ip"`            | Prints the server's address after `apply`.                                             |

**Check:** `ls` shows `main.tf` in `~/LocalAI/infra`.

### Part 4: Keep the state file out of git

The state file holds details about your resources, so it must not be committed. Add these lines to the end of `~/LocalAI/.gitignore` (check the file first with `tail ~/LocalAI/.gitignore`):

```
infra/.terraform/
*.tfstate
*.tfstate.backup
```

**Check:** `cd ~/LocalAI && git status` no longer lists `infra/.terraform` or any `.tfstate` file.

### Part 5: Initialize, check, and plan

Still in `~/LocalAI/infra`:

1. **Download the AWS plugin:**
   ```
   terraform init
   ```
   **Expect:** `Terraform has been successfully initialized!` This creates a `.terraform` folder, which is git-ignored.

2. **Check the file's syntax:**
   ```
   terraform validate
   ```
   **Expect:** `Success! The configuration is valid.`

3. **See what Terraform would do.** Replace the IP with yours from Part 2:
   ```
   terraform plan -var "my_ip=203.0.113.5"
   ```
   **Read the whole output before continuing.** It should end with:
   `Plan: 2 to add, 0 to change, 0 to destroy.`
   The two resources are the security group and the instance. In the output, a `+` means "will be created."

   **If the plan says anything else** (for example "to destroy," or it names resources you didn't expect), stop and paste the summary here.

### Part 6: Build it

**Use a saved plan.** Save the plan to a file, then apply that file. This guarantees the changes match the
plan you read:

```
terraform plan -var "my_ip=<YOUR_IP>" -out=tfplan
terraform apply tfplan
```

Use the **same** IP in both commands. If you apply without a saved plan, Terraform shows the reminder
"you did not use -out." It isn't an error. It means the apply made a fresh plan instead of using the one you read.
That's safe only if nothing changed in between, so prefer the saved-plan version.

After `apply`, Terraform prints the server's IP. Check the output ends with `Apply complete! Resources: 2 added`.

The steps below are the same as before.


```
terraform apply -var "my_ip=203.0.113.5"
```

Terraform shows the same plan again. Type `yes` and press Enter. It finishes in about a minute, and it prints:

```
server_ip = "35.x.x.x"
```

**Check:** note the printed IP. Confirm the instance exists:
```
aws ec2 describe-instances --filters Name=tag:Name,Values=localai Name=instance-state-name,Values=running --query 'Reservations[].Instances[].[InstanceId,PublicIpAddress]' --output table
```

### Part 7: Connect to the new server

Terraform prints the IP in quotes. To use it in a command, print it bare:

```
cd ~/LocalAI/infra
terraform output -raw server_ip
```

Use that value in the `ssh` command. **Don't use your own IP**, which `checkip.amazonaws.com` shows. The two are different:
- `curl -s https://checkip.amazonaws.com` prints **your** Mac's public IP.
- `terraform output -raw server_ip` prints **the server's** IP.

**If your command prints `dquote>` or waits for a closing quote:** a quote mark got into the command. Press
Ctrl+C, or type `"` and press Enter, then run it again without quotes.

#### If SSH hangs or times out (during Part 7)

The firewall only allows the IP you gave Terraform. If your IP has changed, the firewall drops the connection
silently, so SSH waits and then fails with `Operation timed out`. To check:

1. **Get your current IP:** `curl -s https://checkip.amazonaws.com`
2. **Compare it with the rule:** `terraform show | grep -A2 cidr_blocks` (run from `~/LocalAI/infra`).
   If the address shown doesn't match your current IP, that's the cause.
3. **Test the port:** `nc -vz -G 5 <SERVER_IP> 22`. A timeout confirms the firewall is blocking you.
4. **Update the rule** with your current IP, then apply the saved plan:
   ```
   terraform plan -var "my_ip=<YOUR_CURRENT_IP>" -out=tfplan
   terraform apply tfplan
   ```
   Check the plan changes only the security group.

Repeat this whenever your IP changes, for example when you switch networks.

### Part 8: Set up the new server

The server is empty, so install Docker on it first. Run these **on the server**, one block at a time. Enter
your password if asked.

```
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

```
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

**Log out and back in**, so the `docker` group applies:
```
exit
ssh -i ~/.ssh/<KEY_NAME>.pem ubuntu@<SERVER_IP>
```

**Check Docker works:**
```
docker run hello-world
docker compose version
```
`hello-world` prints `Hello from Docker!`, and `docker compose version` prints a version number.

Then set up the rest of the server:

1. **Confirm the server:** `hostname` and `whoami` (the user is `ubuntu`).
2. **Copy the project** from your Mac (C.2 Part 6), then check with `ls ~/LocalAI` on the server.
3. **Start the app** (C.2 Part 7): `cd ~/LocalAI`, `docker compose up -d --build`, then `curl -I http://127.0.0.1:8501/`.

If `docker` needs `sudo` after reconnecting, check that the `usermod` line ran, then reconnect again.

### Part 9: Prove you can rebuild it

This test shows the file really describes the setup:

```
terraform destroy -var "my_ip=203.0.113.5"
```
Type `yes`. Then build it again:
```
terraform apply -var "my_ip=203.0.113.5"
```
Type `yes`.

**Check:** the second apply prints a new `server_ip`, and the plan created the same two resources as before.

### Teardown and the rules for C.3

- **Destroy when you finish a session you won't need for a while:**
  ```
  terraform destroy -var "my_ip=203.0.113.5"
  ```
  This deletes the server, its disk, and the firewall. Nothing else is removed.
- **Stop instead of destroying** if you'll use it again the same day: `aws ec2 stop-instances --instance-ids <INSTANCE_ID>` (the session routine covers this).
- **Keep `main.tf`** in the repo, and never commit the state file.

### Troubleshooting

| Message | Meaning | What to do |
|---|---|---|
| `command not found: terraform` | Terraform isn't installed | Run C.0 again |
| `No valid credential sources` | The AWS CLI isn't configured | Run `aws sts get-caller-identity`; fix with `aws configure` |
| `InvalidGroup.Duplicate` or `already exists` | The old security group still exists | Run Part 1 step 3 again |
| `InvalidKeyPair.NotFound` | `<KEY_NAME>` doesn't exist in AWS | Recreate the key pair (C.2 Part 3), then apply again |
| `Error: no matching AMI found` | The Ubuntu image name changed | Paste the message here |
| `terraform init` fails | No internet, or a proxy blocks it | Check your connection, then run it again |

Paste any other message here, with the step it came from.

---

## C.4: Logs and one alarm

**Goal:** the app's activity log goes to CloudWatch, and an alarm fires on a test event.

**Prerequisite:** the server from C.2 or C.3 is running.

### Part 1: Give the server permission to send logs

1. In the AWS Console: **IAM** → **Roles** → **Create role**.
2. **AWS service** → **EC2**. Attach the policy **CloudWatchAgentServerPolicy**. Name the role `localai-logs`.
3. **EC2** → **Instances** → select `localai` → **Actions** → **Security** → **Modify IAM role** → choose
   `localai-logs` → **Update**.

### Part 2: Install and start the CloudWatch agent (on the server)

SSH into the server, then:
```
wget https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb
```

Create a config file that sends the activity log. Save this as `~/cw-config.json`:

```json
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/home/ubuntu/LocalAI/logs/activity.jsonl",
            "log_group_name": "localai-activity",
            "log_stream_name": "{instance_id}",
            "retention_in_days": 14
          }
        ]
      }
    }
  }
}
```

Start the agent with it:
```
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/home/ubuntu/cw-config.json -s
```

**Check:**
```
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status
```
The status says `running`.

### Part 3: Create an alarm for a blocked action

The app writes a `blocked` event when it refuses something. Test that the alarm fires:

1. Make a blocked action on purpose: in the app (through the tunnel), ask it to save a file outside `docs/`
   (for example "save a note called ../test.md with hello"). It should refuse.
2. In the AWS Console: **CloudWatch** → **Log groups** → `localai-activity` → **Create metric filter**.
   Filter pattern: `{ $.event = "blocked" }`. Metric name: `LocalAIBlocked`. Metric value: `1`.
3. **CloudWatch** → **Alarms** → **Create alarm** → metric `LocalAIBlocked` → threshold **≥ 1** over **5 minutes**.
   Add your email as the notification.

**Check:** after the blocked action, the alarm turns to `In alarm` within a few minutes, and you get the email.

**If the alarm never fires:** check the log arrived. In **Log groups** → `localai-activity`, open the newest
stream and look for a line containing `"event": "blocked"`. If it's not there, the agent isn't reading the file.

**Privacy check:** the log holds names and counts, never your request text. Open one stream and confirm.

**Teardown (C.4):** delete the alarm, the metric filter, and the log group when you're done.

---

## C.5: Replace the shared token with a least-privilege role

**Goal:** GitHub Actions deploys using a role it assumes through OIDC. No stored access keys.

**Prerequisite:** C.3 (the Terraform stack). The workflow only needs to plan, not apply, for this step.

### Part 1: Add GitHub as an identity provider

1. **IAM** → **Identity providers** → **Add provider** → **OpenID Connect**.
2. Provider URL: `https://token.actions.githubusercontent.com`. Audience: `sts.amazonaws.com`.
3. Click **Add provider**.

### Part 2: Create a role only this repo can use

1. **IAM** → **Roles** → **Create role** → **Web identity** → choose the GitHub provider, audience `sts.amazonaws.com`.
2. GitHub organization: `<USER>`. Repository: `LocalAI`. Branch: `model-testing`.
3. Attach **no** policies yet. Name the role `localai-github-plan`.
4. Open the role's **Trust relationships** and check the condition limits the subject to your repo and branch:
   `"repo:<USER>/LocalAI:ref:refs/heads/model-testing"`.

Then give it one permission: read-only for the Terraform stack. Add an inline policy with only what
`terraform plan` needs (for example `ec2:Describe*`). Keep it narrow.

### Part 3: Use it in the workflow

Add to the top of the `diagrams` job (or a new job) in `.github/workflows/tests.yml`:

```yaml
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<ACCOUNT_ID>:role/localai-github-plan
          aws-region: us-west-2
      - run: aws sts get-caller-identity
```

Replace `<ACCOUNT_ID>` with your account ID from C.2 Part 2.

**Check:** the run shows the assumed role in the `get-caller-identity` output.

### Part 4: Prove the old token no longer works

Delete the old stored access keys in **GitHub** → repo **Settings** → **Secrets and variables** → **Actions**
(remove any AWS key secrets). Then confirm no workflow still uses them.

**Check:** a workflow run uses the role, not a stored key.

**Teardown (C.5):** none to remove. Keep the role; it only costs nothing while idle.

---

## Full teardown checklist (run every session)

- [ ] The server is stopped (`aws ec2 stop-instances`) or terminated if the step is done.
- [ ] The local VM is stopped (`limactl stop default`).
- [ ] No snapshots or unused volumes: `aws ec2 describe-volumes --query 'Volumes[].[VolumeId,State]'` and `aws ec2 describe-snapshots --owner-ids self`.
- [ ] The CloudWatch log group is deleted or still within its 14-day retention.
- [ ] No Elastic IP addresses (they cost money when idle): `aws ec2 describe-addresses`.
- [ ] No load balancers or NAT gateways: check the EC2 console.
- [ ] `terraform destroy` run if you used Terraform.
- [ ] The Billing page checked the next day.

## What "done" means for the whole project

- The app runs on the server and loads through the tunnel.
- `curl -m 5 http://<SERVER_IP>:8501` fails or times out.
- `terraform destroy` followed by `terraform apply` rebuilds the same setup.
- The alarm fires on a test blocked action, and the log holds no request text.
- The workflow runs with a role and no stored access key.
- The teardown checklist is complete and nothing is running.

## Not doing, and why

These were considered and rejected for this project. Each one would break a rule above, or cost more than
the project needs. Revisit only by changing the rule first, in this note and in the threat model.

| Idea | Why not | What would change the decision |
|---|---|---|
| Cloud model APIs (Amazon Bedrock, Claude) | The project is local-only by rule (CLAUDE.md). Your notes would be sent to a cloud service. | A deliberate decision to change the privacy rule, with a threat model update |
| Public container hosting (App Runner, ECS on Fargate) | Exposes the app to the internet. The app has no login, so this breaks rule 1 | Authentication in front of the app, and a threat model for the public endpoint |
| Personal documents in S3, or a third-party vector store (Pinecone) | Moves private files off your machine | The same privacy decision as above |
| SageMaker GPU endpoints | Costly, and the opposite of the low-cost goal | A model too large for the Mac, and a budget for it |
| Redis caching, Lambda ingestion pipelines, deduplication at scale | Solve load this app does not have (one user) | More than one user, or measured slowness |

The parts of the wider roadmap that do fit are already in this guide: Terraform, least-privilege IAM, the VPC
and security group, and encryption (C.2, C.3 and C.5). Add encryption at rest (an encrypted EBS volume) when you
build C.3, so the Terraform file sets it.

## Threat model

Before C.2, update `design/threat-model.md` with the cloud risks: the server's exposure, the tunnel, the
Terraform state file, and the role's permissions. For each, write the control and the check that proves it.

_Proposed. Update this note in the same change whenever a step changes._
