"""Which upstream factories are ``PSystemCommandFactory`` subclasses.

Only command factories run ``PSystemCommandFactory``'s command loop, whose multiline
scan glues a ``{{ ... }}`` embedded diagram into one unit
(``command/PSystemCommandFactory.java:288-307``). The factories below extend
``PSystemAbstractFactory`` (JSON, YAML, HCL, files, git), ``PSystemSingleLineFactory``,
``PSystemBasicFactory`` or implement ``PSystemFactory`` directly (welcome), and read their
source as plain lines (``jsondiagram/StyleExtractor.java:63-103``,
``filesdiagram/FilesDiagramFactory.java:54-58``), so a ``{{`` line is an ordinary line to
them. The set is every extracted factory whose superclass chain at 97a5992 does not
contain ``PSystemCommandFactory`` (checked by ``tests/interp/test_factories.py``).
"""

from __future__ import annotations

NON_COMMAND_FACTORIES: frozenset[str] = frozenset(
    {
        "FilesDiagramFactory",
        "GitDiagramFactory",
        "HclDiagramFactory",
        "JsonDiagramFactory",
        "YamlDiagramFactory",
        "PSystemAppleTwoFactory",
        "PSystemCharlieFactory",
        "PSystemColorsFactory",
        "PSystemCreoleFactory",
        "PSystemDedicationFactory",
        "PSystemDefinitionFactory",
        "PSystemDitaaFactory",
        "PSystemDonorsFactory",
        "PSystemDotFactory",
        "PSystemEggFactory",
        "PSystemLatexFactory",
        "PSystemLicenseFactory",
        "PSystemListArchimateSpritesFactory",
        "PSystemListEmojiFactory",
        "PSystemListFontsFactory",
        "PSystemListOpenIconicFactory",
        "PSystemMathFactory",
        "PSystemOpenIconicFactory",
        "PSystemRIPFactory",
        "PSystemSkinparameterListFactory",
        "PSystemSudokuFactory",
        "PSystemVersionFactory",
        "PSystemWelcomeFactory",
    }
)
