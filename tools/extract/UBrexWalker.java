import com.plantuml.ubrex.CaseMode;
import com.plantuml.ubrex.CharClassRaw;
import com.plantuml.ubrex.CharSet;
import com.plantuml.ubrex.LookAround;
import com.plantuml.ubrex.UnicodeBracketedExpression;
import com.plantuml.ubrex.builder.UBrexPart;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.function.Function;
import java.util.jar.JarFile;
import net.sourceforge.plantuml.PSystemBuilder;
import net.sourceforge.plantuml.command.PSystemCommandFactory;
import net.sourceforge.plantuml.gantt.command.NaturalGanttCommand;
import net.sourceforge.plantuml.gantt.lang.Something;
import net.sourceforge.plantuml.gantt.lang.Subject;
import net.sourceforge.plantuml.gantt.lang.Verbs;
import net.sourceforge.plantuml.gantt.ulang.VerbPhraseAction;

/**
 * UBrex Challenge tree to I1 Node ({@code t = "ub-<SimpleClassName>"}).
 *
 * <p>Entry points: a {@link UBrexPart} exposes its tree via {@code getChallenge()}
 * (com/plantuml/ubrex/builder/UBrexPart.java:42); the object returned by
 * {@code UnicodeBracketedExpression.from(challenge)} (UnicodeBracketedExpression.java:57) is an
 * anonymous class holding the challenge in its synthetic {@code val$challenge} field.
 *
 * <p>Fields read per Challenge (all under com/plantuml/ubrex/ at 97a5992): ChallengeAlternative
 * {@code alternatives}; CompositeList {@code challenges}; CompositeNamed {@code name},
 * {@code challenges}; ChallengeOptional/OneOrMore/ZeroOrMore/UpTo {@code origin};
 * ChallengeRepetition {@code origin}, {@code repetition} ({@code values}, {@code minInclusive});
 * ChallengeLazzyOneOrMore {@code origin}, {@code stopCondition}; ChallengeOneOrMoreUpToOldVersion
 * {@code origin}, {@code end}; ChallengeLookAhead/LookBehind {@code origin}, {@code ahead}
 * ({@code LookAround}); ChallengeSingleChar {@code ch}, {@code mode}; ChallengeCharClass
 * {@code charClass} ({@code charClassRaw}, {@code type}); ChallengeCharSet {@code charSet},
 * {@code charClasses}, {@code reversed}; ChallengeEndOfText has none.
 *
 * <p>Extra Node fields (additive to I1): {@code direction}/{@code negated}/{@code lookAround}
 * (look-around), {@code min}/{@code counts} (repetition), {@code caseMode}, {@code charClass},
 * {@code chars}/{@code classes} (char set). ChallengeAlternative/CompositeList/CompositeNamed carry
 * their parts in {@code children}; single-operand challenges have one child; two-operand ones
 * (lazy, up-to-old-version) have {@code [operand, stop]}.
 */
final class UBrexWalker implements NodeWalker {
    static final String REASON_NATURAL_GANTT =
            "natural-gantt-sentence: grammar is the subject x verb-phrase composition in extracted/gantt-lang.json";

    private static final String TYPE_PREFIX = "ub-";
    private static final String ANON_CHALLENGE_FIELD = "val$challenge";
    private static final String ORIGIN = "origin";
    private static final String CHALLENGES = "challenges";
    private static final String CASE_MODE = "caseMode";
    private static final int ASCII_FIRST = 32;
    private static final int ASCII_LAST = 128;

    private static final Map<String, Function<Object, Map<String, Object>>> BUILDERS = new LinkedHashMap<>();

