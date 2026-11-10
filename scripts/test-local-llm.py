#!/usr/bin/env python3
"""Opt-in synthetic API integration against a verified local ControlDeck runtime.
Run from the repository: PYTHONPATH=. python3 scripts/test-local-llm.py --verified-local
No production data or credentials are read. Does not load/unload models.
"""
import argparse
import json
import time
from tests.helpers import Client, LiveServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8097/v1")
    parser.add_argument("--model", default="Qwen3.8-27B")
    parser.add_argument("--verified-local", action="store_true", required=True,
                        help="confirm the runtime is local inference, not a cloud relay")
    args = parser.parse_args()
    srv = LiveServer()
    try:
        srv.app.providers.save([{"id": "controldeck-local", "type": "openai",
            "base_url": args.base_url, "model": args.model, "local_only_verified": True,
            "options": {"max_tokens": 1800, "temperature": 0.2}}], "controldeck-local")
        client = Client(srv.base)
        original_open = client.opener.open
        client.opener.open = lambda req, timeout=20: original_open(req, timeout=180)
        client.login_setup()
        st, project = client.call("POST", "/api/v1/patents", {
            "title": "合成テスト: 雨水を集める植木鉢",
            "data": {"problem": "不在中に植物が乾燥する", "solution": "雨水を貯留して給水する"}})
        assert st == 200, st
        before = client.call("GET", "/api/v1/patents/%s" % project["id"])[1]
        start = time.monotonic()
        st, result = client.call("POST", "/api/v1/patents/%s/assist" % project["id"],
            {"task": "idea", "provider": "controldeck-local", "extra": "検証用。確認すべき点を3つ、簡潔に提示してください。"})
        assert st == 200, st
        assert result.get("answer", "").strip(), "empty model answer"
        after = client.call("GET", "/api/v1/patents/%s" % project["id"])[1]
        assert before == after, "AI assistance unexpectedly changed project"
        print(json.dumps({"passed": True, "model": result.get("model"),
            "provider": "controldeck-local", "elapsed_s": round(time.monotonic()-start, 2),
            "answer_chars": len(result["answer"]), "project_unchanged": True}, ensure_ascii=False))
    finally:
        srv.close()


if __name__ == "__main__":
    main()
