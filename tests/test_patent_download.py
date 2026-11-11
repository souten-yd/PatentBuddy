import io
import unittest
from unittest.mock import patch, Mock
from qnaplibrary import patent_download as dl
from qnaplibrary.connectors import ConnectorError
from tests.helpers import LiveServer, Client


class DownloadTests(unittest.TestCase):
    def test_only_publication_numbers_not_urls(self):
        self.assertEqual(dl.publication('ep 1004359 b1'),'EP1004359NWB1')
        for value in (None,True,'https://127.0.0.1/','EP1004359B1/../../','JP1004359B1','EP1004359B1?x=1'):
            with self.assertRaises(ConnectorError):dl.download(value)

    def test_response_validation_and_release(self):
        for raw, headers, valid in ((b'%PDF-1.7\ncontent',{},True),(b'<html>error</html>',{},False),
                                    (b'%PDF-1.7',{'Content-Length':'100'},False),
                                    (b'%PDF-1.7',{'Content-Length':str(dl.MAX_BYTES+1)},False)):
            response=io.BytesIO(raw);response.headers=headers
            with patch.object(dl.urllib.request,'build_opener',return_value=Mock(open=Mock(return_value=response))),patch.object(dl.time,'sleep'):
                if valid:self.assertEqual(dl.download('EP1004359B1')[1],raw)
                else:
                    with self.assertRaises(ConnectorError):dl.download('EP1004359B1')
            self.assertFalse(dl._lock.locked())
        response=io.BytesIO(b'%PDF-'+b'x'*20);response.headers={}
        with patch.object(dl,'MAX_BYTES',10),patch.object(dl.urllib.request,'build_opener',return_value=Mock(open=Mock(return_value=response))),patch.object(dl.time,'sleep'):
            with self.assertRaises(ConnectorError):dl.download('EP1004359B1')
        self.assertFalse(dl._lock.locked())

    def test_redirect_and_concurrent_requests_rejected(self):
        with self.assertRaises(ConnectorError):dl.NoRedirect().redirect_request(None,None,302,'',{},'http://localhost/')
        dl._lock.acquire()
        try:
            with self.assertRaises(ConnectorError):dl.download('EP1004359B1')
        finally:dl._lock.release()

    def test_admin_csrf_confirmation_and_binary_download(self):
        server=LiveServer();self.addCleanup(server.close)
        admin=Client(server.base);admin.login_setup()
        path='/api/v1/patent-downloads/epo';body={'publication':'EP1004359B1','confirm_public':True}
        with patch.object(dl,'download',return_value=('EP1004359B1.pdf',b'%PDF-synthetic')) as fetch:
            self.assertEqual(Client(server.base).call('POST',path,body)[0],401)
            device=Client(server.base);device.token=server.app.auth.create_device('reader','ro')['token']
            self.assertEqual(device.call('POST',path,body)[0],403)
            csrf=admin.csrf;admin.csrf='wrong'
            self.assertEqual(admin.call('POST',path,body)[0],403);admin.csrf=csrf
            self.assertEqual(admin.call('POST',path,dict(body,confirm_public=1))[0],400)
            self.assertEqual(admin.call('POST',path,dict(body,publication='https://evil.example/'))[0],400)
            fetch.assert_not_called()
            status,raw=admin.call('POST',path,body,raw=True)
            self.assertEqual((status,raw),(200,b'%PDF-synthetic'));fetch.assert_called_once()
