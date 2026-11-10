import copy
import unittest
from qnaplibrary.retrieval_contract import validate_result
from qnaplibrary.addon_client import AddonError
from tests import test_addon_host


class RetrievalTests(unittest.TestCase):
    def test_attestation_and_vector_shape(self):
        value={'execution_policy':'local_only','revision_kind':'host_file_metadata_v1','model_ref':'a'*64,
               'dimensions':2,'vectors':[[1,0],[0,1]]}
        self.assertEqual(validate_result(value,'text.embed',2,'a'*64),value)
        for key,bad in [('execution_policy','cloud'),('model_ref','b'*64),('dimensions',True),('vectors',[[1,0]])]:
            changed=copy.deepcopy(value);changed[key]=bad
            with self.assertRaises(AddonError):validate_result(changed,'text.embed',2,'a'*64)
        for bad in (float('nan'),float('inf'),True):
            changed=copy.deepcopy(value);changed['vectors'][0][0]=bad
            with self.assertRaises(AddonError):validate_result(changed,'text.embed',2,'a'*64)

    def test_rank_rows_cannot_be_dropped_or_duplicated(self):
        value={'execution_policy':'local_only','revision_kind':'host_file_metadata_v1','model_ref':'a'*64,
               'rankings':[{'index':1,'score':1.0},{'index':0,'score':0.5}]}
        validate_result(value,'text.rerank',2,'a'*64)
        value['rankings'][1]['index']=1
        with self.assertRaises(AddonError):validate_result(value,'text.rerank',2,'a'*64)

    def test_old_host_receives_no_private_text(self):
        from unittest.mock import Mock
        _,session=test_addon_host.HostSessionTests().make_session();session.call=Mock(return_value={})
        with self.assertRaises(AddonError):session.retrieval('text.embed',['private'])
        self.assertEqual(session.call.call_args.args,('GET','/ai/retrieval/capabilities'))
        self.assertEqual(session.call.call_count,1)

    def test_cancel_closes_pending_retrieval_connection(self):
        import http.server
        import threading
        from unittest.mock import Mock
        received,release=threading.Event(),threading.Event()
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(b'{');self.wfile.flush();received.set();release.wait(3)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            _,session=test_addon_host.HostSessionTests().make_session()
            session.client.host_url='http://127.0.0.1:%d'%server.server_port
            session.call=Mock(return_value={'text.embed':{'available':True,'execution_policy':'local_only',
                'revision_kind':'host_file_metadata_v1','model_ref':'a'*64}})
            errors=[]
            def run():
                try:session.retrieval('text.embed',['synthetic'])
                except AddonError as error:errors.append(error.status)
            worker=threading.Thread(target=run,daemon=True);worker.start()
            self.assertTrue(received.wait(2));session.abort();worker.join(timeout=2)
            self.assertFalse(worker.is_alive());self.assertEqual(errors,[502])
        finally:
            release.set();server.shutdown();server.server_close();thread.join(timeout=2)
