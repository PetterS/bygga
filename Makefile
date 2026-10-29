.PHONY: test browser-test pwa-test
test:
	node --test tests/engine.test.cjs

browser-test:
	uv run tests/browser_check.py

pwa-test:
	uv run tests/browser_check.py --pwa-only
