import unittest

from nfi_account.origin import is_same_origin
from starlette.requests import Request


class OriginTests(unittest.TestCase):
  def request(self, origin=None, site=None, **headers):
    values = {"host": "internal.test:8080", **headers}
    if origin is not None:
      values["origin"] = origin
    if site is not None:
      values["sec-fetch-site"] = site
    return Request(
      {
        "type": "http",
        "scheme": "http",
        "server": ("internal.test", 8080),
        "path": "/api/v1/live-settings",
        "headers": [(key.encode(), value.encode()) for key, value in values.items()],
      }
    )

  def test_browser_same_origin_survives_host_rewriting_and_tls_termination(self):
    self.assertTrue(is_same_origin(self.request("https://console.example.test", "same-origin")))
    self.assertTrue(is_same_origin(self.request("http://127.0.0.1:18081", "same-origin")))
    self.assertFalse(is_same_origin(self.request("https://console.example.test", "same-origin"), allow_proxy=False))

  def test_cross_site_and_same_site_other_origins_remain_rejected(self):
    for site in (None, "cross-site", "same-site", "none", "invalid"):
      with self.subTest(site=site):
        self.assertFalse(is_same_origin(self.request("https://evil.test", site)))
    self.assertFalse(is_same_origin(self.request("http://internal.test:8080", "cross-site")))
    self.assertFalse(is_same_origin(self.request(site="cross-site")))

  def test_forwarding_headers_alone_do_not_authorize_other_origins(self):
    request = self.request(
      "https://evil.test",
      **{"x-forwarded-host": "evil.test", "x-forwarded-proto": "https", "forwarded": "host=evil.test;proto=https"},
    )
    self.assertFalse(is_same_origin(request))

  def test_direct_clients_default_ports_and_host_case(self):
    self.assertTrue(is_same_origin(self.request()))
    self.assertTrue(is_same_origin(self.request("http://INTERNAL.TEST:8080")))
    self.assertTrue(is_same_origin(self.request("http://internal.test:80", host="internal.test")))
    self.assertFalse(is_same_origin(self.request("http://internal.test:0", host="internal.test")))

  def test_malformed_and_duplicate_origins_are_rejected_even_with_metadata(self):
    for origin in (
      "null",
      "https://",
      "https://evil.test/path",
      "https://user:password@evil.test",
      "https://evil.test?token=hidden",
      "https://evil.test#hidden",
      "https://evil.test:invalid",
      "https://[",
      "https://evil.test https://other.test",
    ):
      with self.subTest(origin=origin):
        self.assertFalse(is_same_origin(self.request(origin, "same-origin")))
    request = self.request("http://internal.test:8080", "same-origin")
    request.scope["headers"].append((b"origin", b"https://evil.test"))
    self.assertFalse(is_same_origin(request))
