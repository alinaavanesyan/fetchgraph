import json

from fetchgraph.core.models import ContextFetchSpec, Plan, ProviderInfo, RawLLMOutput
from fetchgraph.parsing.plan_parser import PlanParser
from fetchgraph.planning.normalize import PlanNormalizer, PlanNormalizerOptions


def test_plan_normalizer_resolves_and_dedupes() -> None:
    providers = {
        "docs": ProviderInfo(name="Docs"),
        "db": ProviderInfo(name="DB"),
    }
    plan = Plan(
        required_context=["Docs", "db", "unknown", "docs"],
        context_plan=[
            ContextFetchSpec(provider="DOCS", mode="full", selectors={"q": "x"}),
            ContextFetchSpec(provider="docs", mode="full", selectors={"q": "x"}),
        ],
        adr_queries=["  adr  ", ""],
        constraints=["", " must "],
    )
    normalizer = PlanNormalizer(providers)
    normalized = normalizer.normalize(plan)

    assert normalized.required_context == ["docs", "db"]
    assert [spec.provider for spec in normalized.context_plan] == ["docs", "db"]
    assert normalized.adr_queries == ["adr"]
    assert normalized.constraints == ["must"]
    assert any(note.startswith("required_context_unknown") for note in normalized.normalization_notes)


def test_plan_normalizer_fills_context_plan() -> None:
    providers = {
        "docs": ProviderInfo(name="Docs"),
        "code": ProviderInfo(name="Code"),
    }
    plan = Plan(required_context=["docs", "code"])
    normalizer = PlanNormalizer(providers)
    normalized = normalizer.normalize(plan)

    assert [spec.provider for spec in normalized.context_plan] == ["docs", "code"]
    assert any(
        note.startswith("context_plan_required_added")
        or note.startswith("context_plan_filled_from_required_context")
        for note in normalized.normalization_notes
    )


def test_plan_normalizer_corpus_roundtrip() -> None:
    providers = {
        "docs": ProviderInfo(name="Docs"),
        "code": ProviderInfo(name="Code"),
        "qa": ProviderInfo(name="QA"),
    }
    normalizer = PlanNormalizer(
        providers, options=PlanNormalizerOptions(allow_unknown_providers=True)
    )
    parser = PlanParser()

    with open("tests/data/plan_corpus.json", "r", encoding="utf-8") as handle:
        corpus = json.load(handle)

    for item in corpus:
        raw = RawLLMOutput(text=json.dumps(item, ensure_ascii=False))
        plan = parser.parse(raw)
        normalized = normalizer.normalize(plan)
        assert isinstance(normalized.required_context, list)
