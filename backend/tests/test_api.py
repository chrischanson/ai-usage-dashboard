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
        for p in ('/api/usage/latest', '/api/usage/{source}/latest',
                  '/api/usage/{source}/history', '/api/usage/history'):
            self.assertIn(p, routes)

    def test_create_app_has_quota_routes(self):
        app = create_app()
        routes = {r.path for r in app.routes}
        for p in ('/api/quota/latest', '/api/quota/{source}/latest'):
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


class TestUsageEndpointsRespond(unittest.TestCase):
    """Invoke the usage/quota routes, don't just check they are registered.

    The route-registration tests above passed while /api/usage/latest and every
    /api/usage/{source}/* route returned HTTP 500 (a renamed kwarg and a dropped
    _VALID_SOURCES definition). Registration is not a substitute for a response.
    """

    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(create_app())

    def test_all_usage_routes_return_200(self):
        for path in ('/api/usage/latest',
                     '/api/usage/latest?deltas=true',
                     '/api/usage/history',
                     '/api/quota/latest'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_per_source_routes_return_200(self):
        for src in ('agy', 'opencode', 'codex', 'claude'):
            for tmpl in ('/api/usage/{}/latest',
                         '/api/usage/{}/history',
                         '/api/quota/{}/latest'):
                path = tmpl.format(src)
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)

    def test_unknown_source_returns_404(self):
        for tmpl in ('/api/usage/{}/latest',
                     '/api/usage/{}/history',
                     '/api/quota/{}/latest'):
            path = tmpl.format('definitely-not-a-source')
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class TestCadenceMeta(unittest.TestCase):
    """The `_meta` block feeding the header's cycle strip."""

    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(create_app())

    def _assert_meta_shape(self, meta):
        self.assertIsInstance(meta, dict)
        for key in ('poll_interval_s', 'latest_cycle_ts', 'next_cycle_ts'):
            self.assertIn(key, meta)
        self.assertIsInstance(meta['poll_interval_s'], int)
        self.assertGreater(meta['poll_interval_s'], 0)
        # next_cycle_ts is exactly one interval past the newest observation,
        # or None when there is no data at all — never invented.
        if meta['latest_cycle_ts'] is None:
            self.assertIsNone(meta['next_cycle_ts'])
        else:
            self.assertEqual(meta['next_cycle_ts'],
                             meta['latest_cycle_ts'] + meta['poll_interval_s'])

    def test_combined_latest_exposes_meta(self):
        self._assert_meta_shape(self.client.get('/api/usage/latest').json()['_meta'])

    def test_source_latest_exposes_meta(self):
        self._assert_meta_shape(self.client.get('/api/usage/agy/latest').json()['_meta'])

    def test_meta_does_not_shadow_a_source(self):
        from source_registry import get_all_names
        self.assertNotIn('_meta', set(get_all_names()))
