import java.util.List;
import java.util.Map;

/**
 * Minimal deterministic JSON writer (no dependencies).
 *
 * <p>Maps keep their iteration order (use LinkedHashMap). A container whose compact form fits
 * within {@link #MAX_INLINE} characters is written on one line; larger ones are indented by two
 * spaces per level. Output always ends with a newline.
 */
final class Json {
    static final int MAX_INLINE = 100;
    private static final String INDENT = "  ";
    private static final int FIRST_PRINTABLE = 0x20;

    private Json() {}

    static String write(Object value) {
        StringBuilder sb = new StringBuilder();
        pretty(sb, value, 0);
        return sb.append('\n').toString();
    }

    static String compact(Object value) {
        if (value instanceof Map<?, ?> map) {
            return joinMap(map);
        }
        if (value instanceof List<?> list) {
            return joinList(list);
        }
        return scalar(value);
    }

    private static String joinMap(Map<?, ?> map) {
        StringBuilder sb = new StringBuilder("{");
        String sep = "";
        for (Map.Entry<?, ?> e : map.entrySet()) {
            sb.append(sep).append(quote(String.valueOf(e.getKey()))).append(": ").append(compact(e.getValue()));
            sep = ", ";
        }
        return sb.append('}').toString();
    }

    private static String joinList(List<?> list) {
        StringBuilder sb = new StringBuilder("[");
        String sep = "";
        for (Object item : list) {
            sb.append(sep).append(compact(item));
            sep = ", ";
        }
        return sb.append(']').toString();
    }

    private static void pretty(StringBuilder sb, Object value, int depth) {
        String flat = compact(value);
        boolean container = value instanceof Map<?, ?> || value instanceof List<?>;
        if (!container || flat.length() + depth * INDENT.length() <= MAX_INLINE) {
            sb.append(flat);
        } else if (value instanceof Map<?, ?> map) {
            prettyMap(sb, map, depth);
        } else {
            prettyList(sb, (List<?>) value, depth);
        }
    }

    private static void prettyMap(StringBuilder sb, Map<?, ?> map, int depth) {
        sb.append("{\n");
        String sep = "";
        for (Map.Entry<?, ?> e : map.entrySet()) {
            sb.append(sep).append(INDENT.repeat(depth + 1)).append(quote(String.valueOf(e.getKey()))).append(": ");
            pretty(sb, e.getValue(), depth + 1);
            sep = ",\n";
        }
        sb.append('\n').append(INDENT.repeat(depth)).append('}');
    }

    private static void prettyList(StringBuilder sb, List<?> list, int depth) {
        sb.append("[\n");
        String sep = "";
        for (Object item : list) {
            sb.append(sep).append(INDENT.repeat(depth + 1));
            pretty(sb, item, depth + 1);
            sep = ",\n";
        }
        sb.append('\n').append(INDENT.repeat(depth)).append(']');
    }

    private static String scalar(Object value) {
        if (value == null) {
            return "null";
        }
        if (value instanceof Number || value instanceof Boolean) {
            return value.toString();
        }
        return quote(value.toString());
    }

    static String quote(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < FIRST_PRINTABLE) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        return sb.append('"').toString();
    }
}
