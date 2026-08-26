"""The extraction prompt, and its version.

PROMPT_VERSION participates in the cache key. Bump it whenever the prompt text
changes — an in-place edit would leave the cache serving results produced by a
prompt that no longer exists, which is invisible and very hard to debug.
"""

PROMPT_VERSION = 2

EXTRACTION_PROMPT = """\
You are extracting obligations from a passage of policy text.

An obligation is a duty the text places on someone: who must do what, by when,
under what conditions. Extract only what the passage states. Do not infer a
duty that is not written, and do not restate background, definitions, or
purpose statements as obligations.

modality must be exactly one of SHALL, MUST, WILL, SHOULD, MAY — the word the
passage actually uses. If the passage says "shall", the modality is SHALL even if
you would phrase it differently. This distinction is load-bearing: SHALL, MUST and
WILL bind; SHOULD and MAY do not.

WILL is a duty here, not a prediction. DoD's plain-language drafting replaced the
directive "shall" with "will", so "the DoD Components will report annually" states
an obligation exactly as "shall report annually" would. Report it as WILL — the
word the passage used — and do not silently reclassify it as SHALL.

statement must be copied from the passage word for word, as a complete sentence
including the subject that carries the duty. Write "PMs shall manage programs
consistent with statute", not "manage programs consistent with statute" — the
subject stays in the statement even though you also report it as the actor. Quote
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

actor is the party the duty falls on, copied from the statement, or null if the
passage names none. Never write a placeholder such as "no actor specified" — use
null. actor, deadline and conditions may be null; modality never may.

modality is never null, and it is the test of whether something belongs in your
answer at all. **The word you report must appear in the sentence you quote.**
Read the statement you are about to write and find the word in it. If it is not
there, you have either quoted the wrong sentence or invented a duty — in both
cases, leave it out. A modal verb elsewhere in the paragraph does not carry over
to a sentence that lacks one.

Three kinds of sentence look like duties and are not, because none carries one of
those words:

- Scope. "This issuance applies to the OSD, the Military Departments, and the
  Combatant Commands" says who the document covers, not what anyone has to do.
- Headings. "Manage Efficiently and Effectively" is the name of a section.
- Bare task lists. A role followed by lettered items — "ISSOs: a. Assist the
  ISSMs..." — instructs without a modal verb.

Omit all three.

Most passages contain no obligation at all. Returning an empty list is a
correct and common answer. Do not manufacture one to seem useful.

Set confidence to how certain you are that this is a real, stated obligation.

Section: {section_path}

Passage:
{chunk_text}

Respond with JSON only, matching this shape:
{{"obligations": [{{"statement": "...", "modality": "SHALL", "actor": "...",
  "deadline": null, "conditions": null, "confidence": 0.0}}]}}
"""
