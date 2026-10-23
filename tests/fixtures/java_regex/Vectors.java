import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.regex.PatternSyntaxException;

/**
 * Reference verdicts for tools.model.java_regex (Java 21, single-file launch:
 * {@code java Vectors.java cases.tsv}).
 *
 * One input line per pattern: {@code mode TAB flag TAB pattern TAB s1,s2,...}.
 * {@code mode} is "line" (find of ^(?:pattern)$, the way Pattern2 commands match) or
 * "pattern" (matches()); {@code flag} is "i" (CASE_INSENSITIVE, as Pattern2.java:114) or
 * "-". Strings are code points in hex joined by ".", "-" is the empty string; the pattern
 * is hex the same way. One output line per input line: a 0/1 per string, or "E" when
 * the pattern does not compile.
 */
public class Vectors {
    private static String decode(String hex) {
        if (hex.equals("-")) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        for (String part : hex.split("\\.")) {
            sb.appendCodePoint(Integer.parseInt(part, 16));
        }
        return sb.toString();
    }

    private static String verdicts(String[] fields) {
        boolean line = fields[0].equals("line");
        int flags = fields[1].equals("i") ? Pattern.CASE_INSENSITIVE : 0;
        String re = decode(fields[2]);
        Pattern pattern;
        try {
            pattern = Pattern.compile(line ? "^(?:" + re + ")$" : re, flags);
        } catch (PatternSyntaxException e) {
            return "E";
        }
        StringBuilder out = new StringBuilder();
        for (String hex : fields[3].split(",", -1)) {
            Matcher m = pattern.matcher(decode(hex));
            out.append((line ? m.find() : m.matches()) ? '1' : '0');
        }
        return out.toString();
    }

    public static void main(String[] args) throws Exception {
        for (String row : Files.readAllLines(Path.of(args[0]))) {
            System.out.println(verdicts(row.split("\t", -1)));
        }
    }
}
