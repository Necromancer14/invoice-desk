from invoice_desk.evaluation import evaluate
from invoice_desk.extractors import RuleBasedExtractor


def test_rule_based_eval_numbers_are_sane_and_safe():
    r = evaluate(mode="rules")
    assert r["count"] == 60
    assert r["unsafe_auto_approvals"] == 0 and r["false_rejections"] == 0
    assert r["by_format"]["txt"]["agree"] / r["by_format"]["txt"]["n"] >= 0.85
    assert r["by_format"]["png"]["agree"] / r["by_format"]["png"]["n"] <= 0.3  # images genuinely need Claude
    assert r["by_scenario"]["prompt_injection"]["agree"] == 1


def test_a_perfect_extractor_scores_perfectly():
    """Feeds the answer key back in as if it were a perfect model: pipeline + rules must then match every expected decision."""
    import json
    from invoice_desk.evaluation import SAMPLES
    from invoice_desk.extractors import Extraction
    truth = {i["file"]: i["truth"] for i in json.loads((SAMPLES / "answers.json").read_text(encoding="utf-8"))["invoices"]}

    class Oracle:
        def extract(self, blob, ct, name):
            return Extraction(dict(truth[name]), 1.0, {}, [], "oracle")
    r = evaluate(mode="rules", extractor_factory=lambda *a: Oracle())
    assert r["decision_agreement"] == 1.0 and r["field_accuracy"] == 1.0
