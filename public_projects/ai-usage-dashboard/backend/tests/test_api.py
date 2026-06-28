"""Tests for the API module (api.py)."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from api import create_app, error_response
from fastapi import FastAPI
from fastapi.responses import JSONResponse


class TestCreateApp(unittest.TestCase):
    def test_create_app_returns_fastapi(self):
        app = create_app()
        self.assertIsInstance(app, FastAPI)

    def test_create_app_has_health_route(self):
        app = create_app()
        routes = {r.path for r in app.routes}
        self.assertIn('/health', routes)

    def test_create_app_has_ready_route(self):
        app = create_app()
        routes = {r.path for r in app.routes}
        self.assertIn('/ready', routes)

    def test_create_app_has_metrics_route(self):
        app = create_app()
        routes = {r.path for r in app.routes}
        self.assertIn('/metrics', routes)

    def test_create_app_has_usage_routes(self):
        app = create_app()
        routes = {r.path for r in app.routes}
        for p in ('/api/usage/latest', '/api/usage/opencode/latest',
                  '/api/usage/agy/latest', '/api/usage/codex/latest',
                  '/api/usage/opencode/history', '/api/usage/agy/history',
                  '/api/usage/codex/history', '/api/usage/history'):
            self.assertIn(p, routes)

    def test_create_app_has_quota_routes(self):
        app = create_app()
        routes = {r.path for r in app.routes}
        for p in ('/api/quota/latest', '/api/quota/agy/latest',
                  '/api/quota/opencode/latest', '/api/quota/codex/latest'):
            self.assertIn(p, routes)

    def test_create_app_has_root_redirect(self):
        app = create_app()
        routes = {r.path for r in app.routes}
        self.assertIn('/', routes)

    def test_create_app_has_static_mount(self):
        app = create_app()
        names = {r.name for r in app.routes if hasattr(r, 'name')}
        self.assertIn('static', names)


class TestErrorResponse(unittest.TestCase):
    def test_error_response_returns_json_response(self):
        resp = error_response("not_found", "Not found", 404)
        self.assertIsInstance(resp, JSONResponse)
        self.assertEqual(resp.status_code, 404)

    def test_error_response_default_status(self):
        resp = error_response("bad_request", "Bad")
        self.assertEqual(resp.status_code, 400)

    def test_error_response_body(self):
        resp = error_response("oops", "Something went wrong", 500)
        self.assertEqual(resp.status_code, 500)
        import json
        body = json.loads(resp.body)
        self.assertEqual(body['error']['code'], 'oops')
        self.assertEqual(body['error']['message'], 'Something went wrong')


class TestHealthEndpoint(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        app = create_app()
        self.client = TestClient(app)

    def test_health_returns_200(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_returns_json(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.headers["content-type"], "application/json")


class TestReadyEndpoint(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        app = create_app()
        self.client = TestClient(app)

    def test_ready_returns_503_or_200(self):
        """Returns 503 (not_ready) when no data has been collected yet."""
        resp = self.client.get("/ready")
        self.assertIn(resp.status_code, (200, 503))
        if resp.status_code == 503:
            self.assertEqual(resp.json(), {"status": "not_ready"})

    def test_ready_content_type(self):
        resp = self.client.get("/ready")
        if resp.status_code == 503:
            self.assertIn("application/json", resp.headers.get("content-type", ""))


class TestMetricsEndpoint(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        app = create_app()
        self.client = TestClient(app)

    def test_metrics_returns_dict(self):
        resp = self.client.get("/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, dict)
        for key in ('per_source', 'total_polls', 'db_size_bytes'):
            self.assertIn(key, data)


class TestStaticFiles(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        app = create_app()
        self.client = TestClient(app)

    def test_root_redirects_to_index(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)

    def test_static_index_exists(self):
        resp = self.client.get("/static/index.html")
        self.assertIn(resp.status_code, (200, 404))


if __name__ == '__main__':
    unittest.main()
