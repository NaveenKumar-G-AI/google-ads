"""Run inside a newly built backend image without network or credentials."""
from recovery.api.app import create_app
from recovery.api.auth import StaticTokenVerifier
from recovery.build_identity import get_build_identity, validate_build_identity
from weasyprint import HTML

validate_build_identity()
identity = get_build_identity()
assert identity["build_identity"] == "embedded", "Backend image must contain build metadata"
app = create_app(repository=object(), verifier=StaticTokenVerifier({}))
for path in ("/healthz", "/readyz", "/buildz", "/v1/me", "/v1/launch/status/me"):
    assert any(getattr(route, "path", None) == path and "GET" in getattr(route, "methods", set()) for route in app.routes), path
pdf = HTML(string="<html><body><h1>Recovery OS deployment check</h1><p>Native PDF rendering works.</p></body></html>").write_pdf()
assert pdf.startswith(b"%PDF-") and len(pdf) > 500
print("PASS installed backend route table, embedded build metadata and native PDF rendering")
