import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import net.sourceforge.plantuml.regex.IRegex;
import net.sourceforge.plantuml.regex.Pattern2;
import net.sourceforge.plantuml.regex.RegexConcat;
import net.sourceforge.plantuml.regex.RegexLeaf;
import net.sourceforge.plantuml.regex.RegexOptional;
import net.sourceforge.plantuml.regex.RegexOr;
import net.sourceforge.plantuml.regex.RegexRepeatedOneOrMore;
import net.sourceforge.plantuml.regex.RegexRepeatedZeroOrMore;

/**
 * IRegex tree to I1 Node. Upstream: regex/RegexComposed.java:54 ({@code partials}),
 * regex/RegexLeaf.java:53 ({@code pattern}), regex/RegexOr.java:46 and
 * regex/RegexRepeatedOneOrMore.java:46 ({@code name}). Leaf patterns stay raw: the {@code %}-macros
 * of regex/Pattern2.java:54-59 are not expanded here.
 *
 * <p>A bare {@link Pattern2} or {@link Pattern} (multiline end patterns, factory constants) becomes
 * a single unnamed leaf.
 */
final class IRegexWalker implements NodeWalker {
    private static final String COMPOSED_PARTIALS = "partials";
    private static final String NAME = "name";

    @Override
    public boolean supports(Object regex) {
        return regex instanceof IRegex || regex instanceof Pattern2 || regex instanceof Pattern;
    }

    @Override
    public Map<String, Object> walk(Object regex) {
        if (regex instanceof RegexLeaf leaf) {
            return node("leaf", leaf.getName(), leaf.getPatternAsString(), List.of());
        }
        if (regex instanceof Pattern2 p) {
            return node("leaf", null, p.pattern(), List.of());
        }
        if (regex instanceof Pattern p) {
            return node("leaf", null, p.pattern(), List.of());
        }
        String type = composedType(regex);
        if (type == null) {
            throw new NodeWalker.Unwalkable("unknown-iregex:" + regex.getClass().getName());
        }
        return node(type, composedName(regex), null, children(regex));
    }

    private static String composedType(Object regex) {
        if (regex instanceof RegexConcat) {
            return "concat";
        }
        if (regex instanceof RegexOr) {
            return "or";
        }
        if (regex instanceof RegexOptional) {
            return "opt";
        }
        if (regex instanceof RegexRepeatedZeroOrMore) {
            return "star";
        }
        if (regex instanceof RegexRepeatedOneOrMore) {
            return "plus";
        }
        return null;
    }

    private static String composedName(Object regex) {
        if (regex instanceof RegexOr || regex instanceof RegexRepeatedOneOrMore) {
            return (String) Refl.field(regex, NAME);
        }
        return null;
    }

    private List<Object> children(Object regex) {
        List<Object> out = new ArrayList<>();
        for (Object part : (List<?>) Refl.field(regex, COMPOSED_PARTIALS)) {
            out.add(walk(part));
        }
        return out;
    }

    static Map<String, Object> node(String type, String name, String pattern, List<Object> children) {
        Map<String, Object> n = new LinkedHashMap<>();
        n.put("t", type);
        n.put("name", name);
        n.put("pattern", pattern);
        n.put("children", children);
        return n;
    }
}

/** Reflection helpers shared by the extractor classes. */
final class Refl {
    private Refl() {}

    /** Value of the first field called {@code name} found walking up from the object's class. */
    static Object field(Object target, String name) {
        return field(target, target.getClass(), name);
    }

    /** Value of field {@code name}, searching from {@code start} up its superclasses. */
    static Object field(Object target, Class<?> start, String name) {
        for (Class<?> c = start; c != null; c = c.getSuperclass()) {
            try {
                Field f = c.getDeclaredField(name);
                f.setAccessible(true);
                return f.get(target);
            } catch (NoSuchFieldException e) {
                continue;
            } catch (IllegalAccessException e) {
                throw new IllegalStateException(e);
            }
        }
        throw new IllegalStateException("no field " + name + " on " + target.getClass().getName());
    }
}
