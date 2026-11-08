import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from safety_dashboard.adapters.firestore_message_pipeline import FirestoreMessagePipelineStore
from safety_dashboard.adapters.firestore_message_records import FirestoreMessageRecordStore
from safety_dashboard.application.message_pipeline import AnalysisRunGate, MessageAnalysisQueue, stamp
from safety_dashboard.application.message_records import RecordConflict
from scripts.build_message_review_deploy_config import build_config
from tests.test_message_records import make_service, registration, NOW


class FakeFirestore:
    """A query/transaction spy, not an emulator or evidence of production IAM."""
    def __init__(self):
        self.documents, self.operations = {}, []

    def collection(self, path):
        client = self
        class Collection:
            def __init__(self): self.filters = []; self.maximum = None; self.order = None
            def document(self, key): return client.ref(path+"/"+key)
            def where(self, *, filter): self.filters.append(filter); return self
            def order_by(self, key): self.order = key; return self
            def limit(self, number): self.maximum = number; return self
            def stream(self, **kwargs):
                client.operations.append(("query", path, [(f.field_path, f.op_string) for f in self.filters], self.order, self.maximum))
                rows = [value for key, value in client.documents.items() if key.startswith(path+"/") and value.get("queue_key")]
                for field in self.filters:
                    rows = [r for r in rows if (r[field.field_path] >= field.value if field.op_string == ">=" else r[field.field_path] <= field.value)]
                return [Mock(to_dict=lambda row=row: copy.deepcopy(row)) for row in sorted(rows, key=lambda r:r[self.order])[:self.maximum]]
        return Collection()

    def ref(self, path):
        client = self
        class Ref:
            def get(self, **kwargs):
                client.operations.append(("get", path))
                value = client.documents.get(path)
                return Mock(exists=value is not None, to_dict=lambda: copy.deepcopy(value))
            def collection(self, name): return client.collection(path+"/"+name)
        ref = Ref(); ref.path = path
        return ref

    def transaction(self):
        return Mock(set=lambda ref, value: self.write(ref, value))

    def write(self, ref, value):
        self.operations.append(("set", ref.path))
        self.documents[ref.path] = copy.deepcopy(value)


class FirestorePipelineTests(unittest.TestCase):
    def test_budget_and_queue_use_only_dedicated_collection_and_single_field_query(self):
        client = FakeFirestore()
        store = FirestoreMessagePipelineStore(client=client, transaction_runner=lambda callback: callback)
        gate = AnalysisRunGate(store, now=lambda: NOW)
        gate.acquire("owner"); gate.release("owner")
        queue = MessageAnalysisQueue(store); record = make_service().register_manual(registration())["record"]
        queue.enqueue(record, NOW)
        self.assertEqual(len(queue.due(NOW)), 1)
        self.assertTrue(all(key.startswith("disaster_message_pipeline/") for key in client.documents))
        query = next(op for op in client.operations if op[0] == "query")
        self.assertEqual(query[2], [("queue_key", ">="), ("queue_key", "<=")])
        self.assertEqual(query[3:], ("queue_key", 20))
        # Every transactional batch reads all requested documents before any write.
        before = len(client.operations)
        store.run(["a", "b"], lambda values: ({"a": {"value": 1}, "b": {"value": 2}}, None))
        self.assertEqual([op[0] for op in client.operations[before:]], ["get", "get", "set", "set"])
        with self.assertRaises(ValueError): store.run(["a"], lambda values: ({"other": {}}, None))

    def test_firestore_observation_has_no_history_version_and_prevents_stale_source_commit(self):
        client = FakeFirestore()
        store = FirestoreMessageRecordStore(client=client, transaction_runner=lambda callback: callback)
        records = make_service(store=store)
        old = records.register_official(registration().canonical(), "ID", NOW.isoformat())["record"]
        fetched = (NOW.replace(minute=3)).isoformat()
        new = records.register_official(old["message"], "ID", fetched)["record"]
        self.assertEqual(new["version"], 1)
        self.assertEqual(len(client.documents), 2)
        old["note"] = "검토 중"
        saved = store.commit(old, 1, "note_saved")
        self.assertEqual(saved["official_fetched_at"], fetched)
        saved.update(content_hash="old-different", official_fetched_at=NOW.isoformat())
        with self.assertRaises(RecordConflict): store.commit(saved, 2, "source_changed")


