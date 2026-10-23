import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import net.sourceforge.plantuml.BlockUml;
import net.sourceforge.plantuml.FileSystem;
import net.sourceforge.plantuml.SourceStringReader;
import net.sourceforge.plantuml.TitledDiagram;
import net.sourceforge.plantuml.core.Diagram;
import net.sourceforge.plantuml.error.PSystemError;
import net.sourceforge.plantuml.preproc.Defines;
import net.sourceforge.plantuml.security.SFile;
import net.sourceforge.plantuml.text.StringLocated;

/**
 * Parity oracle: reads file paths on stdin, prints one JSON line per file.
 *
 * Sources cited at 97a5992 (net/sourceforge/plantuml/). Blocks come from
 * SourceStringReader.getBlocks() (SourceStringReader.java:268), i.e.
 * BlockUmlBuilder (BlockUmlBuilder.java:100-132), the same path the CLI takes.
 * Each block's diagram is classified as SyntaxChecker.checkSyntaxFair does
 * (syntax/SyntaxChecker.java:120-130): PSystemError is a reject, TitledDiagram
 * carries the diagram type. SyntaxChecker itself is not called: it inspects
 * only blocks.get(0) (:89) and checkSyntax pre-rejects any string that does
 * not start with "@startuml\n" or end with "@enduml" (:67, :73). Preprocessed
 * lines are BlockUml.getData() (BlockUml.java:214), directives included.
 *
 * Output per file: {"path":..,"blocks":[{index,start_keyword,accepted,
 * diagram_type,error_line,preproc}]} or {"path":..,"error":..}.
 * error_line is 1-based within the file text, whose YAML header is blanked.
 */
public final class Oracle {
    private static final String YAML_SEPARATOR = "---";
    private static final Pattern START = Pattern.compile("[@\\\\]start\\w*");

    private Oracle() {
    }

    public static void main(String[] args) throws Exception {
        final PrintStream out = new PrintStream(System.out, false, StandardCharsets.UTF_8);
        try (BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            String path;
            while ((path = in.readLine()) != null) {
                if (path.isEmpty())
                    continue;
                out.println(Verdicts.forFile(path));
                out.flush();
            }
        }
    }

    /** Blank a leading YAML front-matter header, keeping line numbers stable. */
    static String blankYamlHeader(String text) {
        final String[] lines = text.split("\n", -1);
        if (lines.length < 2 || !lines[0].stripTrailing().equals(YAML_SEPARATOR))
            return text;
        for (int i = 1; i < lines.length; i++) {
            if (lines[i].stripTrailing().equals(YAML_SEPARATOR)) {
                for (int j = 0; j <= i; j++)
                    lines[j] = "";
                return String.join("\n", lines);
            }
        }
        return text;
    }

    static final class Verdicts {
        private Verdicts() {
        }

        static String forFile(String path) {
            try {
                final File file = new File(path);
                final String text = blankYamlHeader(Files.readString(file.toPath(), StandardCharsets.UTF_8));
                // Mirror SourceFileReader (SourceFileReader.java:72,79): file-name defines and
                // !include/!import resolution relative to the source file's directory.
                FileSystem.getInstance().setCurrentDir(SFile.fromFile(file.getAbsoluteFile().getParentFile()));
                final List<BlockUml> blocks = new SourceStringReader(Defines.createWithFileName(file), text,
                        Collections.<String>emptyList()).getBlocks();
                final List<String> json = new ArrayList<>();
                for (int i = 0; i < blocks.size(); i++)
                    json.add(block(i, blocks.get(i)));
                return "{\"path\":" + Json.str(path) + ",\"blocks\":[" + String.join(",", json) + "]}";
            } catch (Throwable t) {
                return "{\"path\":" + Json.str(path) + ",\"error\":" + Json.str(t.toString()) + "}";
            }
        }

        private static String block(int index, BlockUml block) {
            final List<String> lines = new ArrayList<>();
            for (StringLocated s : block.getData())
                lines.add(Json.str(s.getString()));
            final Diagram diagram = block.getDiagram();
            boolean accepted = true;
            String type = "null";
            String errorLine = "null";
            if (diagram instanceof PSystemError) {
                accepted = false;
                errorLine = Integer.toString(((PSystemError) diagram).getLineLocation().getPosition() + 1);
            } else if (diagram instanceof TitledDiagram) {
                type = Json.str(((TitledDiagram) diagram).getDiagramType().name());
            }
            return "{\"index\":" + index + ",\"start_keyword\":" + Json.str(startKeyword(block))
                    + ",\"accepted\":" + accepted + ",\"diagram_type\":" + type + ",\"error_line\":" + errorLine
                    + ",\"preproc\":[" + String.join(",", lines) + "]}";
        }

        private static String startKeyword(BlockUml block) {
            if (block.getData().isEmpty())
                return "";
            final Matcher m = START.matcher(block.getData().get(0).getString());
            return m.find() ? m.group() : "";
        }
    }

    static final class Json {
        private Json() {
        }

        static String str(String s) {
            final StringBuilder sb = new StringBuilder("\"");
            for (int i = 0; i < s.length(); i++) {
                final char c = s.charAt(i);
                switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < 0x20)
                        sb.append(String.format("\\u%04x", (int) c));
                    else
                        sb.append(c);
                }
                }
            }
            return sb.append('"').toString();
        }
    }
}
