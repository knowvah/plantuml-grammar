## Observation: how the sibling knowvah repos publish to npm
- **Context**: Planning #1 (npm packaging) against knowvah/dot-engine (origin/main c3a81f76)
  and knowvah/dot-plugins (origin/main 0fd36b2), 2026-10-26.
- **Finding**: Both use npm trusted publishing (OIDC, no NPM_TOKEN) from a workflow named
  `release.yml` in a GitHub environment `release`; the npm trusted publisher is pinned to
  that file name and environment. npm >= 11.5.1 is installed in the job. Each release is
  then mirrored to GitHub Packages with GITHUB_TOKEN, because consumers that need the
  private `@knowvah/theme` map the `@knowvah` scope to npm.pkg.github.com. The first publish
  of a new package is manual (`npm login`, `npm publish` with 2FA), since a trusted
  publisher can only be added to a package that already exists.
  dot-engine (one package): semantic-release on push to main; the version lives only in the
  tag, npm and the GitHub Release (`package.json` stays `0.0.0-development`); nothing is
  committed back; no CHANGELOG file.
  dot-plugins (6 packages): release-please manifest mode; a bot release PR bumps versions
  and CHANGELOGs, and merging it publishes `paths_released`.
- **Impact**: release-please opens its release PR with GITHUB_TOKEN, and PRs created that
  way do not trigger workflows, so under this repo's ruleset 25892693 (required `python`
  and `node`, no bypass) the release PR could never merge. dot-plugins has no required
  checks. semantic-release opens no PR and only pushes a tag, so it fits the ruleset.
  semantic-release's default rules release on every `fix:` regardless of scope, and this
  repo merges with merge commits, so each commit on the branch is analyzed: `fix(ci):`
  (3bc092a) would have cut a patch release. CI-only fixes should use `ci:`.
  dot-engine's CONTRIBUTING.md is stale on two points: it says PRs are squash-merged (the
  repo allows merge commits only) and that dot-plugins uses Changesets (it uses
  release-please).
- **Confidence**: High

## Observation: semantic-release cannot start below 1.0.0
- **Context**: Choosing the first version of `@knowvah/plantuml-grammar` (#1), 2026-10-26.
- **Finding**: The semantic-release FAQ says starting at a version other than 1.0.0 "is
  not supported"; with no `v*` tag its first release is 1.0.0, and it treats 0.x like any
  other major (a breaking change still bumps the major). dot-engine bootstrapped with a
  manual 0.1.0 publish (no tag) and its first tag is v1.0.0. Node 26.9.0 ships npm
  11.19.1, so the release job needs no `npm install -g npm@latest` for trusted publishing
  (>= 11.5.1).
- **Impact**: The manual bootstrap publish is a placeholder (0.1.0); the first real release
  is 1.0.0 from CI on the merge. Tagging v0.1.0 by hand to stay in 0.x buys nothing.
- **Confidence**: High (FAQ, dot-engine tags); not run end to end here, because the
  scratch simulation needed unsigned commits and was declined.

## Observation: npm publish fails with E403 when the account has no 2FA
- **Context**: Bootstrap publish of `@knowvah/plantuml-grammar@0.1.0` (#1), 2026-10-26,
  npm 11.19.1, logged in as the org owner's npm account.
- **Finding**: `npm publish` got `403 ... Two-factor authentication or granular access
  token with bypass 2fa enabled is required to publish packages`. The debug log shows the
  PUT went straight to 403 with no 401 OTP challenge, so npm never prompted for a code;
  `npm profile get "two-factor auth"` returned `disabled`. The registry requires 2FA on the
  account (or a bypass-2FA granular token) for any publish, including a package's first.
- **Impact**: Enable 2FA on the npm account before the manual bootstrap publish. Do not
  work around it with a bypass-2FA token: CI publishes through OIDC and needs no token.
  A failed run of the bootstrap chain leaves `packages/engine/package.json` and
  `package-lock.json` at 0.1.0 in the working tree; restore them before committing.
- **Confidence**: High (debug log, `npm profile get`)

## Observation: npm publish to @knowvah returns E404 for an account outside the org
- **Context**: Retrying the bootstrap publish of `@knowvah/plantuml-grammar@0.1.0` (#1)
  after enabling 2FA, 2026-10-26.
- **Finding**: The 2FA web confirmation succeeded (PUT 401, web auth, done-check 200),
  then the retried PUT returned `404 Not Found`. The logged-in account was not a member of
  the `knowvah` npm organization: `npm org ls knowvah` returned `{}` and `npm team ls
  knowvah` returned 403. The existing `@knowvah/*` packages are maintained by a different
  npm account (`npm view @knowvah/dot-engine maintainers`). The registry answers a publish
  into a scope the user cannot write to with 404, not 403.
- **Impact**: Before the bootstrap publish, check `npm whoami` against
  `npm view @knowvah/dot-engine maintainers`, or `npm org ls knowvah <user>`.
- **Confidence**: High (debug log, npm org/team/view output)

## Observation: npm trusted publishers need --allow-publish and expire after two days
- **Context**: Adding the trusted publisher for `@knowvah/plantuml-grammar` (#1),
  2026-10-26, npm 11.19.1.
- **Finding**: `npm trust github <pkg> --file <workflow> --repo owner/repo --env <env>`
  configures trusted publishing from the CLI (npm >= 11.15, account 2FA, package must
  exist; one configuration per package; change it with `npm trust revoke --id`). A
  configuration must name at least one permission: `--allow-publish` (`npm publish`) or
  `--allow-stage-publish`; the website calls these "Allowed actions". Per
  docs.npmjs.com/trusted-publishers, npm does not validate the fields on save, and a new
  configuration expires if its first successful publish does not happen within two days.
- **Impact**: semantic-release runs `npm publish`, so the publisher needs
  `--allow-publish`; merge the release PR within two days of creating it.
- **Confidence**: High (`npm help trust`, npm docs)
