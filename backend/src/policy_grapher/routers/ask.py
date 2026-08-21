"""Answering a question from the corpus, or admitting the corpus does not say.

Two properties hold here and are tested rather than intended.

**No Cypher is authored.** A question selects among queries written in advance
(`retrieval/templates.py`) and supplies values, which are bound as parameters.
Nothing a question contains becomes query text, so the classic injection has
nowhere to land — and the classic *prompt* injection has nothing to steer, since
selection is a rule, not a model.

**Every claim is a quotation.** The answer is *composed from* retrieved rows
rather than written about them. There is no step at which a sentence could enter
without a passage behind it, which is a stronger guarantee than instructing a
model to cite its sources — that instruction is advice, and this is arithmetic.
When retrieval finds nothing, the answer says so and the citation list is empty.
"""

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver, RoutingControl

from policy_grapher.auth import Principal, require_principal
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver, get_embedder
from policy_grapher.embedding import Embedder
from policy_grapher.models import AnswerOut, AskRequest, CitationOut
from policy_grapher.retrieval.hybrid import retrieve
from policy_grapher.retrieval.templates import (
    GROUNDED_PASSAGES,
    TEMPLATES,
    select_template,
)

router = APIRouter(prefix="/ask", tags=["ask"])

ROW_LIMIT = 10
QUOTE_LIMIT = 600

NOTHING_FOUND = (
    "Nothing in the corpus addresses that. No passage matched, so there is no "
    "grounded answer to give — this is an absence of evidence, not a statement "
    "that the answer is no."
)


def _truncate(text: str) -> str:
    quote = " ".join((text or "").split())
    return quote if len(quote) <= QUOTE_LIMIT else quote[:QUOTE_LIMIT].rstrip() + "…"


def _from_template(driver, database, template, parameters) -> list[CitationOut]:
    """Run a pre-written query with bound parameters, in a read transaction.

    `RoutingControl.READ` is belt and braces over the static check that no
    template contains a write clause: Neo4j refuses a write inside a read
    transaction, so even a template edited carelessly in future cannot mutate.
    """
    records, _, _ = driver.execute_query(
        template.cypher,
        {**parameters, "limit": ROW_LIMIT},
        database_=database,
        routing_=RoutingControl.READ,
    )
    return [
        CitationOut(
            document=record["document"],
            section_path=record["section_path"],
            page=record["page"],
            quote=_truncate(record["statement"] or record["quote"]),
        )
        for record in records
    ]


def _from_retrieval(driver, database, *, question, embedder) -> list[CitationOut]:
    return [
        CitationOut(
            document=hit.document,
            section_path=hit.section_path,
            page=hit.page,
            quote=_truncate(hit.text),
        )
        for hit in retrieve(
            driver, database, query=question, embedder=embedder, limit=ROW_LIMIT
        )
    ]


def _compose(citations: list[CitationOut]) -> str:
    """Build the answer out of the citations themselves.

    Deliberately extractive. A generative step here would be the one place in the
    pipeline able to assert something the corpus does not say, and for a
    compliance tool that is not a trade worth making. A model could later render
    prose *from these same rows* behind a port — the citations requirement is what
    would keep that safe.
    """
    if not citations:
        return NOTHING_FOUND

    lines = ["The corpus states:"]
    for citation in citations:
        where = "/".join(citation.section_path)
        lines.append(
            f'— "{citation.quote}" ({citation.document}, {where}, p. {citation.page})'
        )
    return "\n".join(lines)


@router.post("", response_model=AnswerOut)
def ask(
    body: AskRequest,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    embedder: Embedder = Depends(get_embedder),
    principal: Principal = Depends(require_principal),
) -> AnswerOut:
    selection = select_template(body.question)

    template = TEMPLATES.get(selection.name)
    if template is None:
        # Selection is a rule today and always names a known template. This
        # guards the day it is not: a model-backed selector that invents a name
        # must stop here rather than reach a query builder.
        raise HTTPException(
            status_code=500,
            detail=(
                f"Selected template {selection.name!r} is not one of "
                f"{sorted(TEMPLATES)}."
            ),
        )

    database = settings.neo4j_database
    if template.cypher is None:
        citations = _from_retrieval(
            driver,
            database,
            question=body.question,
            embedder=embedder,
        )
    else:
        citations = _from_template(driver, database, template, selection.parameters)
        if not citations:
            # A structured query that matched nothing is not the end of the road:
            # the passage may still be there under different words.
            citations = _from_retrieval(
                driver,
                database,
                question=body.question,
                embedder=embedder,
            )
            if citations:
                return AnswerOut(
                    answer=_compose(citations),
                    citations=citations,
                    template_used=GROUNDED_PASSAGES,
                )

    return AnswerOut(
        answer=_compose(citations),
        citations=citations,
        template_used=template.name if citations else GROUNDED_PASSAGES,
    )
