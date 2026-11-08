"""Check browser request origins without trusting arbitrary forwarding headers."""

from urllib.parse import urlsplit


def normalized_origin(value):
  try:
    parts = urlsplit(value)
    if (
      parts.scheme not in ("http", "https")
      or not parts.hostname
      or parts.username is not None
      or parts.password is not None
      or parts.path not in ("", "/")
      or parts.query
      or parts.fragment
      or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    ):
      return None
    port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
    return parts.scheme, parts.hostname.lower(), port
  except (ValueError, TypeError):
    return None


def is_same_origin(request, allow_proxy=True):
  site = request.headers.get("sec-fetch-site")
  if site == "cross-site":
    return False
  origins = request.headers.getlist("origin")
  if not origins:
    # Authenticated non-browser API clients need not send an Origin header.
    return True
  if len(origins) != 1 or (origin := normalized_origin(origins[0])) is None:
    return False
  target = normalized_origin(f"{request.url.scheme}://{request.url.netloc}")
  if origin == target:
    return True
  # Browsers forbid JavaScript from setting Sec-Fetch-Site. A same-origin fetch
  # remains same-origin when a reverse proxy rewrites Host or terminates TLS.
  # This never replaces authentication and never trusts X-Forwarded-Host.
  return allow_proxy and site == "same-origin"
