"""Ephemeral evidence checks and newly planned local invention-assist tasks."""
import json
import unittest

from qnaplibrary.chart_ai import assess_chart
from qnaplibrary.patents import PROMPTS, STAGES


def chart(evidence=True):
    rows = []
    for label, doc in (("A", 11), ("B", 22)):
        rows.append({"element": {"label": label, "text": "電気回路の構成" + label},
                     "evidence": ([{"doc_id": doc, "chunk_id": doc + 1,
                                     "title": "引用文献" + label, "section": "請求項",
                                     "snippet": "検索された記載"}] if evidence else [])})
    return {"claim_no": 1, "claim": "テスト請求項", "rows": rows}


class FakeLocal:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat(self, messages, **kw):
        self.calls.append((messages, kw))
        return {"content": self.reply, "model": "offline-test"}


class LocalIdeaTests(unittest.TestCase):
    def test_innovation_tasks_registered_in_correct_stages(self):
        for key in ("brainstorm", "invention_summary", "prior_art_gaps", "claim_scope", "design_around"):
            self.assertIn(key, PROMPTS)
            self.assertTrue(PROMPTS[key]["prompt"])
            self.assertTrue(any(key in stage["ai"] for stage in STAGES))

    def test_citation_never_points_to_other_element_or_hallucinated_id(self):
        p = FakeLocal(json.dumps({"rows": [
            {"label": "A", "judgment": "○", "reason": "Aに対応", "citations": ["E1", "E999"]},
            {"label": "B", "judgment": "△", "reason": "誤った参照", "citations": ["E2"]}]}))
        result = assess_chart(chart(), p)
        self.assertTrue(result["evaluated"])
        self.assertEqual(result["rows"][0]["assessment"]["judgment"], "○")
        self.assertEqual(result["rows"][0]["assessment"]["citations"][0]["doc_id"], 11)
        self.assertEqual(len(result["rows"][0]["assessment"]["citations"]), 1)
        self.assertEqual(result["rows"][1]["assessment"]["judgment"], "?")
        self.assertEqual(result["rows"][1]["assessment"]["citations"], [])
        self.assertEqual(len(p.calls), 1)

    def test_no_evidence_never_calls_model(self):
        p = FakeLocal("not json")
        result = assess_chart(chart(False), p)
        self.assertFalse(result["evaluated"])
        self.assertEqual(len(p.calls), 0)
        self.assertEqual([r["assessment"]["judgment"] for r in result["rows"]], ["?", "?"])

    def test_bad_model_response_fails_cleanly(self):
        with self.assertRaisesRegex(ValueError, "JSON"):
            assess_chart(chart(), FakeLocal("invalid response"))

    def test_element_limit(self):
        c = chart()
        c["rows"] = c["rows"] * 10
        with self.assertRaisesRegex(ValueError, "上限"):
            assess_chart(c, FakeLocal("{}"))


if __name__ == "__main__":
    unittest.main()
