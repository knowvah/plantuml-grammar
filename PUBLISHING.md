# Publishing @knowvah/plantuml-grammar
Releases are automated with **semantic-release and npm trusted publishing (OIDC)**, the
same way as `@knowvah/dot-engine`: no long-lived npm token, and nobody runs `npm publish`
after the one-time bootstrap below. Every push to `main` runs
[`release.yml`](.github/workflows/release.yml); when the commits since the last `v*` tag
include a releasable one, it publishes to npm with provenance, pushes the `v<version>` tag,
creates the GitHub Release and mirrors the package to GitHub Packages.

## What gets published
The package is the npm workspace `packages/engine`. `prepack` builds the engine and copies
in, from the repository root, `LICENSE` and the committed `dist/` files; `postpack`
removes the copies.

| Import | File |
|---|---|
| `@knowvah/plantuml-grammar` | `dist/index.js` (types `dist/index.d.ts`): `loadEngine`, `Interpreter`, `accepts` |
| `@knowvah/plantuml-grammar/plantuml.tmLanguage.json` | the TextMate grammar (`source.plantuml`) |
| `@knowvah/plantuml-grammar/plantuml.engine.json` | the engine model (`engine_format` 1) |

The Node-only CLI and worker pool (`cli`, `pool`, `worker`) serve the parity harness and
are not published. `tests/package` packs the workspace, installs the tarball into a scratch
project and uses both artifacts from there; `npm test` runs it.

Before publishing, the release job rebuilds `dist/` from `model/` and fails if it differs
from the committed files, then runs `npm test`.

## Day-to-day releasing
The version comes from the commit messages (Conventional Commits). Pull requests are
merged with merge commits, so **every commit on the branch is analyzed**, not only the
pull request title:

| Commit | Release |
|---|---|
| `fix: ...`, any scope | patch, `1.2.3` to `1.2.4` |
| `feat: ...` | minor, `1.2.3` to `1.3.0` |
| `feat!: ...`, or a `BREAKING CHANGE:` footer | major, `1.2.3` to `2.0.0` |
| `docs:` `chore:` `ci:` `refactor:` `test:` `style:` `perf:` | none |

- A fix to CI or tooling only is `ci:` or `chore:`, not `fix(ci):`, which would publish a
  patch release with no change to the package.
- The public contracts are listed at the top of [CHANGELOG.md](CHANGELOG.md): the TextMate
  scope names, `engine_format`, and the engine API. Changing one is a breaking change and
  needs `!` or a `BREAKING CHANGE:` footer.
- `packages/engine/package.json` stays at `0.0.0-development`. The version lives in the
  tag, on npm and in the GitHub Release; nothing is committed back to `main`.

### CHANGELOG
`CHANGELOG.md` is kept by hand, because it records parity and model changes in more detail
than the generated release notes. A pull request adds its entries under `[Unreleased]`.
After a release, a `docs(changelog): ...` pull request renames `[Unreleased]` to the
released version and date (from the GitHub Release) and opens a new empty `[Unreleased]`.

## One-time bootstrap
A trusted publisher can only be added to a package that already exists on npm, so the
first publish is manual.

1. Log in to npm with an account in the `knowvah` npm organization: `npm login`. The
   account must have two-factor authentication enabled (npmjs.com, Account,
   Two-Factor Authentication); without it the registry rejects the publish with
   `E403 ... Two-factor authentication or granular access token with bypass 2fa
   enabled is required` and never asks for a code.
2. From the head of the pull request that adds the package, with its CI green, publish a
   placeholder version (`publishConfig.access` is already `public`; npm asks for the 2FA
   code):

   ```sh
   npm ci
   npm version 0.1.0 --no-git-tag-version -w packages/engine
   npm publish -w packages/engine
   git checkout -- packages/engine/package.json package-lock.json
   ```

3. Add the trusted publisher, as the same npm account (npm 11.15 or later; npm asks
   for 2FA):

   ```sh
   npm trust github @knowvah/plantuml-grammar --file release.yml \
     --repo knowvah/plantuml-grammar --env release --allow-publish
   npm trust list @knowvah/plantuml-grammar
   ```

   `--allow-publish` is required: semantic-release runs `npm publish`, and a trusted
   publisher allows only `npm stage publish` unless told otherwise. On the website the
   same form is under **Packages, @knowvah/plantuml-grammar, Settings, Trusted
   publishing, GitHub Actions** (Organization or user `knowvah`, Repository
   `plantuml-grammar`, Workflow filename `release.yml`, Environment name `release`,
   and allow `npm publish` under Allowed actions). npm does not check these values when
   they are saved, and a configuration expires if nothing is published through it
   within two days, so merge soon after this step.

4. Merge the pull request. There is no `v*` tag yet, so semantic-release cuts its first
   release, **1.0.0** (semantic-release always starts at 1.0.0), with provenance, and the
   tag, the GitHub Release and the GitHub Packages mirror follow.
5. Mark the placeholder:
   `npm deprecate @knowvah/plantuml-grammar@0.1.0 "bootstrap publish; use 1.0.0 or later"`.

If the pull request is merged before step 3, the release run fails before publishing
anything (no tag, no release). Finish step 3, then re-run it from the Actions tab (the
workflow has a manual trigger).

Optional: to approve each publish by hand, add required reviewers to the `release`
environment (repository Settings, Environments, `release`). It is created by the first
run.

## Removing a published version
- Within 72 hours: `npm unpublish @knowvah/plantuml-grammar@<version>`.
- A version number can never be reused; release a new one with a new releasable commit.
- After 72 hours: `npm deprecate @knowvah/plantuml-grammar@<version> "<message>"`.
