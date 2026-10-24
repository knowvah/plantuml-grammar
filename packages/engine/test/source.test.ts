import { describe, expect, it } from "vitest";
import {
  embeddedType,
  isEmbeddedEnd,
  isEndDirective,
  isStartDirective,
  readLine,
  splitBlock,
  splitBlocks,
  startKeyword,
  stripComments,
  trin,
  type Line,
} from "../src/source.js";

const EM_SPACE = " ";
const NBSP = " ";
const IDEOGRAPHIC_SPACE = "　";
const GRINNING = "\u{1F600}";

function lines(...texts: string[]): Line[] {
  return texts.map((text, i) => ({ number: i + 1, text, trimmed: trin(text) }));
}

function texts(kept: Line[]): string[] {
  return kept.map((ln) => ln.text);
}

describe("readLine", () => {
  it("drops one leading BOM and maps en dash to hyphen", () => {
    expect(readLine("﻿a–b–c")).toBe("a-b-c");
    expect(readLine("﻿﻿a")).toBe("﻿a");
    expect(readLine("a﻿")).toBe("a﻿");
  });
});

describe("trin", () => {
  it("strips control chars and spaces only", () => {
    expect(trin("\t \x01 a b \r")).toBe("a b");
    expect(trin(`${NBSP}a${NBSP}`)).toBe(`${NBSP}a${NBSP}`);
  });

  it("does not strip Unicode whitespace above U+0020", () => {
    expect(trin(`${EM_SPACE}\x1f a${NBSP}\x00`)).toBe(`${EM_SPACE}\x1f a${NBSP}`);
    expect(trin("﻿a")).toBe("﻿a");
  });

  it("strips U+0000 through U+0020 on both sides, including all-trimmed input", () => {
    expect(trin("\x00\x1f\x20a\x20\x1f\x00")).toBe("a");
    expect(trin("\x00 \t")).toBe("");
    expect(trin("")).toBe("");
  });

  it("leaves supplementary-plane characters intact", () => {
    expect(trin(`${GRINNING} a ${GRINNING}`)).toBe(`${GRINNING} a ${GRINNING}`);
    expect(trin(` ${GRINNING} `)).toBe(GRINNING);
  });
});

describe("isStartDirective", () => {
  it.each([
    ["@startuml", true],
    ["  \\startuml", true],
    ["@start", false],
    ["@startx", true],
    ["start uml", false],
    ["   ", false],
    ["@end", false],
    [`${EM_SPACE}@startuml`, true],
    [`${IDEOGRAPHIC_SPACE}@startuml`, true],
    ["\x1c@startuml", true],
    ["\x85@startuml", true],
    ["﻿@startuml", false],
    ["\x00@startuml", false],
    ["@startuml".toUpperCase(), false],
    [`@start${GRINNING}`, true],
  ])("%j -> %s", (text, expected) => {
    expect(isStartDirective(text)).toBe(expected);
  });
});

describe("isEndDirective", () => {
  it.each([
    ["@enduml", true],
    [" \\end", true],
    ["@start", false],
    ["end", false],
    ["", false],
    [`${EM_SPACE}@end`, true],
    ["@en", false],
  ])("%j -> %s", (text, expected) => {
    expect(isEndDirective(text)).toBe(expected);
  });
});

describe("startKeyword", () => {
  it("returns the lower-cased word after @start", () => {
    expect(startKeyword("@startMindmap")).toBe("mindmap");
    expect(startKeyword("@startuml name=a")).toBe("uml");
    expect(startKeyword("@startuml{x}")).toBe("uml");
    expect(startKeyword("plain")).toBe("");
  });

  it("stops at supplementary characters", () => {
    expect(startKeyword(`@start${GRINNING}uml`)).toBe("");
    expect(startKeyword(`@startuml${GRINNING}x`)).toBe("uml");
  });

  it("matches Python str.lower for non-ASCII letters that lower to ASCII", () => {
    expect(startKeyword("@startİx")).toBe("i");
    expect(startKeyword("@startKa")).toBe("ka");
    expect(startKeyword("@starté")).toBe("");
  });

  it("allows leading Unicode whitespace", () => {
    expect(startKeyword(`${EM_SPACE}@startjson`)).toBe("json");
  });
});

describe("embeddedType", () => {
  it.each([
    ["{{", "uml"],
    ["  {{  ", "uml"],
    ["{{json", "json"],
    ["{{ json", null],
    ["{{ nonsense", null],
    ["{{salt  ", "salt"],
    ["x {{", null],
    [`${EM_SPACE}{{${NBSP}`, "uml"],
    ["\x1c{{json\x85", "json"],
    ["﻿{{", null],
  ])("%j -> %s", (text, expected) => {
    expect(embeddedType(text)).toBe(expected);
  });
});

