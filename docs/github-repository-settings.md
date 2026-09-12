# Recommended GitHub repository settings

Repository: `sridharrajarao-site/gridrudder`

These settings require GitHub owner/administrator mutations and are not applied by the source files in this repository. Apply them only after review of the first sanitized commit.

## Repository basics

- Set `main` as the default branch.
- Enable Issues and disable blank issues; keep Projects, Wiki, and Discussions off until someone owns them.
- Allow squash merge; disable merge commits and rebase merge for a simple, linear pre-1.0 history.
- Automatically delete head branches after merge.
- Add the description: `Supervised power orchestration for AI infrastructure.`
- Add topics such as `gpu`, `power-management`, `data-center`, `nvidia`, `energy`, and `simulation` without using `production-ready` or `autonomous`.
- Create labels referenced by the issue forms before enabling Issues: `bug`, `enhancement`, `compatibility`, and `triage`.

## Main-branch ruleset

Create an active ruleset for `main` and apply it to administrators:

- Block deletion and force pushes.
- Require a pull request with at least one approval.
- Dismiss stale approvals and require approval of the most recent reviewable push.
- Require conversation resolution.
- Require linear history.
- Require these checks before merge:
  - `Core / Python 3.9`
  - `Core / Python 3.12`
  - `Core / Python 3.13`
  - `Site / build, lint, test`
  - `DCO / commit sign-off`
- Require branches to be current before merge once CI names are confirmed on the first pull request.
- Do not enable merge queue until its additional event path has been added to CI and tested.

Add a second immutable-tag ruleset matching `v*` that blocks tag updates and deletion. Do not grant routine bypass rights.

## Security

- Enable GitHub Advanced Security features available for public repositories: secret scanning, push protection, dependency graph, Dependabot alerts, and Dependabot security updates.
- Enable private vulnerability reporting and verify that its responders match the owners of the interim `pilot@gridrudder.com` security route.
- Configure CodeQL default setup for Python and JavaScript/TypeScript after confirming it does not duplicate or weaken required CI.
- Set the default `GITHUB_TOKEN` permission to read repository contents only and require approval for workflows from first-time outside contributors.
- Limit Actions to GitHub-authored actions initially. Current workflows pin them to reviewed full commit SHAs; keep Dependabot’s Actions updates under normal review.
- Review Dependabot pull requests normally; automatic creation is not authorization to merge.

## Ownership and releases

- Add a real CODEOWNERS mapping only after the responsible individual or team slug is confirmed. Require its review for `.github/workflows/**`, `gridgpu/hardware_lab.py`, `gridgpu/performance_trial.py`, `gridgpu/audit.py`, `gridgpu/policy.py`, `gridgpu/session.py`, `SECURITY.md`, and safety/evidence specifications.
- Protect release management with least-privilege roles; do not give triage users write or Actions-management permission.
- Use GitHub release attestations or verified signatures and attach only the package created by `tools/build_public_release.py` plus its checksum.
- Mark every `0.x` release as a pre-release unless the architect records a different decision. Never label a source release as production-ready.
- Create a protected `production` environment with a required reviewer before adding any deployment workflow. No deployment workflow exists in the public source today.

## First-publication verification

1. Create the repository from the sanitized package rather than importing nested or unscanned history.
2. Confirm the private physical-trial artifact, nested `.git`, `node_modules`, build output, deployment metadata, and local secrets are absent.
3. Open a signed-off test pull request and confirm all exact check names before making them required.
4. Test the security-reporting path, issue forms, DCO failure/recovery, Dependabot, branch protection, and release checksum verification.
5. Record who owns vulnerability response, conduct reports, dependency updates, releases, and pilot-data deletion.
