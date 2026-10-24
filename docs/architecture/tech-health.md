# Tech health

Checked 2026-10-23. Sources:
- EOL dates: endoflife.date API (`nodejs`, `python`, `eclipse-temurin`).
- Advisories: OSV (`api.osv.dev` querybatch, then vuln details). A query uses the version
  resolved in the lockfile when one exists, and otherwise the declared floor.

"Local" rows describe the toolchain installed on this workstation, not what the repos
declare. They are listed because the gates in plantuml-grammar run on it.

| Repo | Component | Version | EOL Date | CVEs (High+) | Action |
|------|-----------|---------|----------|--------------|--------|
| plantuml-grammar | Python (declared) | >=3.11 | 3.11: 2027-10-31 | — | OK |
| plantuml-grammar | Python (local) | 3.13.5 | 2029-10-31 | not checked per patch | Update available (3.13.17) |
| plantuml-grammar | JDK (declared) | 21 | Temurin 21: 2029-12-31 | — | OK |
| plantuml-grammar | JDK (local) | 21.0.1 | 2029-12-31 | Not enumerated; 21.0.1 is 12 quarterly updates behind | Update available (21.0.13) |
| plantuml-grammar | Node (declared) | unpinned | — | — | OK (consider pinning, see findings) |
| plantuml-grammar | Node (local) | 25.2.1 | **2026-06-01 (passed)** | — | EOL — upgrade required |
| plantuml-grammar | PlantUML pin | 1.2026.8beta1 (97a5992) | rolling | none in OSV (Maven `net.sourceforge.plantuml:plantuml`) | Update available (1.2026.9 released; brew has it) |
| plantuml-grammar | pyyaml / jsonschema / regex | 6.0.3 / 4.26.0 / 2026.9.29 | — | none | OK |
| plantuml-grammar | pcre2 (dev) | 0.7.1 | — | OSV matches CVE-2025-58050 (CVSS 3.1 vector C:H/A:H; open-ended range). Not affected: the wheel bundles libpcre2 10.47, and the fix landed in 10.46. | OK (false positive) |
| plantuml-grammar | vscode-textmate / vscode-oniguruma (dev) | 9.3.2 / 2.0.1 | — | none | OK |
| plantuml-ts | Node | >=26 (volta 26.9.0) | 2029-04-30 (LTS from 2026-10-28) | — | Update available (26.12.1) |
| plantuml-ts | TypeScript / Vite | 6.0.3 / 8.3.4 | — | none | OK |
| plantuml-ts | vite nested under vitepress override (docs-site, dev) | 7.3.6 | — | GHSA-587h-7wmj-h5pm / CVE-2026-112942 (HIGH; launch-editor, Windows), plus 3 moderate/low (GHSA-698v-4r3x-3vcv, GHSA-r825-w8mm-5pxw, GHSA-rq7h-c2jc-7f22, GHSA-9jrq-w75r-8gcw) | CVE — patch required (vite 7.3.7) |
| plantuml-ts | @knowvah/dot-engine / elkjs / katex / pako / @xmldom/xmldom | 2.4.0 / 0.12.0 / 0.19.0 / 3.0.2 / 0.9.12 | — | none | OK |
| plantuml-plugins | Node | >=22 | 2027-04-30 | — | OK |
| plantuml-plugins | vite (dev, pnpm lock) | 8.3.0 | — | GHSA-587h-7wmj-h5pm / CVE-2026-112942 (HIGH), plus GHSA-vfpm-58rq-9qcg, GHSA-rq7h-c2jc-7f22, GHSA-698v-4r3x-3vcv, GHSA-r825-w8mm-5pxw, GHSA-9jrq-w75r-8gcw | CVE — patch required (vite 8.3.3) |
| plantuml-plugins | markdown-it (dev; consumers bring their own, peer >=14) | 15.0.2 | — | GHSA-gfr2-rv44-r23c / CVE-2026-111758 (HIGH, CVSS 3.1 7.5: quadratic-time DoS), plus GHSA-vfgh-jcmw-g37q (LOW) | CVE — patch required (15.0.3; raise peer floor to >=14.3.3) |
| plantuml-plugins | TypeScript / tsup / vitest / esbuild | 5.9.3 / 8.5.1 / 4.1.11 / 0.28.2 | — | none | OK (one major behind plantuml-ts's TS 6 / Vitest 5) |
| plantuml-plugins | VS Code engine / JetBrains platform | ^1.125.0 / 2025.2 | — | not checked | OK |

## Findings
- **The plantuml-plugins engine link is broken.** `packages/core/package.json` declares
  `link:../../../../plantuml-ts`. That resolves to `~/git/plantuml-ts`, which does not
  exist; the checkout is at `~/git/knowvah/plantuml-ts`. The installed symlink
  `packages/core/node_modules/@knowvah/plantuml-ts` points there and is dangling. The same
  repo's README tells users to clone `github.com/sseely/plantuml-ts`, not the knowvah org
  repo.
- **plantuml-grammar's defaults assume a fixed directory layout.** `PLANTUML_JAR` and
  `CORPUS_PLANTUML_TS` default to paths inside `~/git/knowvah/plantuml-ts`. A rebuild of the
  plantuml-ts oracle, or a move of the repo, silently changes or breaks the parity inputs.
  The pinned SHA in the jar file name guards the jar, but the corpus has no such guard.
- **Node is not pinned in plantuml-grammar.** `package.json` has no `engines` field and
  there is no `.nvmrc`. The local Node 25 is past EOL. Node 24 or 26 LTS would match
  plantuml-plugins (>=22) and plantuml-ts (>=26).
- **No known vulnerability reaches plantuml-grammar's own dependencies.** Every High+
  advisory above is in dev or docs tooling (the Vite dev server, markdown-it in the
  plugins' test and peer surface), not in shipped runtime code.

Confidence:
- HIGH for the EOL dates and the OSV results, which were retrieved in this run.
- UNKNOWN for which JDK 21.0.1 CVEs apply, which were not enumerated. The local JVM only
  runs the trusted pinned jar.
