from __future__ import annotations

import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from pydantic import BaseModel

from dev_workflow_standards_tools.infrastructure import openai_client


class _ProxyHandler(BaseHTTPRequestHandler):
    requests: list[str] = []
    connects: list[str] = []

    def do_POST(self) -> None:
        type(self).requests.append(self.path)
        self.send_response(502)
        self.send_header("Content-Length", str(len(b"synthetic proxy failure")))
        self.end_headers()
        self.wfile.write(b"synthetic proxy failure")

    def do_CONNECT(self) -> None:
        type(self).connects.append(self.path)
        self.send_response(502)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class _OriginHandler(BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_POST(self) -> None:
        type(self).requests.append(self.path)
        self.send_response(502)
        self.send_header("Content-Length", str(len(b"synthetic origin failure")))
        self.end_headers()
        self.wfile.write(b"synthetic origin failure")

    def log_message(self, format: str, *args: object) -> None:
        return


class _ParsedContent(BaseModel):
    value: str


class OpenAIProxyTests(unittest.TestCase):
    def start_server(self, handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, threading.Thread]:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, thread

    def capture_http_clients(self) -> tuple[list[object], object]:
        created: list[object] = []
        client_type = openai_client.httpx2.Client

        class CapturedClient(client_type):
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__(*args, **kwargs)
                created.append(self)

        return created, patch.object(openai_client.httpx2, "Client", CapturedClient)

    def test_sdk_initialization_failure_closes_created_transport(self) -> None:
        created, client_patch = self.capture_http_clients()
        env = {
            "OPENAI_API_KEY": "sk-test-proxy-key-value",
            "OPENAI_BASE_URL": "https://api.synthetic.invalid/v1",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            client_patch,
            patch.object(openai_client, "OpenAI", side_effect=RuntimeError("synthetic SDK failure")),
        ):
            with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                openai_client.create_decision([], [])
        self.assertEqual(raised.exception.error_code, "client_initialization_failed")
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].is_closed)

    def test_http_proxy_variables_route_sdk_request_to_proxy(self) -> None:
        _ProxyHandler.requests = []
        proxy, _ = self.start_server(_ProxyHandler)
        proxy_url = f"http://127.0.0.1:{proxy.server_port}"
        for proxy_name in ("http_proxy", "HTTP_PROXY", "ALL_PROXY"):
            _ProxyHandler.requests = []
            env = {
                "OPENAI_API_KEY": "sk-test-proxy-key-value",
                "OPENAI_BASE_URL": "http://api.synthetic.invalid/v1",
                proxy_name: proxy_url,
                "no_proxy": "",
            }
            with self.subTest(proxy_name=proxy_name), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                    openai_client.create_decision([], [])
            self.assertEqual(raised.exception.error_code, "api_status_error")
            self.assertNotIn(proxy_url, str(raised.exception))
            self.assertEqual(len(_ProxyHandler.requests), 1)
            self.assertTrue(_ProxyHandler.requests[0].startswith("http://api.synthetic.invalid/"))

    def test_https_proxy_uses_connect_and_parse_response_path(self) -> None:
        _ProxyHandler.connects = []
        proxy, _ = self.start_server(_ProxyHandler)
        proxy_url = f"http://127.0.0.1:{proxy.server_port}"
        for proxy_name in ("https_proxy", "HTTPS_PROXY"):
            _ProxyHandler.connects = []
            env = {
                "OPENAI_API_KEY": "sk-test-proxy-key-value",
                "OPENAI_BASE_URL": "https://api.synthetic.invalid/v1",
                proxy_name: proxy_url,
                "no_proxy": "",
            }
            with self.subTest(proxy_name=proxy_name), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                    openai_client.parse_response(
                        instructions="Return a value.",
                        input="Synthetic input.",
                        text_format=_ParsedContent,
                        reasoning_effort="medium",
                        max_output_tokens=16,
                    )
            self.assertEqual(raised.exception.error_code, "api_connection_failed")
            self.assertEqual(_ProxyHandler.connects, ["api.synthetic.invalid:443"])

    def test_no_proxy_routes_to_local_origin_without_contacting_proxy(self) -> None:
        _ProxyHandler.requests = []
        _OriginHandler.requests = []
        proxy, _ = self.start_server(_ProxyHandler)
        origin, _ = self.start_server(_OriginHandler)
        env = {
            "OPENAI_API_KEY": "sk-test-proxy-key-value",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{origin.server_port}/v1",
            "HTTP_PROXY": f"http://127.0.0.1:{proxy.server_port}",
            "NO_PROXY": "127.0.0.1",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                openai_client.create_decision([], [])
        self.assertEqual(raised.exception.error_code, "api_status_error")
        self.assertEqual(len(_OriginHandler.requests), 1)
        self.assertEqual(_ProxyHandler.requests, [])

    def test_sdk_closes_transport_after_success_and_request_failures(self) -> None:
        created, client_patch = self.capture_http_clients()
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "sk-test-proxy-key-value",
            "OPENAI_BASE_URL": "https://api.synthetic.invalid/v1",
        }, clear=True), client_patch:
            result = openai_client._invoke({"ok": True}, lambda _client: {"ok": True})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(created), 1)
        self.assertTrue(created[-1].is_closed)

        _ProxyHandler.requests = []
        proxy, _ = self.start_server(_ProxyHandler)
        created, client_patch = self.capture_http_clients()
        env = {
            "OPENAI_API_KEY": "sk-test-proxy-key-value",
            "OPENAI_BASE_URL": "http://api.synthetic.invalid/v1",
            "http_proxy": f"http://127.0.0.1:{proxy.server_port}",
            "no_proxy": "",
        }
        with patch.dict(os.environ, env, clear=True), client_patch:
            with self.assertRaises(openai_client.OpenAIWorkflowError):
                openai_client.create_decision([], [])
        self.assertEqual(len(_ProxyHandler.requests), 1)
        self.assertEqual(len(created), 1)
        self.assertTrue(created[-1].is_closed)

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            refused_port = listener.getsockname()[1]
        created, client_patch = self.capture_http_clients()
        env["http_proxy"] = f"http://127.0.0.1:{refused_port}"
        with patch.dict(os.environ, env, clear=True), client_patch:
            with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                openai_client.create_decision([], [])
        self.assertEqual(raised.exception.error_code, "api_connection_failed")
        self.assertEqual(len(created), 1)
        self.assertTrue(created[-1].is_closed)

    def test_bad_proxy_configuration_fails_before_sdk_creation(self) -> None:
        env = {
            "OPENAI_API_KEY": "sk-test-proxy-key-value",
            "OPENAI_BASE_URL": "http://api.synthetic.invalid/v1",
            "http_proxy": "http://127.0.0.1:invalid-port",
            "no_proxy": "",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(
            openai_client, "OpenAI"
        ) as sdk_factory:
            with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                openai_client.create_decision([], [])
        self.assertEqual(raised.exception.error_code, "client_initialization_failed")
        sdk_factory.assert_not_called()

    def test_unavailable_proxy_never_falls_back_to_local_origin(self) -> None:
        _OriginHandler.requests = []
        origin, _ = self.start_server(_OriginHandler)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            refused_port = listener.getsockname()[1]
        env = {
            "OPENAI_API_KEY": "sk-test-proxy-key-value",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{origin.server_port}/v1",
            "http_proxy": f"http://127.0.0.1:{refused_port}",
            "no_proxy": "",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                openai_client.create_decision([], [])
        self.assertEqual(raised.exception.error_code, "api_connection_failed")
        self.assertEqual(_OriginHandler.requests, [])


if __name__ == "__main__":
    unittest.main()