    static {
        BUILDERS.put("ChallengeAlternative", c -> composite(c, null, Refl.field(c, "alternatives")));
        BUILDERS.put("CompositeList", c -> composite(c, null, Refl.field(c, CHALLENGES)));
        BUILDERS.put("CompositeNamed", c -> composite(c, (String) Refl.field(c, "name"), Refl.field(c, CHALLENGES)));
        for (String wrapper :
                List.of("ChallengeOptional", "ChallengeOneOrMore", "ChallengeZeroOrMore", "ChallengeUpTo")) {
            BUILDERS.put(wrapper, c -> composite(c, null, List.of(Refl.field(c, ORIGIN))));
        }
        BUILDERS.put("ChallengeRepetition", UBrexWalker::repetition);
        BUILDERS.put("ChallengeLazzyOneOrMore", c -> twoOperand(c, "stopCondition"));
        BUILDERS.put("ChallengeOneOrMoreUpToOldVersion", c -> twoOperand(c, "end"));
        BUILDERS.put("ChallengeLookAhead", UBrexWalker::lookAround);
        BUILDERS.put("ChallengeLookBehind", UBrexWalker::lookAround);
        BUILDERS.put("ChallengeEndOfText", c -> leaf(c, null));
        BUILDERS.put("ChallengeSingleChar", UBrexWalker::singleChar);
        BUILDERS.put("ChallengeCharClass", UBrexWalker::charClass);
        BUILDERS.put("ChallengeCharSet", UBrexWalker::charSet);
    }

    @Override
    public boolean supports(Object regex) {
        return regex instanceof UnicodeBracketedExpression || regex instanceof UBrexPendingWalker.Marker;
    }

    @Override
    public Map<String, Object> walk(Object regex) {
        if (regex instanceof UBrexPendingWalker.Marker) {
            throw new Unwalkable(REASON_NATURAL_GANTT);
        }
        return node(rootChallenge(regex));
    }

    /** The Challenge tree root of a UBrex object. */
    static Object rootChallenge(Object ubrex) {
        if (ubrex instanceof UBrexPart part) {
            return part.getChallenge();
        }
        try {
            return Refl.field(ubrex, ANON_CHALLENGE_FIELD);
        } catch (IllegalStateException e) {
            throw new Unwalkable("unknown-ubrex-holder:" + ubrex.getClass().getName());
        }
    }

    /** Node for a Challenge object. */
    static Map<String, Object> node(Object challenge) {
        Function<Object, Map<String, Object>> builder =
                BUILDERS.get(challenge.getClass().getSimpleName());
        if (builder == null) {
            throw new Unwalkable("unknown-challenge:" + challenge.getClass().getName());
        }
        return builder.apply(challenge);
    }

    private static Map<String, Object> typed(Object challenge, String name, String pattern, List<Object> kids) {
        return IRegexWalker.node(TYPE_PREFIX + challenge.getClass().getSimpleName(), name, pattern, kids);
    }

    private static Map<String, Object> leaf(Object challenge, String pattern) {
        return typed(challenge, null, pattern, List.of());
    }

    private static Map<String, Object> composite(Object challenge, String name, Object parts) {
        List<Object> kids = new ArrayList<>();
        for (Object part : (Collection<?>) parts) {
            kids.add(node(part));
        }
        return typed(challenge, name, null, kids);
    }

    private static Map<String, Object> twoOperand(Object challenge, String stopField) {
        return composite(challenge, null, List.of(Refl.field(challenge, ORIGIN), Refl.field(challenge, stopField)));
    }

    private static Map<String, Object> repetition(Object challenge) {
        Map<String, Object> n = composite(challenge, null, List.of(Refl.field(challenge, ORIGIN)));
        Object rep = Refl.field(challenge, "repetition");
        int min = ((java.util.concurrent.atomic.AtomicInteger) Refl.field(rep, "minInclusive")).get();
        n.put("min", min == Integer.MAX_VALUE ? null : min);
        n.put("counts", new ArrayList<>((Set<?>) Refl.field(rep, "values")));
        return n;
    }

    private static Map<String, Object> lookAround(Object challenge) {
        Map<String, Object> n = composite(challenge, null, List.of(Refl.field(challenge, ORIGIN)));
        LookAround look = (LookAround) Refl.field(challenge, "ahead");
        n.put("direction", look.isLookBehind() ? "behind" : "ahead");
        n.put("negated", look.name().endsWith("NEGATIVE"));
        n.put("lookAround", look.name());
        return n;
    }

    private static Map<String, Object> singleChar(Object challenge) {
        Map<String, Object> n = leaf(challenge, String.valueOf(Refl.field(challenge, "ch")));
        n.put(CASE_MODE, ((CaseMode) Refl.field(challenge, "mode")).name());
        return n;
    }

