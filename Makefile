.PHONY: test browser-test
test:
	node --test tests/engine.test.cjs

browser-test:
	uv run tests/browser_check.py
