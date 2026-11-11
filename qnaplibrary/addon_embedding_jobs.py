"""Host-owned indexing jobs; the canonical vector rows are the resume checkpoint."""
import re
import threading
import time
import uuid

from .addon_client import AddonError
from .addon_compute_host import ComputeHostSession
from .addon_host import owner_key
from .addon_jobs import AnalysisJobs
from .embedding_build import build, model_reference


class EmbeddingJobs(AnalysisJobs):
    state_filename = 'embedding-jobs.json'

    def __init__(self, client, data_dir):
        super().__init__(client, data_dir)
        self.threads = {}
        for job in self.jobs.values():
            if job['status'] == 'interrupted':
                job['host_sync_pending'] = True

    def start(self, headers, resume_id=None):
        if resume_id is not None and (not isinstance(resume_id, str) or not re.fullmatch('[a-f0-9]{32}', resume_id)):
            raise AddonError(400, '再開IDが不正です')
        session = ComputeHostSession(self.client, headers)
        model = model_reference(session)
        with self.lock:
            if self.stopping.is_set() or self.sessions:
                raise AddonError(429, '索引構築の終了を待ってください')
            if any(j.get('host_sync_pending') for j in self.jobs.values()):
                raise AddonError(409, '先に前回のHost状態を確認してください')
            if resume_id:
                old = self.jobs.get(resume_id)
                if not old or old['owner'] != session.owner or old['status'] not in ('failed', 'canceled', 'interrupted'):
                    raise AddonError(404, '再開できる索引ジョブがありません')
                if old['model_ref'] != model:
                    raise AddonError(409, 'モデルが変更されています。新しい索引構築を開始してください')
            if len(self.jobs) >= 32:
                raise AddonError(429, '終了した索引ジョブを履歴から除外してください')
            identifier = uuid.uuid4().hex
            host_id = session.create_job('PatentBuddy 検索索引構築')
            value = dict(id=identifier, host_job_id=host_id, owner=session.owner, kind='embedding',
                         model_ref=model, status='queued', phase='queued', created=time.time(),
                         completed_chunks=0, host_sync_pending=True, message='計算資源を待っています')
            self.jobs[identifier] = value
            self.sessions[identifier] = session
            try:
                self._save()
            except OSError:
                self.jobs.pop(identifier); self.sessions.pop(identifier)
                session.finish('failed')
                raise AddonError(503, '索引ジョブを保存できません') from None
            session.resource_changed = lambda: self._update(identifier, request_id=session.request_id, lease_id=session.lease_id)
            thread = threading.Thread(target=self._run_index, args=(identifier, session), daemon=True)
            self.threads[identifier] = thread
            thread.start()
            return self._public(value)

    def cancel(self, identifier, identity):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job['owner'] != owner_key(identity):
                raise AddonError(404, '索引ジョブがありません')
            if identifier in self.sessions:
                self.sessions[identifier].abort()
                self._update(identifier, phase='canceling', message='中断しています。保存済みの索引は保持します')
            return self._public(job)

    def reconcile(self, headers, identifier):
        session = ComputeHostSession(self.client, headers)
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job['owner'] != session.owner:
                raise AddonError(404, '索引ジョブがありません')
            if identifier in self.sessions:
                raise AddonError(409, '索引処理の終了を待ってください')
            session.job_id = job['host_job_id']
            session.request_id = job.get('request_id')
            session.lease_id = job.get('lease_id')
            session.release_cpu()
            status = 'canceled' if job['status'] == 'interrupted' else job['status']
            result = job.get('result') if status == 'succeeded' else None
            receipt = session.finish(status, result)
            matched = receipt.get('terminal_matches') is True or (status != 'succeeded' and receipt.get('status') == 'interrupted')
            self._update(identifier, status=status, phase='done' if status == 'succeeded' else status,
                         host_sync_pending=not matched, request_id=None, lease_id=None,
                         message='Host状態を確認しました。保存済みの索引は保持しています' if matched else 'Host状態を確認できません。ControlDeckのジョブを確認してください')
            return self._public(job)

    def _run_index(self, identifier, session):
        done = threading.Event()
        watcher = None
        last = [0.0]
        def progress(count):
            # Persist small progress metadata at most once every five seconds.
            if time.monotonic() - last[0] >= 5:
                self._update(identifier, completed_chunks=count, message='索引構築: %dチャンク保存済み' % count)
                last[0] = time.monotonic()
        def monitor():
            while not done.wait(5):
                try:
                    state = session.heartbeat()
                    if state.get('cancel_requested') or state.get('status') not in ('queued', 'running') or self.stopping.is_set():
                        session.abort(); return
                except Exception:
                    session.abort(); return
        try:
            session.acquire_cpu()
            # Start renewal only after activation; a partially activated lease
            # is not yet a valid heartbeat target.
            state = session.heartbeat()
            if state.get('cancel_requested') or state.get('status') not in ('queued', 'running'):
                session.abort()
            watcher = threading.Thread(target=monitor, daemon=True); watcher.start()
            self._update(identifier, status='running', phase='embedding', message='ローカルAIで検索索引を構築しています')
            result = build(self.client, session, self.jobs[identifier]['model_ref'], progress)
            with self.lock:
                if session.aborted.is_set() or self.stopping.is_set():
                    raise AddonError(409, '索引構築が中断されました')
                self._update(identifier, status='succeeded', phase='done', result=result,
                             completed_chunks=result['completed_chunks'], message='検索索引を構築しました')
        except Exception as error:
            status = 'canceled' if session.aborted.is_set() or self.stopping.is_set() else 'failed'
            self._update(identifier, status=status, phase=status,
                         error_code='http_%d' % error.status if isinstance(error, AddonError) else type(error).__name__,
                         message='索引構築を完了できませんでした。保存済みの部分から再開できます')
        finally:
            done.set()
            if watcher: watcher.join()
            try:
                session.release_cpu()
                self._update(identifier, request_id=None, lease_id=None)
                job = self.jobs[identifier]
                receipt = session.finish(job['status'], job.get('result') if job['status'] == 'succeeded' else None)
                self._update(identifier, host_sync_pending=receipt.get('terminal_matches') is not True)
            except Exception:
                self._update(identifier, host_sync_pending=True)
            finally:
                with self.lock:
                    self.sessions.pop(identifier, None)
                    self.threads.pop(identifier, None)

    def close(self):
        super().close()
        for thread in list(self.threads.values()):
            thread.join(timeout=35)