class AutomationDeployTests(unittest.TestCase):
    def test_automation_requires_verified_feed_and_ai_fixed_versions(self):
        env = {"MESSAGE_COLLECTION_ENABLED": "true"}
        with self.assertRaises(ValueError): build_config(env)
        env.update(MESSAGE_COLLECTION_CONTRACT_VERIFIED="true", MESSAGE_REVIEW_AI_ENABLED="true", MESSAGE_REVIEW_FEED_ENABLED="true")
        with self.assertRaises(ValueError): build_config(env)
        env.update(MESSAGE_REVIEW_OPENAI_VERSION="1", MESSAGE_REVIEW_KAKAO_VERSION="2", MESSAGE_REVIEW_FEED_VERSION="3")
        config = build_config(env)
        self.assertIn("MESSAGE_COLLECTION_ENABLED=true", config["MESSAGE_REVIEW_ENV_VARS"])
        self.assertEqual(len(config["MESSAGE_REVIEW_SECRET_BINDINGS"].split(",")), 3)
        for name, value in (("MESSAGE_ANALYSIS_DAILY_LIMIT", "1000"), ("MESSAGE_COLLECTION_START_AT", "2026-11-08"), ("MESSAGE_COLLECTION_CATCHUP_DAYS", "1")):
            with self.assertRaises(ValueError): build_config({**env, name: value})

    def run_configure(self, enabled, missing=False, denied=False):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); log = folder/"calls.jsonl"
            fake = folder/"gcloud"
            fake.write_text("#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\na=sys.argv[1:]\nwith open(os.environ['MESSAGE_TEST_LOG'],'a') as f:f.write(json.dumps(a)+'\\n')\n"
                "if a[:3]==['scheduler','jobs','describe']:\n"
                " if os.environ.get('MESSAGE_TEST_DENIED')=='true':print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)\n"
                " if os.environ.get('MESSAGE_TEST_MISSING')=='true':print('NOT_FOUND',file=sys.stderr);sys.exit(1)\n"
                "if a[:3]==['run','services','describe']:print('https://fake-message-worker.invalid')\n")
            fake.chmod(0o700)
            env = {**os.environ, "PATH": str(folder)+os.pathsep+os.environ["PATH"], "MESSAGE_TEST_LOG": str(log),
                   "MESSAGE_TEST_DENIED": str(denied).lower(), "MESSAGE_TEST_MISSING": str(missing).lower(),
                   "MESSAGE_COLLECTION_ENABLED": str(enabled).lower(), "GCP_PROJECT_ID": "fake-project", "GCP_REGION": "fake-region",
                   "WORKER_IMAGE": "fake-image", "GITHUB_SHA": "fake-revision", "MESSAGE_REVIEW_ENV_VARS": "MESSAGE_COLLECTION_ENABLED=true",
                   "MESSAGE_REVIEW_SECRET_BINDINGS": "OPENAI_API_KEY=OPENAI_API_KEY:1,KAKAO_REST_API_KEY=KAKAO_REST_API_KEY:1,SAFETY_DATA_API_KEY=SAFETY_DATA_API_KEY:1"}
            result = subprocess.run(["bash", "scripts/configure_message_automation.sh"], env=env, text=True, capture_output=True, timeout=20)
            return result, [json.loads(line) for line in log.read_text().splitlines()]

    def test_disabled_deployment_pauses_only_message_schedules_and_fails_on_permission_error(self):
        result, calls = self.run_configure(False)
        self.assertEqual(result.returncode, 0, result.stderr)
        paused = [args[3] for args in calls if args[:3] == ["scheduler", "jobs", "pause"]]
        self.assertCountEqual(paused, ["safety-message-collect", "safety-message-analyze"])
        self.assertFalse(any(args[0] == "run" for args in calls))
        result, calls = self.run_configure(False, missing=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any("pause" in args for args in calls))
        result, _ = self.run_configure(False, denied=True)
        self.assertNotEqual(result.returncode, 0)

    def test_enabled_deployment_is_private_and_does_not_bind_notification_credentials(self):
        result, calls = self.run_configure(True, missing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        deployment = next(args for args in calls if args[:2] == ["run", "deploy"])
        self.assertEqual(deployment[2], "safety-message-worker")
        self.assertIn("--no-allow-unauthenticated", deployment)
        self.assertNotIn("TELEGRAM", str(calls)); self.assertNotIn("KMA_API_KEY", str(calls))
        schedules = [args for args in calls if args[:4] == ["scheduler", "jobs", "create", "http"]]
        self.assertEqual(len(schedules), 2)
        collect = next(args for args in schedules if args[4] == "safety-message-collect")
        self.assertIn("--schedule=*/15 * * * *", collect)
        self.assertTrue(all("--max-retry-attempts=0" in args for args in schedules))
        self.assertFalse(any("dispatch" in str(args) for args in calls))
        self.assertTrue(all("safety-alert-worker" not in str(args) for args in calls))
