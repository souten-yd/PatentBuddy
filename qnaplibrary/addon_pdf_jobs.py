"""PDF import lifecycle: Host authority, private scratch, canonical results only."""
import base64
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import time
import uuid

from .addon_client import AddonError
from .addon_host import owner_key
from .addon_jobs import AnalysisJobs
from .addon_pdf_host import PDFHostSession
from .pdf_extract import capabilities, extract_pdf
from .pdf_store import validate


class PDFJobs(AnalysisJobs):
    state_filename = 'pdf-jobs.json'

    def __init__(self, client, data_dir):
        self.work = Path(data_dir) / 'pdf-work'
        self.work.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.work.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('PDF scratch must be a private directory')
        fd = os.open(self.work / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.work_lock = os.fdopen(fd, 'rb')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for path in self.work.iterdir():
                if re.fullmatch(r'[a-f0-9]{32}', path.name):
                    if path.is_symlink() or not path.is_dir():
                        raise ValueError('invalid PDF scratch entry')
                    shutil.rmtree(path)
            super().__init__(client, data_dir)
        except Exception:
            self.work_lock.close()
            raise
        self.threads = {}

    def start(self, headers, grant_id, force_pages=None, resume_id=None):
        force_pages = [] if force_pages is None else force_pages
        if (not isinstance(force_pages, list) or len(force_pages) > 200
                or any(type(p) is not int or not 1 <= p <= 200 for p in force_pages)):
            raise AddonError(400, 'OCRページは1〜200の番号で指定してください')
        if not all(capabilities().values()):
            raise AddonError(503, 'PCにPopplerと日本語・英語Tesseractの実行環境が必要です')
        if resume_id is not None and (not isinstance(resume_id, str) or not re.fullmatch(r"[a-f0-9]{32}", resume_id)):
            raise AddonError(400, "再実行IDが不正です")
        session = PDFHostSession(self.client, headers)
        metadata = session.grant(grant_id)
        with self.lock:
            if self.stopping.is_set() or self.sessions:
                raise AddonError(429, 'PDF取り込みの完了を待ってください')
            if resume_id:
                old = self.jobs.get(resume_id)
                if not old or old['owner'] != session.owner or old['status'] not in ('failed', 'canceled', 'interrupted'):
                    raise AddonError(404, '再実行するPDFジョブがありません')
                if old.get('host_sync_pending'):
                    raise AddonError(409, '先に前回の保存・Host状態を確認してください')
            if len(self.jobs) >= 32:
                raise AddonError(429, '終了した取り込みを処理履歴から除外してください')
            identifier = uuid.uuid4().hex
            host_id = session.create_job('PatentBuddy PDF取り込み')
            value = {'id': identifier, 'host_job_id': host_id, 'owner': session.owner,
                     'doc_id': None, 'kind': 'pdf', 'created': time.time(), 'status': 'queued',
                     'phase': 'queued', 'message': 'CPU資源を待っています', 'host_sync_pending': True}
            if resume_id:
                value['resume_id'] = resume_id
            self.jobs[identifier] = value
            self.sessions[identifier] = session
            try:
                self._save()
            except OSError:
                self.jobs.pop(identifier); self.sessions.pop(identifier)
                session.finish('failed')
                raise AddonError(503, 'PDFジョブ状態を保存できません') from None
            thread = threading.Thread(target=self._run_pdf, args=(identifier, session, grant_id, metadata, force_pages), daemon=True)
            self.threads[identifier] = thread
            thread.start()
            return self._public(value)

    def cancel(self, identifier, identity):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job['owner'] != owner_key(identity):
                raise AddonError(404, 'PDFジョブがありません')
            if identifier in self.sessions and job['status'] in ('queued', 'running'):
                self.sessions[identifier].abort()
                self._update(identifier, phase='canceling', message='PDF取り込みを中断しています')
            return self._public(job)

    def _receipt(self, job):
        if not job.get('extraction_sha256'):
            return None
        try:
            return self.client.data('GET', '/api/v1/pdf-imports/' + job['extraction_sha256'])
        except AddonError as error:
            if error.status == 404:
                return None
            raise

    def reconcile(self, headers, identifier):
        session = PDFHostSession(self.client, headers)
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job['owner'] != session.owner:
                raise AddonError(404, 'PDFジョブがありません')
            if identifier in self.sessions:
                raise AddonError(409, 'PDF処理が終了していません')
            saved = self._receipt(job)
            status = 'succeeded' if saved else 'canceled' if job['status'] in ('interrupted', 'canceled') else 'failed'
            session.job_id = job['host_job_id']
            session.request_id = job.get('request_id')
            session.lease_id = job.get('lease_id')
            session.release_cpu()
            receipt = session.finish(status, {'doc_id': saved['doc_id']} if saved else None)
            matched = receipt.get('terminal_matches') is True or (not saved and receipt.get('status') == 'interrupted')
            self._update(identifier, status=status, phase='done' if saved else status,
                         doc_id=saved['doc_id'] if saved else None, host_sync_pending=not matched, request_id=None, lease_id=None,
                         message='取り込み済み資料を確認しました' if saved else '前回の取り込みは終了しています。再選択して実行できます。')
            return self._public(job)

    def _run_pdf(self, identifier, session, grant_id, metadata, forced):
        done = threading.Event()
        scratch = self.work / identifier
        def monitor():
            while not done.wait(5):
                try:
                    state = session.heartbeat()
                    if state.get('cancel_requested') or state.get('status') not in ('queued', 'running') or self.stopping.is_set():
                        session.abort(); return
                except Exception:
                    session.abort(); return
        watcher = threading.Thread(target=monitor, daemon=True); watcher.start()
        saved = None
        try:
            scratch.mkdir(mode=0o700)
            session.acquire_cpu()
            self._update(identifier, status='running', phase='downloading', message='選択したPDFを読み込んでいます')
            source = scratch / 'source.pdf'
            session.download(grant_id, source)
            last = [0.0]
            def progress(page, total):
                session.progress('extracting', page, total)
                if time.monotonic() - last[0] >= 1 or page == total:
                    self._update(identifier, phase='extracting', completed=page, total=total,
                                 message='PDF読み取り・OCR %d / %dページ' % (page, total))
                    last[0] = time.monotonic()
            result = extract_pdf(source, cancel=session.aborted, force_pages=forced, progress=progress,
                                 scratch_parent=scratch, image_directory=scratch / "images")
            raw = source.read_bytes()
            source_hash, extraction_hash, _ = validate(raw, result, metadata['name'][:300])
            state = session.heartbeat()
            with self.lock:
                if session.aborted.is_set() or self.stopping.is_set() or state.get('cancel_requested'):
                    raise AddonError(409, 'PDF処理を中断しました')
                old = self.jobs.get(self.jobs[identifier].get('resume_id'))
                if old and old.get('source_sha256') and old['source_sha256'] != source_hash:
                    raise AddonError(400, '再選択したPDFが前回の原本と一致しません')
                self._update(identifier, phase='saving', source_sha256=source_hash,
                             extraction_sha256=extraction_hash, message='原本と抽出結果を保存しています')
                saved = self.client.data('POST', '/api/v1/pdf-imports', {
                    'title': metadata['name'][:300], 'pdf_base64': base64.b64encode(raw).decode(), 'extraction': result,
                    'images': [{'id': image['id'], 'data_base64': base64.b64encode((scratch / 'images' / ('%d.png' % image['id'])).read_bytes()).decode()} for image in result.get('images', [])]})
                self._update(identifier, status='succeeded', phase='done', doc_id=saved['doc_id'],
                             message='PDFを取り込みました。OCR結果は原本と照合してください。')
        except Exception as error:
            # A lost POST response is not evidence that canonical storage failed.
            try:
                saved = self._receipt(self.jobs[identifier])
                status = 'succeeded' if saved else 'canceled' if session.aborted.is_set() else 'failed'
            except AddonError:
                status = 'interrupted'
            self._update(identifier, status=status, phase=status, doc_id=saved['doc_id'] if saved else None,
                         message='保存済み資料を確認しました' if saved else '取り込みを完了できませんでした。状態を確認して再実行してください。',
                         error_code=type(error).__name__)
        finally:
            done.set(); watcher.join(timeout=25)
            cleanup_ok = True
            self._update(identifier, request_id=session.request_id, lease_id=session.lease_id)
            try:
                session.release_cpu()
                self._update(identifier, request_id=None, lease_id=None)
            except Exception:
                cleanup_ok = False
            try:
                if scratch.exists(): shutil.rmtree(scratch)
            except OSError:
                cleanup_ok = False
            try:
                status = self.jobs[identifier]['status']
                if status != 'interrupted':
                    receipt = session.finish(status, {'doc_id': saved['doc_id']} if saved else None)
                    self._update(identifier, host_sync_pending=not (cleanup_ok and receipt.get('terminal_matches') is True))
            except Exception:
                self._update(identifier, host_sync_pending=True)
            with self.lock:
                self.sessions.pop(identifier, None)
                self.threads.pop(identifier, None)

    def close(self):
        super().close()
        for thread in list(self.threads.values()):
            thread.join(timeout=35)
        if not self.threads:
            self.work_lock.close()