    private static Map<String, Object> charClass(Object challenge) {
        Object cc = Refl.field(challenge, "charClass");
        Map<String, Object> n = leaf(challenge, null);
        n.put("charClass", ((CharClassRaw) Refl.field(cc, "charClassRaw")).name());
        n.put("negated", "NEGATIVE".equals(String.valueOf(Refl.field(cc, "type"))));
        return n;
    }

    private static Map<String, Object> charSet(Object challenge) {
        CharSet set = (CharSet) Refl.field(challenge, "charSet");
        StringBuilder chars = new StringBuilder();
        for (char ch = ASCII_FIRST; ch <= ASCII_LAST; ch++) {
            if (set.contains(ch) && ch == CaseMode.ensureLowercase(ch)) {
                chars.append(ch);
            }
        }
        Set<String> classes = new TreeSet<>();
        for (Object raw : (Set<?>) Refl.field(challenge, "charClasses")) {
            classes.add(((CharClassRaw) raw).name());
        }
        Map<String, Object> n = leaf(challenge, chars.toString());
        n.put("chars", chars.toString());
        n.put("classes", new ArrayList<>(classes));
        n.put("negated", Refl.field(challenge, "reversed"));
        n.put(CASE_MODE, CaseMode.CASE_INSENSITIVE.name());
        return n;
    }
}

/**
 * Gantt sentence parts to {@code extracted/gantt-lang.json} (same Node shape as I1).
 *
 * <p>Registry (97a5992): the nine subjects are registered as {@code new NaturalGanttCommand(
 * SubjectX.ME)} at gantt/GanttDiagramFactory.java:113-121 (method {@code addLanguageCommands},
 * called at :89); each subject enumerates its verb phrases via {@code Subject.getVerbPhrases()}
 * (gantt/lang/Subject.java:53), each a {@code VerbPhraseAction(verb, ignored?, complement)}
 * (gantt/ulang/VerbPhraseAction.java:53-55, :57, :66). Verbs are the static fields of
 * gantt/lang/Verbs.java:53-72; complements are {@code Something} implementations
 * (gantt/lang/Something.java:48). Subject and complement classes are also enumerated by scanning
 * the jar for {@code gantt/lang/*} so unreferenced ones are reported, not dropped.
 *
 * <p>Usage: {@code java -Dpin.sha=.. -Dpin.version=.. -cp <jar>:<classes> GanttLangDump <outDir>}.
 */
final class GanttLangDump {
    static final String OUTPUT_FILE = "gantt-lang.json";

    private static final String FACTORY = "GanttDiagramFactory";
    private static final String LANG_PREFIX = "net/sourceforge/plantuml/gantt/lang/";
    private static final String NATURAL = "NaturalGanttCommand";
    private static final String SUBJECT_FIELD = "subject";
    private static final String CLASS = "class";
    private static final String TREE = "tree";
    private static final String PARAMS = "params";
    private static final String PROP_SHA = "pin.sha";
    private static final String PROP_VERSION = "pin.version";
    private static final String COMBINATION =
            "sentence := SPACES? SUBJECT SPACES? VERBPHRASE (AND VERBPHRASE)*; "
                    + "VERBPHRASE := VERB SPACES? (IGNORED SPACES?)? COMPLEMENT; "
                    + "after the subject, verb phrases are tried in listed order and the first whose "
                    + "verb+ignored+complement matches is used; after each phrase, AND is tried and, if "
                    + "it matches, the candidate list is reset to all verb phrases of the same subject. "
                    + "Command validity requires subject non-empty and at least one verb phrase matching.";
    private static final List<String> COMBINATION_CITES = List.of(
            "gantt/command/NaturalGanttCommand.java:61 (AND)",
            "gantt/command/NaturalGanttCommand.java:74-122 (execute: subject, then verb-phrase loop)",
            "gantt/command/NaturalGanttCommand.java:125-141 (isValid)",
            "gantt/ulang/VerbPhraseAction.java:51 (SPACES)",
            "gantt/ulang/VerbPhraseAction.java:100-124 (parseVerbPhrase)",
            "gantt/ulang/VerbPhraseAction.java:126-150 (check)",
            "gantt/GanttDiagramFactory.java:112-122 (addLanguageCommands)");

