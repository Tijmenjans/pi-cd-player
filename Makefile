PYTHON ?= python3
VENV ?= .venv
TEST_PYTHON ?= $(VENV)/bin/python

.PHONY: setup test check check-hardware check-http deploy-plan
setup:
	$(PYTHON) -m venv $(VENV)
	$(TEST_PYTHON) -m pip install -r requirements-test.lock

test:
	$(TEST_PYTHON) tools/run_tests.py
	node tests/test_frontend.cjs

check:
	$(TEST_PYTHON) tools/check_repository.py --tracked
	$(TEST_PYTHON) -c 'import pathlib,subprocess; [compile(pathlib.Path(n).read_bytes(),n,"exec") for n in subprocess.check_output(["git","ls-files","-z"]).decode().split("\0") if n.endswith(".py")]'
	bash -n tools/pi-ssh tools/vps-ssh tools/setup
	@if [ -f tools/deploy ]; then bash -n tools/deploy; fi
	$(MAKE) test

check-hardware:
	@test "$(ALLOW_INTEGRATION)" = 1 || { echo 'Explicit opt-in required: make check-hardware ALLOW_INTEGRATION=1'; exit 2; }
	PYTHONPATH=.:tests $(TEST_PYTHON) -m unittest discover -s tests/integration

deploy-plan:
	@test -f tools/deploy || { echo 'tools/deploy is not available yet'; exit 2; }
	./tools/deploy --dry-run

check-http:
	PYTHONPATH=. $(TEST_PYTHON) -m unittest discover -s tests/http -v