describe("isEmbeddedEnd", () => {
  it("accepts }} surrounded by Python whitespace only", () => {
    expect(isEmbeddedEnd("}}")).toBe(true);
    expect(isEmbeddedEnd(`${EM_SPACE}}}${IDEOGRAPHIC_SPACE}`)).toBe(true);
    expect(isEmbeddedEnd("}} x")).toBe(false);
    expect(isEmbeddedEnd("﻿}}")).toBe(false);
  });
});

describe("stripComments", () => {
  it("mirrors the read filter", () => {
    const src = lines(
      "keep1",
      "  ' line comment",
      "/' inline '/",
      "/' start",
      "inside",
      "end '/",
      "keep2",
      "/' x '/ trailing",
      "keep3",
    );
    // "/' x '/ trailing" starts with /' but neither ends with '/ nor lacks '/ -> kept.
    expect(texts(stripComments(src))).toEqual(["keep1", "keep2", "/' x '/ trailing", "keep3"]);
  });

  it("drops the rest after an unclosed long comment", () => {
    expect(texts(stripComments(lines("a", "/' open", "b", "c")))).toEqual(["a"]);
  });

  it("treats tabs as spaces when trimming", () => {
    expect(texts(stripComments(lines("\t' tabbed", "\t/' c '/\t", "k")))).toEqual(["k"]);
  });
});

describe("splitBlock", () => {
  it("numbers lines and stops at the end line", () => {
    const block = splitBlock("\n@startuml\nA\n\n@enduml\nB");
    expect(block.start).toEqual({ number: 2, text: "@startuml", trimmed: "@startuml" });
    expect(block.keyword).toBe("uml");
    expect(block.body.map((ln) => [ln.number, ln.text])).toEqual([
      [3, "A"],
      [4, ""],
    ]);
  });

  it("treats a block without a start line as all body", () => {
    const block = splitBlock("A\r\nB");
    expect(block.start).toBeNull();
    expect(block.keyword).toBeNull();
    expect(block.body.map((ln) => ln.text)).toEqual(["A", "B"]);
  });

  it("handles empty text", () => {
    const block = splitBlock("");
    expect(block.start).toBeNull();
    expect(block.body.map((ln) => ln.number)).toEqual([1]);
  });

  it("records the end line", () => {
    const block = splitBlock("@startuml\nA\n@endmindmap\nrest");
    expect(block.end).not.toBeNull();
    expect([block.end?.number, block.end?.text]).toEqual([3, "@endmindmap"]);
    expect(splitBlock("@startuml\nA").end).toBeNull();
  });

  it("splits on \\r\\n, \\r and \\n alike", () => {
    const block = splitBlock("x\r\ny\rz\n");
    expect(block.body).toEqual([
      { number: 1, text: "x", trimmed: "x" },
      { number: 2, text: "y", trimmed: "y" },
      { number: 3, text: "z", trimmed: "z" },
      { number: 4, text: "", trimmed: "" },
    ]);
  });

  it("applies BOM and en dash handling to each line", () => {
    const block = splitBlock("﻿@startuml\na–b");
    expect(block.start?.text).toBe("@startuml");
    expect(block.body.map((ln) => ln.text)).toEqual(["a-b"]);
  });

  it("finds a start line preceded by blank lines and Unicode whitespace", () => {
    const block = splitBlock(`\n  \n${EM_SPACE}@startjson\nx`);
    expect(block.start?.number).toBe(3);
    expect(block.keyword).toBe("json");
  });

  it("treats an all-blank block as body only", () => {
    const block = splitBlock("  \n\t");
    expect(block.start).toBeNull();
    expect(block.body).toHaveLength(2);
  });
});

describe("splitBlocks", () => {
  it("mirrors BlockUmlBuilder", () => {
    const text =
      "intro text\n@startuml\nA\n@startuml\nB\n@enduml\nbetween\n\\startdot x\nC\n\\enddot\n";
    expect(splitBlocks(text)).toEqual(["@startuml\nB\n@enduml", "\\startdot x\nC\n\\enddot"]);
  });

  it("drops unterminated blocks and non-directives", () => {
    expect(splitBlocks("@startuml\nA\n")).toEqual([]);
    expect(splitBlocks("@STARTUML\nA\n@ENDUML")).toEqual([]);
    expect(splitBlocks("@start\nA\n@end")).toEqual([]);
    expect(splitBlocks("@enduml\n@startmindmap\r\n* a\r\n@endwbs\r\n")).toEqual([
      "@startmindmap\n* a\n@endwbs",
    ]);
  });

  it("strips every trailing carriage return", () => {
    expect(splitBlocks("@startuml\r\r\nA\r\n@enduml\r\r\n")).toEqual(["@startuml\nA\n@enduml"]);
  });
});