    private final List<Map<String, Object>> complements = new ArrayList<>();
    private final Map<String, Integer> complementIndex = new LinkedHashMap<>();

    private GanttLangDump() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            throw new IllegalArgumentException("usage: GanttLangDump <outDir>");
        }
        Map<String, Object> pin = new LinkedHashMap<>();
        pin.put("sha", System.getProperty(PROP_SHA));
        pin.put("version", System.getProperty(PROP_VERSION));
        Path out = Path.of(args[0]);
        Files.createDirectories(out);
        Files.writeString(out.resolve(OUTPUT_FILE), Json.write(new GanttLangDump().build(pin)), StandardCharsets.UTF_8);
    }

    Map<String, Object> build(Map<String, Object> pin) throws Exception {
        Map<String, Object> doc = new LinkedHashMap<>();
        doc.put("pin", pin);
        doc.put("combination", combination());
        doc.put("subjects", subjects());
        doc.put("verbs", verbs());
        doc.put("complements", complements);
        doc.put("unreferenced", addUnreferencedComplements());
        return doc;
    }

    private Map<String, Object> combination() {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("rule", COMBINATION);
        c.put("spaces", UBrexWalker.node(UBrexWalker.rootChallenge(Refl.field(null, VerbPhraseAction.class, "SPACES"))));
        c.put("and", UBrexWalker.node(UBrexWalker.rootChallenge(Refl.field(null, NaturalGanttCommand.class, "AND"))));
        c.put("cites", COMBINATION_CITES);
        return c;
    }

    // ---- subjects ---------------------------------------------------------------------

    private List<Object> subjects() throws Exception {
        List<Object> out = new ArrayList<>();
        List<Object> cmds = ganttCommands();
        for (int order = 0; order < cmds.size(); order++) {
            if (NATURAL.equals(cmds.get(order).getClass().getSimpleName())) {
                out.add(subjectEntry(order, Refl.field(cmds.get(order), SUBJECT_FIELD)));
            }
        }
        return out;
    }

    private static List<Object> ganttCommands() throws Exception {
        Object builder = PSystemBuilder.getInstance();
        for (Object f : (List<?>) Refl.field(builder, "factories")) {
            if (FACTORY.equals(f.getClass().getSimpleName())) {
                Method init = PSystemCommandFactory.class.getDeclaredMethod("initCommandsList", List.class);
                init.setAccessible(true);
                List<Object> cmds = new ArrayList<>();
                init.invoke(f, cmds);
                return cmds;
            }
        }
        throw new IllegalStateException("no " + FACTORY);
    }

    private Map<String, Object> subjectEntry(int commandOrder, Object subject) throws Exception {
        Map<String, Object> e = new LinkedHashMap<>();
        e.put(CLASS, subject.getClass().getName());
        e.put("commandOrder", commandOrder);
        Object subjectPart = subject.getClass().getMethod("toUnicodeBracketedExpressionSubject").invoke(subject);
        e.put(TREE, UBrexWalker.node(UBrexWalker.rootChallenge(subjectPart)));
        List<Object> phrases = new ArrayList<>();
        Collection<?> actions = (Collection<?>) subject.getClass().getMethod("getVerbPhrases").invoke(subject);
        for (Object action : actions) {
            phrases.add(phrase(phrases.size(), action));
        }
        e.put("verbPhrases", phrases);
        return e;
    }

    private Map<String, Object> phrase(int order, Object action) throws Exception {
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("order", order);
        p.put("verb", verbName(Refl.field(action, "verb")));
        Object ignored = Refl.field(action, "ignored");
        p.put("ignored", ignored == null ? null : UBrexWalker.node(UBrexWalker.rootChallenge(ignored)));
        Map<String, Object> complement = describe(Refl.field(action, "complement"));
        p.put("complementClass", complement.get(CLASS));
        p.put("complement", indexOf(complement));
        return p;
    }

    // ---- verbs ------------------------------------------------------------------------

    private static List<Field> verbFields() {
        List<Field> out = new ArrayList<>();
        for (Field f : Verbs.class.getDeclaredFields()) {
            if (Modifier.isStatic(f.getModifiers()) && f.getType() == Verbs.class) {
                out.add(f);
            }
        }
        return out;
    }

    private static String verbName(Object verb) throws IllegalAccessException {
        for (Field f : verbFields()) {
            if (f.get(null) == verb) {
                return f.getName();
            }
        }
        throw new IllegalStateException("verb not in Verbs registry");
    }

    private static List<Object> verbs() throws Exception {
        List<Object> out = new ArrayList<>();
        for (Field f : verbFields()) {
            Map<String, Object> v = new LinkedHashMap<>();
            v.put("name", f.getName());
            v.put(TREE, UBrexWalker.node(UBrexWalker.rootChallenge(Refl.field(f.get(null), "ubrex"))));
            out.add(v);
        }
        return out;
    }

    // ---- complements ------------------------------------------------------------------

    /** Class, simple scalar parameters, tree and (for combinators) parts of one complement. */
    private static Map<String, Object> describe(Object something) throws Exception {
        Map<String, Object> d = new LinkedHashMap<>();
        d.put(CLASS, something.getClass().getName());
        List<Object> parts = new ArrayList<>();
        Map<String, Object> params = new LinkedHashMap<>();
        for (Field f : something.getClass().getDeclaredFields()) {
            if (Modifier.isStatic(f.getModifiers())) {
                continue;
            }
            f.setAccessible(true);
            Object value = f.get(something);
            if (Something.class.isInstance(value)) {
                parts.add(describe(value));
            } else if (value instanceof Enum<?> || value instanceof Number || value instanceof Boolean || value instanceof String) {
                params.put(f.getName(), value instanceof Enum<?> en ? en.name() : value);
            }
        }
        d.put(PARAMS, params);
        Object part = something.getClass().getMethod("toUnicodeBracketedExpressionComplement").invoke(something);
        d.put(TREE, UBrexWalker.node(UBrexWalker.rootChallenge(part)));
        if (!parts.isEmpty()) {
            d.put("parts", parts);
        }
        return d;
    }

    private int indexOf(Map<String, Object> complement) {
        String key = Json.compact(complement);
        Integer known = complementIndex.get(key);
        if (known != null) {
            return known;
        }
        complements.add(complement);
        complementIndex.put(key, complements.size() - 1);
        return complements.size() - 1;
    }

    /** Scans gantt/lang in the jar; instantiates complement classes no verb phrase referenced. */
    private List<Object> addUnreferencedComplements() throws Exception {
        List<Object> unreferenced = new ArrayList<>();
        for (Class<?> c : langClasses()) {
            if (!Something.class.isAssignableFrom(c) || c.isInterface() || Modifier.isAbstract(c.getModifiers())) {
                continue;
            }
            if (complements.stream().anyMatch(d -> c.getName().equals(d.get(CLASS)))) {
                continue;
            }
            unreferenced.add(instantiateOrReport(c));
        }
        return unreferenced;
    }

    private Object instantiateOrReport(Class<?> c) throws Exception {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put(CLASS, c.getName());
        try {
            Constructor<?> ctor = c.getDeclaredConstructor();
            ctor.setAccessible(true);
            Map<String, Object> d = describe(ctor.newInstance());
            indexOf(d);
            entry.put("instantiated", true);
        } catch (NoSuchMethodException e) {
            entry.put("instantiated", false);
            entry.put("reason", "no-nullary-constructor (combinator or parameterised; its parts are covered via verb phrases)");
        }
        return entry;
    }

    private static List<Class<?>> langClasses() throws IOException, URISyntaxException, ClassNotFoundException {
        Path jar = Path.of(Subject.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        List<String> names = new ArrayList<>();
        try (JarFile jf = new JarFile(jar.toFile())) {
            jf.stream().map(e -> e.getName()).filter(n -> n.startsWith(LANG_PREFIX) && n.endsWith(".class") && n.indexOf('$') < 0)
                    .sorted().forEach(names::add);
        }
        List<Class<?>> out = new ArrayList<>();
        for (String n : names) {
            out.add(Class.forName(n.substring(0, n.length() - ".class".length()).replace('/', '.'), false, Subject.class.getClassLoader()));
        }
        return out;
    }
}
