import com.plantuml.ubrex.UnicodeBracketedExpression;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import net.sourceforge.plantuml.Lazy;
import net.sourceforge.plantuml.PSystemBuilder;
import net.sourceforge.plantuml.command.CommandDecoratorMultine;
import net.sourceforge.plantuml.command.PSystemCommandFactory;
import net.sourceforge.plantuml.command.SingleLineCommand2;
import net.sourceforge.plantuml.command.UBrexSingleLineCommand2;
import net.sourceforge.plantuml.regex.IRegex;
import net.sourceforge.plantuml.regex.Pattern2;

/**
 * Dumps every factory registered in {@code PSystemBuilder} (I1 raw extraction), one JSON file per
 * factory, into the output directory given as the first argument.
 *
 * <p>Usage: {@code java -Dpin.sha=... -Dpin.version=... -cp <jar>:<classes> Extract <outDir>}.
 * One JSON summary line is printed to stderr at the end.
 *
 * <p>Fields read per command base class (all at 97a5992, prefix
 * net/sourceforge/plantuml/command/): SingleLineCommand2.java:53 {@code pattern};
 * CommandMultilines.java:45-46 {@code starting}/{@code ending}; CommandMultilines2.java:51,57
 * {@code starting}/{@code end} (Lazy); CommandMultilines3.java:47,53 {@code starting}/{@code
 * patternEnd}; CommandMultilinesBracket.java:46 {@code starting}; UBrexSingleLineCommand2.java:55; {@code doTrim} of both single-line bases (SingleLineCommand2.java:54,
 * UBrexSingleLineCommand2.java:56);
 * UBrexCommandMultilines2.java:50,56; CommandDecoratorMultine.java:44 wraps a SingleLineCommand2
 * ({@code cmd}) and is emitted as a multiline whose start is that pattern. Factory order:
 * PSystemBuilder.java:133-200 (read from the private {@code factories} list, so conditional
 * registrations such as PSystemPathFactory follow the default security profile).
 */
public final class Extract {
    static final String ENGINE_IREGEX = "IRegex";
    static final String ENGINE_UBREX = "UBrex";
    static final String REASON_UBREX_PENDING = "ubrex-pending";

    private static final String PROP_SHA = "pin.sha";
    private static final String PROP_VERSION = "pin.version";
    private static final String KIND_SINGLE = "single";
    private static final String KIND_MULTILINE = "multiline";
    private static final String KIND_BRACKET = "multiline-bracket";
    private static final String KIND_OPAQUE = "opaque";
    private static final String CLASS = "class";
    private static final String START = "start";
    private static final String END = "end";
    private static final String NATURAL_GANTT = "NaturalGanttCommand";
    private static final String DECORATOR = "CommandDecoratorMultine";
    private static final String DO_TRIM = "doTrim";

    /**
     * Engine dispatch registry: first walker whose {@code supports} returns true wins. T03 adds
     * the UBrex walker with ONE line, placed BEFORE the pending fallback:
     * {@code WALKERS.add(new UBrexWalker());}
     */
    static final List<NodeWalker> WALKERS = new ArrayList<>();

    static {
        WALKERS.add(new IRegexWalker());
        WALKERS.add(new UBrexWalker()); // T03 hook
        WALKERS.add(new UBrexPendingWalker());
    }

    /** Where a command class keeps its regexes: kind, engine, start field, end field (or null). */
    private record Spec(String kind, String engine, String startField, String endField) {}

    private static final Map<String, Spec> SPECS = new LinkedHashMap<>();

    static {
        SPECS.put("SingleLineCommand2", new Spec(KIND_SINGLE, ENGINE_IREGEX, "pattern", null));
        SPECS.put("UBrexSingleLineCommand2", new Spec(KIND_SINGLE, ENGINE_UBREX, "pattern", null));
        SPECS.put("CommandMultilines", new Spec(KIND_MULTILINE, ENGINE_IREGEX, "starting", "ending"));
        SPECS.put("CommandMultilines2", new Spec(KIND_MULTILINE, ENGINE_IREGEX, "starting", "end"));
        SPECS.put("CommandMultilines3", new Spec(KIND_MULTILINE, ENGINE_IREGEX, "starting", "patternEnd"));
        SPECS.put("CommandMultilinesBracket", new Spec(KIND_BRACKET, ENGINE_IREGEX, "starting", null));
        SPECS.put("UBrexCommandMultilines2", new Spec(KIND_MULTILINE, ENGINE_UBREX, "starting", "end"));
        SPECS.put(DECORATOR, new Spec(KIND_MULTILINE, ENGINE_IREGEX, "cmd", null));
        // Gantt sentence command: grammar lives in the Subject/VerbPhrase UBrex objects (T03).
        SPECS.put(NATURAL_GANTT, new Spec(KIND_SINGLE, ENGINE_UBREX, null, null));
    }

