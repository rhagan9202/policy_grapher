"""The extraction prompt, and its version.

PROMPT_VERSION participates in the cache key. Bump it whenever the prompt text
changes — an in-place edit would leave the cache serving results produced by a
prompt that no longer exists, which is invisible and very hard to debug.
"""

PROMPT_VERSION = 1

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
