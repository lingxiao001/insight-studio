"""Render the domain-only Caddy template without shell interpolation."""
import argparse
import ipaddress
from pathlib import Path
import re
from urllib.parse import urlsplit


def canonical_site_url(value):
    if any(char.isspace() for char in value):
        raise ValueError("SITE_URL cannot contain whitespace.")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError("SITE_URL must be https://your.domain.example with no path, credentials or nonstandard port.")
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Use a DNS hostname for automatic domain certificates; IP certificate deployment is not included.")
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise ValueError("SITE_URL must contain a valid public DNS hostname.")
    return "https://" + host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-url", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--print-url", action="store_true", help="Validate and print only the canonical HTTPS URL.")
    args = parser.parse_args()
    try:
        site_url = canonical_site_url(args.site_url)
    except (ValueError, UnicodeError) as exc:
        parser.error(str(exc))
    if args.print_url:
        print(site_url)
        return
    template = Path(__file__).with_name("Caddyfile").read_text(encoding="utf-8")
    rendered = template.replace("__SITE_HOST__", urlsplit(site_url).hostname)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
