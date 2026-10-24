# Parity: plantuml-ts

Pin: `97a5992201a7b1bc5d4063a81da609fe7387fede`

| family | blocks | fr | fa | timeout | diagram_mismatch | raw_fr | FR rate |
|---|---|---|---|---|---|---|---|
| activity-legacy | 119 | 0 | 0 | 0 | 1 | 0 | 0.00% |
| activity3 | 777 | 0 | 2 | 0 | 1 | 33 | 0.00% |
| class | 1166 | 0 | 14 | 0 | 25 | 30 | 0.00% |
| description | 662 | 0 | 6 | 0 | 0 | 58 | 0.00% |
| sequence | 1223 | 0 | 3 | 0 | 0 | 52 | 0.00% |
| single-line | 3 | 0 | 0 | 0 | 2 | 0 | 0.00% |
| state | 300 | 0 | 4 | 0 | 0 | 3 | 0.00% |
| timing | 65 | 0 | 3 | 0 | 0 | 0 | 0.00% |
| unclassified | 86 | 0 | 0 | 0 | 0 | 0 | 0.00% |
| **total** | 4401 | 0 | 32 | 0 | 29 | 176 | 0.00% |

## Cases

- activity3: `class/duluve-89-mati167.puml#0` fa (semantic) - unknown arrow color `-[#toto]->`: NoSuchColorException at execution (gap/arrow-unknown-color)
- activity3: `class/leseku-63-ruda113.puml#0` fa (semantic) - unknown stereotype color `<<#zzblue>>`: NoSuchColorException at execution (gap/activity-unknown-color)
- class: `class/dulone-62-neri182.puml#0` fa (semantic) - map CapitalCity defined twice: "Map already exists"
- class: `class/fegafi-82-xiri255.puml#0` fa (semantic) - class X.Encoding made X a package; `class X` then fails: "Bad name"
- class: `class/foxufo-19-nuco936.puml#0` fa (semantic) - package Order exists, `class Order` fails: "Bad name"
- class: `class/jicogu-02-cani636.puml#0` fa (semantic) - Order exists as a package; class Order {...} cannot mute it: "Cannot create Order because it already exists"
- class: `class/luzive-62-zote562.puml#0` fa (semantic) - `<> StationCrossing` reuses a class name: "Already existing"
- class: `class/notevi-43-sita948.puml#0` fa (semantic) - Order exists as a package; class Order {...}: "Cannot create Order because it already exists"
- class: `class/pedoze-30-xoxo765.puml#0` fa (semantic) - class X then class X.Encoding: "Bad hierarchy for class"
- class: `class/petiku-70-fogu777.puml#0` fa (semantic) - bar created by a link, `struct bar {` cannot mute it: "Cannot create bar because it already exists"
- class: `class/pizegi-06-jiro383.puml#0` fa (semantic) - lollipop link to a class that does not exist: "No class"
- class: `class/revosa-68-goci965.puml#0` fa (semantic) - b is a class, so `b.b` in a link cannot resolve it as a package: "Not a package"
- class: `class/rogoxa-80-mori838.puml#0` fa (semantic) - package Toto exists, `class Toto` fails: "Bad name"
- class: `class/sunuli-13-geju490.puml#0` fa (semantic) - class com.Toto then class com.Toto.Internal: "Bad hierarchy for class"
- class: `class/xadepe-11-noja686.puml#0` fa (semantic) - Toto is a class, `class Toto.Internal` needs it as a package: "Not a package"
- class: `object/losote-76-beki147.puml#0` fa (semantic) - object user defined twice: "Object already exists"
- description: `class/gikaju-64-bari602.puml#0` fa (semantic) - C4 Rel() links someContainer before `rectangle ... as someContainer` declares it: "This element (someContainer) is already defined" (the link made it STILL_UNKNOWN)
- description: `class/mucajo-31-lifo004.puml#0` fa (semantic) - Provider is a group after `component [Provider] {`; the later `[Provider]` fails: "This element (Provider) is already defined"
- description: `class/nixuje-20-bobu879.puml#0` fa (semantic) - `sprite ... jar:archimate/strategy-value-stream` names no internal sprite: "No such internal sprite" (runtime resource table)
- description: `class/xexuza-21-kifa053.puml#0` fa (semantic) - `note left of compo` before compo exists: "Not known: compo"
- description: `component/sabafe-32-viju467.puml#0` fa (semantic) - a second `note as _n` (in another package) reuses the existing note code: "Note already created: _n"
- description: `usecase/nekote-79-pori818.puml#0` fa (semantic) - `usecase sameid` then `rectangle sameid`: "This element (sameid) is already defined"
- sequence: `sequence/moragi-03-luto111.puml#0` fa (semantic) - preprocessor error: %dirpath() has arity 0, called with one argument; not a sequence command
- sequence: `sequence/riguga-63-mujo058.puml#0` fa (semantic) - create then a message to another participant: SequenceDiagram.addMessage pendingCreate check (state, gap/create-then-other-message)
- sequence: `sequence/sosudi-70-jape391.puml#0` fa (semantic) - activate/deactivate just after a delay: SequenceDiagram.activate lastDelay check (state, gap/activate-after-delay)
- state: `class/fugedo-34-fice721.puml#0` fa (semantic) - link endpoint ChildMode1.A resolves under the current group, whose parent state does not exist (cross-line, gap/link-unknown-parent)
- state: `class/xacona-99-peze211.puml#0` fa (semantic) - link endpoint pUndetected belongs to a concurrent region and is used outside it (cross-line, gap/state-reused-in-other-region)
- state: `class/zecivu-62-pagu681.puml#0` fa (semantic) - link endpoint XA13 is declared later inside a concurrent region; links run in pass TWO and cannot use it at the root (cross-line)
- state: `sequence/cagego-53-vemo516.puml#0` fa (semantic) - link endpoint c belongs to another concurrent region (cross-line, gap/state-reused-in-other-region)
- timing: `class/sezuvo-55-nose464.puml#0` fa (semantic) - constraint on an undeclared player: CommandConstraint looks PART1 up in the player table (gap/constraint-unknown-player)
- timing: `class/tobafo-52-libo419.puml#0` fa (semantic) - constraint to an undefined time label: TimeTickBuilder resolves :code in the label table, null fails (gap/constraint-unknown-label)
- timing: `sequence/pebecu-20-deci596.puml#0` fa (semantic) - message to an undeclared player: CommandTimeMessage looks PART2 up in the player table (gap/message-unknown-player)
