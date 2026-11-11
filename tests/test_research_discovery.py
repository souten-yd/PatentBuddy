import copy
import io
import unittest
from unittest.mock import patch, Mock
from qnaplibrary import research_discovery as discovery
from qnaplibrary.connectors import ConnectorError
from tests.helpers import LiveServer, Client


def response(total='2'):
    document = {'@country':'EP','@doc-number':'1004359','@kind':'B1','@family-id':'123',
                'bibliographic-data':{'invention-title':{'@lang':'en','$':'Synthetic inverter'},
                                     'classifications-ipcr':{'classification-ipcr':{'text':{'$':'H02M 1/00'}}}}}
    return {'ops:world-patent-data':{'ops:biblio-search':{'@total-result-count':total,
            'ops:search-result':{'exchange-documents':{'exchange-document':[document, copy.deepcopy(document)]}}}}}


class DiscoveryTests(unittest.TestCase):
    def test_grouped_results_keep_provenance_and_report_truncation(self):
        with patch.object(discovery, '_request', side_effect=[{'access_token':'synthetic'}, response('100')]) as request, patch.object(discovery.time,'sleep'):
            result=discovery.search('ta=inverter',25,'key','secret')
        self.assertEqual(result['fetched'],2)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['reported_total'],100)
        self.assertEqual(result['records'][0]['family'],'epo:123')
        self.assertEqual(result['records'][0]['cells'],['IPC:H02M 1/00'])
        self.assertEqual(request.call_args.args[1]['X-OPS-Range'],'1-25')
        self.assertNotIn('secret',str(result))
        self.assertFalse(discovery._lock.locked())

    def test_invalid_results_fail_closed_and_release_lock(self):
        bad=response();bad['ops:world-patent-data']['ops:biblio-search']['@total-result-count']=True
        for value in ({},bad,response('0'),response('1')):
            with patch.object(discovery,'_request',side_effect=[{'access_token':'synthetic'},value]),patch.object(discovery.time,'sleep'):
                with self.assertRaises(ConnectorError):discovery.search('q',25,'key','secret')
            self.assertFalse(discovery._lock.locked())
        with patch.object(discovery,'_request') as request:
            for query,limit,key in [('',25,'key'),('q',True,'key'),('q',101,'key'),('q',25,'')]:
                with self.assertRaises(ConnectorError):discovery.search(query,limit,key,'secret')
            request.assert_not_called()

    def test_transport_rejects_redirect_oversize_and_provider_error_body(self):
        with self.assertRaises(ConnectorError):discovery.NoRedirect().redirect_request(None,None,302,'',{},'https://other.example/')
        for data in (b'x'*9,b'<secret>'):
            with patch.object(discovery,'MAX_BYTES',8),patch.object(discovery.urllib.request,'build_opener',return_value=Mock(open=Mock(return_value=io.BytesIO(data)))):
                with self.assertRaises(ConnectorError) as error:discovery._request('auth/accesstoken',{})
                self.assertNotIn('<secret>',str(error.exception))

    def test_api_confirmation_missing_keys_and_saved_metadata(self):
        server=LiveServer();self.addCleanup(server.close)
        admin=Client(server.base);admin.login_setup()
        path='/api/v1/research/discover/epo';body={'query':'ta=inverter','limit':25,'confirm_public':True}
        with patch.object(discovery,'search') as search:
            self.assertEqual(Client(server.base).call('POST',path,body)[0],401)
            self.assertEqual(admin.call('POST',path,dict(body,confirm_public=1))[0],403)
            self.assertEqual(admin.call('POST',path,dict(body,limit=True))[0],400)
            self.assertEqual(admin.call('POST',path,body)[0],409)
            search.assert_not_called()
        with patch.object(discovery,'_request',side_effect=[{'access_token':'synthetic'},response('100')]),patch.object(discovery.time,'sleep'):
            result=discovery.search('ta=inverter',25,'key','secret')
        with patch.object(server.app.config,'secret',return_value='synthetic'),patch.object(discovery,'search',return_value=result):
            status,saved=admin.call('POST',path,body)
        self.assertEqual(status,200)
        self.assertEqual(saved['snapshot']['unique_publications'],1)
        stored=admin.call('GET','/api/v1/research/snapshots/'+saved['snapshot']['revision'])[1]
        self.assertEqual(stored['discovery']['query'],'ta=inverter')
        self.assertEqual(stored['discovery']['reported_total'],100)
        self.assertIsNone(stored['selection'])
        self.assertEqual(server.app.store.one('SELECT count(*) FROM documents')[0],0)
