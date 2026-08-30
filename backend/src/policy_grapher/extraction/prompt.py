"""The extraction prompt, and its version.

PROMPT_VERSION participates in the cache key. Bump it whenever the prompt text
changes — an in-place edit would leave the cache serving results produced by a
prompt that no longer exists, which is invisible and very hard to debug.
"""

from dataclasses import dataclass

PROMPT_VERSION = 4

EXTRACTION_PROMPT = """\
You are extracting obligations from a passage of policy text.

An obligation is a duty the text places on someone: who must do what, by when,
under what conditions. Extract only what the passage states. Do not infer a
duty that is not written, and do not restate background, definitions, or
purpose statements as obligations.

modality must be exactly one of SHALL, MUST, WILL, SHOULD, MAY, ASSIGNED. The
first five are the word the passage actually uses. If the passage says "shall",
the modality is SHALL even if you would phrase it differently. This distinction
is load-bearing: SHALL, MUST and WILL bind; SHOULD and MAY do not. ASSIGNED is
explained below and binds.

WILL is a duty here, not a prediction. DoD's plain-language drafting replaced the
directive "shall" with "will", so "the DoD Components will report annually" states
an obligation exactly as "shall report annually" would. Report it as WILL — the
word the passage used — and do not silently reclassify it as SHALL.

statement must be copied from the passage word for word. For the five word
modalities it is a complete sentence including the subject that carries the duty:
write "PMs shall manage programs consistent with statute", not "manage programs
consistent with statute" — the subject stays in the statement even though you also
report it as the actor. For ASSIGNED it is the lettered item as written, which
begins at the verb and has no subject; that case is explained below. Quote
the whole sentence, from its first word to its closing full stop — including any
leading clause such as "As the retention planning process works though approvals,"
and including the final "." itself. Do not paraphrase, do not shorten, and do not
begin the statement at the verb. A
statement that is not a quotation of the passage is not usable: it is hashed into
the obligation's identity, so a re-worded one silently detaches the reviews a
person has already recorded against that clause.

Do not extract headings, titles, or the labels of paragraphs. "Manage Efficiently
and Effectively" and "Focus on Affordability" are the names of sections; they
impose no duty on anyone, and reporting them as obligations is a common and
costly mistake.

actor is the party the duty falls on. For the five word modalities it is copied
from the statement, and must appear there; if the sentence names no party, use
null. For ASSIGNED it is the office named in the role heading above the item, and
it is not in the statement — that case is explained below. Never write a placeholder such as "no actor specified" — use
null. actor, deadline and conditions may be null; modality never may.

modality is never null, and it is the test of whether something belongs in your
answer at all. **For the five word modalities, the word you report must appear in
the sentence you quote.**
Read the statement you are about to write and find the word in it. If it is not
there, you have either quoted the wrong sentence or invented a duty — in both
cases, leave it out. A modal verb elsewhere in the paragraph does not carry over
to a sentence that lacks one.

ASSIGNED is for a duty the passage imposes by position rather than by a word.
DoD writes its responsibilities sections as a role heading followed by lettered
third-person verbs:

  2.1.  UNDER SECRETARY OF DEFENSE FOR ACQUISITION AND SUSTAINMENT (USD(A&S)).
  The USD(A&S):
  a.  Executes the acquisition responsibilities in DoDD 5135.02.
  b.  Serves as an advisor in the preparation of MDAP study guidance.

Those are duties assigned to a named office, and the passage grades their force
nowhere. Report each lettered item as ASSIGNED.

The role heading may be longer than that and the items need not be third-person
verbs. A lead-in clause may come before the office — "In accordance with DoDD
5144.02 ... the DoD Chief Information Officer:" — and the heading may end "by:"
with gerund items — "a. Prescribing policies and procedures ...". Both are
ASSIGNED. What makes an item ASSIGNED is the colon above it and the office named
before that colon, not the shape of the verb. Do not label such items SHALL:
there is no "shall" in them.

For an ASSIGNED item, statement is the item itself, copied word for word without
its letter — "Executes the acquisition responsibilities in DoDD 5135.02." — and
actor is the office named in the heading above it, here "USD(A&S)". Do not splice
the office into the statement and do not rewrite the verb: the statement is
hashed into the obligation's identity, so a sentence you compose rather than copy
detaches the reviews already recorded against that clause. The subject is not
lost; it is what actor is for.

ASSIGNED requires an actor. If you cannot name the office the duty falls on from
a heading above the item, the passage is assigning nothing — leave it out.

Two kinds of sentence look like duties and are not:

- Scope. "This issuance applies to the OSD, the Military Departments, and the
  Combatant Commands" says who the document covers, not what anyone has to do.
- Headings. "Manage Efficiently and Effectively" is the name of a section, and so
  is "Be Responsive." A heading names no office and imposes nothing on anyone.
  It is not ASSIGNED either — ASSIGNED needs a role heading above it that says
  who acts.

Omit both.

Most passages contain no obligation at all. Returning an empty list is a
correct and common answer. Do not manufacture one to seem useful.

Set confidence to how certain you are that this is a real, stated obligation.

Section: {section_path}

Passage:
{chunk_text}

Respond with JSON only, matching this shape:
{{"obligations": [{{"statement": "...", "modality": "SHALL|ASSIGNED", "actor": "...",
  "deadline": null, "conditions": null, "confidence": 0.0}}]}}
"""


