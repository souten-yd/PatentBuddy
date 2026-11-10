"""Unread POST bodies must not become the next HTTP request line."""
import http.client
import json
import unittest
from unittest import mock

from tests.helpers import Client, LiveServer


class KeepAliveTest(unittest.TestCase):
    def test_update_check_body_does_not_poison_next_request(self):
        srv = LiveServer()
        try:
            client = Client(srv.base)
            client.login_setup()
            cookie = "; ".join(c.name + "=" + c.value for c in client.jar)
            conn = http.client.HTTPConnection("127.0.0.1", srv.httpd.server_port, timeout=5)
            try:
                with mock.patch.object(srv.app.updater, "check", return_value=None):
                    conn.request("POST", "/api/update/check", "{}", {
                        "Cookie": cookie, "X-CSRF-Token": client.csrf, "Content-Type": "application/json"})
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                conn.request("GET", "/api/health")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())["ok"])
            finally:
                conn.close()
        finally:
            srv.close()

    def test_ambiguous_lengths_and_unauthorized_body_close_connection(self):
        srv = LiveServer()
        try:
            for invalid in (False, True):
                with self.subTest(duplicate_length=invalid):
                    conn = http.client.HTTPConnection("127.0.0.1", srv.httpd.server_port, timeout=5)
                    try:
                        conn.putrequest("POST", "/api/update/check")
                        if invalid:
                            conn.putheader("Content-Length", "0")
                        conn.putheader("Content-Length", "2")
                        conn.endheaders(b"{}")
                        response = conn.getresponse()
                        self.assertEqual(response.status, 400 if invalid else 401)
                        self.assertEqual(response.getheader("Connection"), "close")
                        response.read()
                        conn.request("GET", "/api/health")
                        response = conn.getresponse()
                        self.assertEqual(response.status, 200)
                        response.read()
                    finally:
                        conn.close()
        finally:
            srv.close()
