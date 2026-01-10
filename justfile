# LabDaemon core framework

# Install dependencies
install-deps:
	uv pip install -e .[dev]

# Run the core test suite
test:
	uv run pytest src/labdaemon/tests -v

# Re-run only failed tests
test-rr:
	uv run pytest src/labdaemon/tests --lf -v

# Build the mdBook documentation
docs-build:
	mdbook build docs

# Serve the mdBook documentation locally
docs-serve:
	mdbook serve docs

# Deploy the mdBook to samsci server (requires samsc@samsci SSH config)
docs-deploy:
	mdbook build docs
	rsync -avz --delete docs/book/ samsc@samsci:/srv/docs/labdaemon/

# Build the package
build:
	uv build

# Publish to TestPyPI
publish-test:
	uv publish --publish-url https://test.pypi.org/legacy/

# Publish to production PyPI
publish:
	uv publish