@dataclass(frozen=True)
class PromptRule:
    """One rule the prompt states, and what enforces it.

    ADR-036. Four sprints running, the prompt stated a rule that nothing
    enforced, each went unenforced for at least a sprint, and each was found by
    looking at extracted data rather than by a test — then fixed deterministically
    in under an hour, because each was checkable all along.

    A prompt is a string: nothing executes it, and no test related its sentences
    to the validators. A rule that is merely written reads exactly like a rule
    that holds. This registry is what makes the difference visible, and
    `test_prompt_rules.py` is what makes writing an unenforced rule fail.
    """

    id: str
    # Verbatim from EXTRACTION_PROMPT, whitespace-normalised. The test asserts it
    # is still there, so editing the prompt without revisiting this fails.
    sentence: str
    # Exactly one of these two. `enforced_by` names the validator; `unenforceable`
    # says why no validator can exist. A shrug is not a reason.
    enforced_by: str | None = None
    unenforceable: str | None = None


PROMPT_RULES: tuple[PromptRule, ...] = (
    PromptRule(
        id="modality-is-one-of-six",
        sentence="modality must be exactly one of SHALL, MUST, WILL, SHOULD, MAY, ASSIGNED.",
        enforced_by="Modality",
    ),
    PromptRule(
        id="modality-word-is-in-the-statement",
        sentence=(
            "For the five word modalities, the word you report must appear in "
            "the sentence you quote."
        ),
        enforced_by="ExtractedObligation._modality_word_is_in_the_statement",
    ),
    PromptRule(
        id="statement-is-a-quotation",
        sentence="statement must be copied from the passage word for word",
        enforced_by="validate_extracted",
    ),
    PromptRule(
        id="no-placeholder-actor",
        sentence=(
            'Never write a placeholder such as "no actor specified" — use'
        ),
        enforced_by="ExtractedObligation._placeholder_actor_is_no_actor",
    ),
    PromptRule(
        id="assigned-requires-an-actor",
        sentence="ASSIGNED requires an actor.",
        enforced_by="ExtractedObligation._an_assigned_duty_names_its_actor",
    ),
    PromptRule(
        id="modality-is-never-null",
        sentence="actor, deadline and conditions may be null; modality never may.",
        enforced_by="Modality",
    ),
    PromptRule(
        id="confidence-is-a-probability",
        sentence="Set confidence to how certain you are that this is a real, stated obligation.",
        enforced_by="ExtractedObligation.confidence",
    ),
    PromptRule(
        id="actor-is-copied-from-the-statement",
        sentence=(
            "For the five word modalities it is copied from the statement, and "
            "must appear there"
        ),
        # Enforced for the five word modalities by ADR-035, and the sentence now
        # says so: STORY-103 corrected it from a general claim that was false for
        # ASSIGNED, whose actor ADR-033 takes from the role heading above the item
        # and which is correctly absent from the statement.
        enforced_by="validate_extracted",
    ),
    PromptRule(
        id="statement-includes-the-subject",
        sentence=(
            "it is a complete sentence including the subject that carries the duty"
        ),
        unenforceable=(
            "'Is this a complete sentence carrying its subject' needs a parser and "
            "a judgement about sentence fragments this project has no basis to "
            "make. The clause that used to stand here — that the sentence was also "
            "false for ASSIGNED — was true until STORY-103 corrected it, and is "
            "removed rather than left to rot."
        ),
    ),
    PromptRule(
        id="do-not-infer-an-unwritten-duty",
        sentence="Do not infer a\nduty that is not written",
        unenforceable=(
            "Requires knowing what the passage means, not what it contains. The "
            "quotation rule bounds it — an inferred duty is rarely a quotation — "
            "but a model can quote a real sentence and still call it a duty when "
            "it is not."
        ),
    ),
    PromptRule(
        id="do-not-extract-headings",
        sentence="Do not extract headings, titles, or the labels of paragraphs.",
        unenforceable=(
            "'Is this line a heading' is a judgement. It is bounded in practice "
            "by two other rules — a heading rarely contains a modal verb, and "
            "ADR-033's guards refuse a heading as ASSIGNED — which is how "
            '"Be Responsive." is now kept out, indirectly rather than by name.'
        ),
    ),
    PromptRule(
        id="omit-scope-sentences",
        sentence=(
            '"This issuance applies to the OSD, the Military Departments, and the'
        ),
        unenforceable=(
            "Same class as headings: recognising a scope statement is semantic. "
            "In practice these carry no modal verb and fail the modality rule, "
            "which is why they arrive as dropped items rather than as obligations."
        ),
    ),
    PromptRule(
        id="an-empty-answer-is-correct",
        sentence="Returning an empty list is a\ncorrect and common answer.",
        unenforceable=(
            "A permission, not a requirement — there is nothing for a validator "
            "to refuse. Registered so that the count of rules is honest."
        ),
    ),
    PromptRule(
        id="will-is-not-reclassified-as-shall",
        sentence="do not silently reclassify it as SHALL",
        unenforceable=(
            "Cannot be checked directly: nothing can know what the model would "
            "otherwise have said. Bounded by the modality-word rule, which "
            "refuses a SHALL whose statement says 'will'."
        ),
    ),
)