    private Extract() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            throw new IllegalArgumentException("usage: Extract <outDir>");
        }
        Path outDir = Path.of(args[0]);
        Files.createDirectories(outDir);
        Map<String, Object> pin = new LinkedHashMap<>();
        pin.put("sha", requiredProperty(PROP_SHA));
        pin.put("version", requiredProperty(PROP_VERSION));

        List<?> factories = factories();
        Map<String, Object> commandCounts = new LinkedHashMap<>();
        int unreachableTotal = 0;
        for (int order = 0; order < factories.size(); order++) {
            Object factory = factories.get(order);
            Map<String, Object> doc = factoryDoc(pin, factory, order);
            String name = factory.getClass().getSimpleName();
            Files.writeString(outDir.resolve(name + ".json"), Json.write(doc), StandardCharsets.UTF_8);
            commandCounts.put(name, ((List<?>) doc.get("commands")).size());
            unreachableTotal += ((List<?>) doc.get("unreachable")).size();
        }
        GanttLangDump.main(new String[] {outDir.toString()}); // T03: extracted/gantt-lang.json
        System.err.println(Json.compact(summary(factories.size(), commandCounts, unreachableTotal)));
    }

    private static Map<String, Object> summary(int factories, Map<String, Object> counts, int unreachable) {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("factories", factories);
        s.put("commands", counts);
        s.put("commandsTotal", counts.values().stream().mapToInt(v -> (Integer) v).sum());
        s.put("unreachable", unreachable);
        return s;
    }

    private static String requiredProperty(String key) {
        String v = System.getProperty(key);
        if (v == null || v.isEmpty()) {
            throw new IllegalStateException("missing -D" + key);
        }
        return v;
    }

    private static List<?> factories() throws ReflectiveOperationException {
        Object builder = PSystemBuilder.getInstance();
        return (List<?>) Refl.field(builder, "factories");
    }

    static Map<String, Object> factoryDoc(Map<String, Object> pin, Object factory, int order)
            throws ReflectiveOperationException {
        List<Object> commands = new ArrayList<>();
        List<Object> unreachable = new ArrayList<>();
        if (factory instanceof PSystemCommandFactory pcf) {
            commandEntries(pcf, commands, unreachable);
        } else {
            opaqueEntries(factory, commands, unreachable);
        }
        Map<String, Object> doc = new LinkedHashMap<>();
        doc.put("pin", pin);
        doc.put("factory", factory.getClass().getSimpleName());
        doc.put("factoryOrder", order);
        doc.put("diagramType", diagramType(factory));
        doc.put("commands", commands);
        doc.put("unreachable", unreachable);
        return doc;
    }

    private static String diagramType(Object factory) throws ReflectiveOperationException {
        Method m = factory.getClass().getMethod("getDiagramType");
        return String.valueOf(m.invoke(factory));
    }

    // ---- command factories -------------------------------------------------------------

    private static void commandEntries(PSystemCommandFactory factory, List<Object> commands, List<Object> unreachable)
            throws ReflectiveOperationException {
        Method init = PSystemCommandFactory.class.getDeclaredMethod("initCommandsList", List.class);
        init.setAccessible(true);
        List<Object> cmds = new ArrayList<>();
        init.invoke(factory, cmds);
        for (int i = 0; i < cmds.size(); i++) {
            commands.add(commandEntry(i, cmds.get(i), unreachable));
        }
    }

    private static Map<String, Object> commandEntry(int order, Object cmd, List<Object> unreachable)
            throws ReflectiveOperationException {
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("order", order);
        e.put(CLASS, cmd.getClass().getName());
        Found found = specFor(cmd);
        if (found == null) {
            e.put("kind", KIND_OPAQUE);
            e.put("engine", null);
            e.put(START, null);
            e.put(END, null);
            unreachable.add(unreachable(order, cmd, "no-regex-source"));
            return e;
        }
        Spec spec = found.spec();
        e.put("kind", spec.kind());
        e.put("engine", spec.engine());
        e.put(START, walk(startRegex(cmd, found), order, cmd, unreachable));
        e.put(END, spec.endField() == null ? null : walk(field(cmd, found.owner(), spec.endField()), order, cmd, unreachable));
        e.put("finalBracket", finalBracket(cmd));
        if (cmd instanceof SingleLineCommand2<?> || cmd instanceof UBrexSingleLineCommand2<?>) {
            e.put(DO_TRIM, doTrim(cmd));
        }
        if (cmd instanceof CommandDecoratorMultine<?> d) {
            e.put("wrapper", DECORATOR);
            e.put("nbMaxLines", d.getNbMaxLines());
        }
        return e;
    }

    /** A matched {@link Spec} and the class that declares its fields. */
    private record Found(Class<?> owner, Spec spec) {}

    /** The first class walking up from the command that has a {@link #SPECS} entry. */
    private static Found specFor(Object cmd) {
        for (Class<?> c = cmd.getClass(); c != null; c = c.getSuperclass()) {
            Spec s = SPECS.get(c.getSimpleName());
            if (s != null) {
                return new Found(c, s);
            }
        }
        return null;
    }

    /**
     * Reads the declaring class's field, never a same-named field of a subclass (e.g. the static
     * {@code pattern} constant in gantt commands).
     */
    private static Object field(Object cmd, Class<?> owner, String name) {
        return resolve(Refl.field(cmd, owner, name));
    }

    private static Object startRegex(Object cmd, Found found) {
        String name = found.spec().startField();
        if (name == null) {
            return new UBrexPendingWalker.Marker();
        }
        Object value = field(cmd, found.owner(), name);
        if (value instanceof SingleLineCommand2<?> inner) {
            return field(inner, SingleLineCommand2.class, "pattern");
        }
        return value;
    }

    /** Unwraps {@code Lazy<T>}; other values pass through. */
    private static Object resolve(Object value) {
        return value instanceof Lazy<?> lazy ? lazy.get() : value;
    }

    /**
     * The {@code doTrim} flag of a single-line command: false means the pattern is matched against
     * the untrimmed line (SingleLineCommand2.java:76-81, :93, :102; UBrexSingleLineCommand2.java
     * has the same field). Read from the declaring class, never by name alone.
     */
    private static boolean doTrim(Object cmd) {
        Class<?> owner = cmd instanceof SingleLineCommand2<?> ? SingleLineCommand2.class : UBrexSingleLineCommand2.class;
        return (Boolean) Refl.field(cmd, owner, DO_TRIM);
    }

    private static boolean finalBracket(Object cmd) throws ReflectiveOperationException {
        try {
            return (Boolean) cmd.getClass().getMethod("syntaxWithFinalBracket").invoke(cmd);
        } catch (NoSuchMethodException e) {
            return false;
        }
    }

    private static Object walk(Object regex, int order, Object cmd, List<Object> unreachable) {
        try {
            for (NodeWalker w : WALKERS) {
                if (w.supports(regex)) {
                    return w.walk(regex);
                }
            }
            throw new NodeWalker.Unwalkable("no-walker:" + regex.getClass().getName());
        } catch (NodeWalker.Unwalkable u) {
            Map<String, Object> entry = unreachable(order, cmd, u.getMessage());
            if (!unreachable.contains(entry)) {
                unreachable.add(entry);
            }
            return null;
        }
    }

    private static Map<String, Object> unreachable(int order, Object cmd, String reason) {
        Map<String, Object> u = new LinkedHashMap<>();
        u.put(CLASS, cmd.getClass().getName());
        u.put("order", order);
        u.put("reason", reason);
        return u;
    }

    // ---- non-command factories ---------------------------------------------------------

    /**
     * Opaque factories: every static {@code Pattern2}/{@code Pattern}/{@code IRegex} constant
     * declared on the factory class becomes an opaque entry named after the field (sorted by field
     * name for determinism). Without any, the factory accepts lines by hard-coded Java and is
     * reported unreachable.
     */
    private static void opaqueEntries(Object factory, List<Object> commands, List<Object> unreachable)
            throws ReflectiveOperationException {
        List<Field> fields = new ArrayList<>();
        for (Field f : factory.getClass().getDeclaredFields()) {
            boolean regex = IRegex.class.isAssignableFrom(f.getType())
                    || f.getType() == Pattern2.class
                    || f.getType() == Pattern.class;
            if (regex && Modifier.isStatic(f.getModifiers())) {
                fields.add(f);
            }
        }
        fields.sort(Comparator.comparing(Field::getName));
        if (fields.isEmpty()) {
            unreachable.add(unreachable(0, factory, "opaque-no-regex-field"));
            return;
        }
        IRegexWalker walker = new IRegexWalker();
        for (int i = 0; i < fields.size(); i++) {
            Field f = fields.get(i);
            f.setAccessible(true);
            Map<String, Object> node = walker.walk(f.get(null));
            node.put("name", f.getName());
            Map<String, Object> e = new LinkedHashMap<>();
            e.put("order", i);
            e.put(CLASS, factory.getClass().getName());
            e.put("kind", KIND_OPAQUE);
            e.put("engine", ENGINE_IREGEX);
            e.put(START, node);
            e.put(END, null);
            commands.add(e);
        }
    }
}

/**
 * Engine dispatch: turns one engine's regex object into an I1 Node.
 *
 * <p>Registered in {@link Extract#WALKERS}.
 */
interface NodeWalker {
    boolean supports(Object regex);

    /** Returns the Node, or throws {@link Unwalkable} (the command is then listed unreachable). */
    Map<String, Object> walk(Object regex);

    /** Reason string becomes the {@code unreachable[].reason}. */
    final class Unwalkable extends RuntimeException {
        private static final long serialVersionUID = 1L;

        Unwalkable(String reason) {
            super(reason);
        }
    }
}

/** Fallback for UBrex objects until a real UBrex walker is registered ahead of it (T03). */
final class UBrexPendingWalker implements NodeWalker {
    /** Stand-in for a command whose UBrex lives outside any field (NaturalGanttCommand). */
    static final class Marker {}

    @Override
    public boolean supports(Object regex) {
        return regex instanceof UnicodeBracketedExpression || regex instanceof Marker;
    }

    @Override
    public Map<String, Object> walk(Object regex) {
        throw new Unwalkable(Extract.REASON_UBREX_PENDING);
    }
}
