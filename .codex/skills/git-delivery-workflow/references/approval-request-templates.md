# Approval Request Templates

Use these templates when asking the user to approve a Git action. These are not commit message templates.

## Branch Proposal

```markdown
Suggested next Git action: create a new branch

Reason: <why current work should be isolated>
Current branch: <current-branch>
Suggested branch: <branch-name>
Base: <base-branch>

Approve or reject branch creation.
```

## Commit Approval Request

```markdown
Suggested next Git action: commit current checkpoint

Branch: <branch-name>
Scope: <one-sentence checkpoint summary>
Why now: <why this is a coherent stopping point>
Verification:
- <command 1> -> <result>
- <command 2> -> <result>

Proposed commit subject:
`<type>(<scope>): <summary>`

Commit body summary:
- Changes: <what changed>
- Refs: <spec/plan/issue if any>
- Optional Verification in commit body: <only if commit history should retain it>

Approve or reject this commit.
```

## PR Readiness Proposal

```markdown
Suggested next Git action: mark branch PR-ready

Branch: <branch-name>
PR title: <title>
Scope:
- <point 1>
- <point 2>
Non-goals:
- <point 1>
Verification:
- <command> -> <result>
Risks / follow-ups:
- <point 1>

Approve or reject PR preparation.
```

## Merge Approval Request

```markdown
Suggested next Git action: merge into `main`

Source branch: <branch-name>
Target branch: main
Strategy: <squash | no-ff>
Reason: <why this merge strategy fits>
Verification:
- <command> -> <result>

Post-merge options:
- delete source branch: <yes/no>

Approve or reject this merge.
```

## Release Approval Request

```markdown
Suggested next Git action: create release <branch | tag>

Release version: <vX.Y.Z>
Target commit/branch: <main or release/vX.Y.Z>
Reason: <direct tag or stabilization branch>
Verification:
- <command> -> <result>

Planned commands:
- <command 1>
- <command 2>

Approve or reject this release action.
```
