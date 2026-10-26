# AWS command-line steps (for the cloud guide)

Written for: the project owner, to run AWS commands safely from your Mac.
Used by: `design/cloud-deploy.md`. Every AWS command in that guide follows these steps.

**Before any command that creates, changes or deletes something, do steps 1 and 2.**

## Part 1: One-time setup

### 1. Install the AWS CLI
```
brew install awscli
aws --version
```
**Check:** the version prints (for example `aws-cli/2.x`).

### 2. Create the credentials (once)
In the AWS Console, as `localai-admin` (not as root):
1. **IAM** → **Users** → `localai-admin` → **Security credentials** → **Create access key**.
2. Choose **Command Line Interface (CLI)** → **Create access key**.
3. Copy the **Access key ID** and **Secret access key** now. AWS shows the secret only once.

**Never paste these into a file in the project, a commit, a chat, or a screenshot.**

### 3. Configure the CLI
```
aws configure
```
Enter:
- **Access key ID:** from step 2
- **Secret access key:** from step 2
- **Default region name:** `us-west-2` (the region from D.1 in the guide)
- **Default output format:** `json`

The values are saved in `~/.aws/credentials` and `~/.aws/config`, on your Mac only.

**Check:**
```
aws sts get-caller-identity
```
The output shows your account ID and the `localai-admin` user. If it shows an error, run `aws configure` again.

### 4. Delete the access key when the setup is finished
When you're comfortable with the guide, or if you stop using the CLI for a while:
Console → **IAM** → **Users** → `localai-admin` → **Security credentials** → delete the key.

For a longer-term setup, switch to IAM Identity Center (AWS SSO), which avoids long-lived keys. That's a later step.

## Part 2: Before every AWS command

Run these three checks first. They take seconds and prevent most mistakes.

```
aws sts get-caller-identity          # which account and user am I using?
aws configure get region             # which region will this use?
```

**Read the output.** If the account or the region isn't what you expect, stop.

For commands that change things, look at what exists first:
```
aws ec2 describe-instances --query 'Reservations[].Instances[].[InstanceId,State.Name,Tags[?Key==`Name`]|[0].Value]' --output table
```
This lists your instances, their state, and their name tag.

## Part 3: Read before you change

The order for every change:
1. **Describe** the current state (read-only command).
2. **Run** the change with one resource.
3. **Describe** again to confirm the result.
4. **Write it down:** the command, the expected result, the actual result.

Example (stop the server):
```
aws ec2 describe-instances --instance-ids <INSTANCE_ID> --query 'Reservations[0].Instances[0].State.Name' --output text
aws ec2 stop-instances --instance-ids <INSTANCE_ID>
aws ec2 describe-instances --instance-ids <INSTANCE_ID> --query 'Reservations[0].Instances[0].State.Name' --output text
```
Expected: `running`, then `stopping` or `stopped`, then `stopped`.

## Part 4: Reading errors

| Error contains | Usually means | Do this |
|---|---|---|
| `InvalidClientTokenId` | The access key is wrong | Run `aws configure` again |
| `AccessDenied` or `UnauthorizedOperation` | The user lacks permission | Check the user's policies in IAM; don't add broad permissions to fix it |
| `DependencyViolation` | Something still uses the resource | Delete the thing using it first (for example, terminate the instance before the security group) |
| `InvalidParameterValue` | A value is wrong (ID, region, name) | Check the value with the `describe-` command |
| `Could not connect to the endpoint` | Wrong region, or no internet | Check `aws configure get region` and your connection |

Paste the full error (without any keys) into your notes. Most errors repeat, so the notes save time later.

## Part 5: Cost checks (run these at the end of each session)

```
aws ec2 describe-instances --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output table
aws ec2 describe-addresses --query 'Addresses[].[PublicIp,AssociationId]' --output table
aws ec2 describe-volumes --query 'Volumes[].[VolumeId,State,Size]' --output table
```
**Expected at the end of a session:**
- Instances: `stopped` (or no rows if terminated).
- Addresses: no rows, or one with no association (remove it if you don't need it).
- Volumes: only the root disk of the stopped server.

## Rules

1. **Describe before you change.** Always.
2. **One resource at a time.** Don't run a command with a wildcard that could hit more than you meant.
3. **Check the account and region first.** Every session.
4. **Never put keys in a file that could be committed.** Use `~/.aws/`, which is outside the repo.
5. **Write it down.** The command, the result, and anything unexpected.
6. **If unsure, stop and ask.** A paused command costs nothing; a wrong one can cost money or delete something.

_Proposed. Update this note whenever a command in the guide changes._
