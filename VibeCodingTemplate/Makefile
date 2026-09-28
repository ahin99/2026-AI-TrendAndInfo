.PHONY: test check

test:
	PYTHONPYCACHEPREFIX=.cache/pycache PYTHONPATH=src python3 -m unittest discover -s tests -v

check:
	PYTHONPYCACHEPREFIX=.cache/pycache PYTHONPATH=src python3 -m compileall -q src tests tools
	PYTHONPYCACHEPREFIX=.cache/pycache python3 tools/check_repo.py
	bash -n tools/commit_session.sh
