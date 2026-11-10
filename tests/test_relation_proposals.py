import copy
import json
import unittest
from unittest.mock import Mock
from qnaplibrary import relation_proposals as proposals
from qnaplibrary.store import StoreError
from tests.helpers import LiveServer, Client


class RelationProposalTests(unittest.TestCase):
    def setUp(self):
        self.server=LiveServer(); self.addCleanup(self.server.close)
        self.client=Client(self.server.base); self.client.login_setup()
        self.store=self.server.app.store
        self.client.call('POST','/api/v1/collections',{'name':'relations'})
        self.client.call('POST','/api/v1/collections/relations/documents',{'documents':[
            {'id':'source','body':'😀電池の抵抗が高い。固体電解質層を薄くして抵抗を下げる。'}]})
        self.doc=self.store.get_document(self.store.one('SELECT id FROM documents')[0])
        self.session=Mock()
        self.session.generation_provenance=dict(execution_policy='local_only',revision_kind='host_process_file_metadata_v1',model_ref='a'*64,runtime_ref='b'*64)
        self.proposal=dict(relation='problem',concept='高抵抗',confidence=0.8,quote='電池の抵抗が高い。')
        self.session.stream.return_value=json.dumps({'proposals':[self.proposal]},ensure_ascii=False)

    def save(self, value):
        return self.store.save_analysis(self.doc['id'],dict(id='relation-test',kind='relations',
            source_revision=self.doc['revision'],content=json.dumps(value,ensure_ascii=False)))

    def test_generation_exact_unicode_storage_and_no_graph_promotion(self):
        value=json.loads(proposals.generate(self.session,self.doc))
        self.assertEqual(value['proposals'][0]['start'],1)
        self.assertIs(self.session.stream.call_args.kwargs['require_provenance'],True)
        self.save(value); before=self.store.db.total_changes; self.save(value)
        self.assertEqual(before,self.store.db.total_changes)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM graph_edges')[0],0)
        self.assertEqual(self.store.list_analyses(self.doc['id'])['items'][0]['review_status'],'unreviewed')
        self.client.call('POST','/api/v1/collections/relations/documents',{'documents':[{'id':'source','body':'変更'}]})
        self.assertTrue(self.store.list_analyses(self.doc['id'])['items'][0]['stale'])
        with self.assertRaises(StoreError):self.save(value)

    def test_atomic_rejection_of_forgery_and_approval(self):
        base=json.loads(proposals.generate(self.session,self.doc))
        values=[]
        for field,new in [('basis','factual'),('review_status','approved'),('source_revision','b'*64),('generation',{})]:
            v=copy.deepcopy(base);v[field]=new;values.append(v)
        for field,new in [('start',True),('quote','原文にない'),('relation','citation'),('confidence',float('nan'))]:
            v=copy.deepcopy(base);v['proposals'][0][field]=new;values.append(v)
        for value in values:
            with self.assertRaises(StoreError): self.save(value)
            self.assertEqual(self.store.one('SELECT COUNT(*) FROM document_analyses')[0],0)

    def test_model_must_not_invent_ambiguous_duplicate_or_excess_proposals(self):
        for value in ([dict(self.proposal,quote='抵抗')],[self.proposal]*2,[self.proposal]*13,
                      [dict(self.proposal,confidence=True)],[dict(self.proposal,approved=True)]):
            self.session.stream.return_value=json.dumps({'proposals':value})
            with self.assertRaises(StoreError):proposals.generate(self.session,self.doc)
        self.session.stream.return_value='{"proposals":[]}'
        self.save(json.loads(proposals.generate(self.session,self.doc)))
