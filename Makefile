# Makefile for DIDSvc project.
#
# Run `make help` for some help.
#
# Backend (didsvc-) targets require a python virtualenv (venv) to be active. To
# explicitly override the check and run without a venv, set SKIP_CHECK_VENV=1
# env var.
#
# Frontend (didcheck-) targets require an NVM environment to be active. To
# explicitly override the check and run without an NVM, set SKIP_CHECK_NVM=1 env
# var.


######################################################################
## Env Vars
######################################################################


PYTHON := python3
VENV := .venv
AUDIT_REPORT_FILE := audit-report.txt
FULLTEST_REPORT_FILE := fulltest-report.txt


######################################################################
## Global settings
######################################################################


# Skip showing entering/leaving dir when running sub make
MAKEFLAGS += --no-print-directory

.DEFAULT_GOAL := help

# Make everything PHONY: this is just a task runner.
.PHONY: %


######################################################################
## Basic targets
######################################################################


help: ## Show this help message
	@awk 'BEGIN {FS = ":.*##"} \
		/^[a-zA-Z0-9_-]+:.*##/ { \
			printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2 \
		}' $(MAKEFILE_LIST)


venv: ## Reminder on how to activate virtualEnv
	@echo "source .venv/bin/activate"

venv-create: ## Create the default virtualenv venv
	$(PYTHON) -m venv $(VENV)

venv-check: ## Check if virtualenv is activated or skipped
	@test -n "$$SKIP_CHECK_VENV" || test -n "$$VIRTUAL_ENV" || \
		( echo "ERROR: No virtualenv active. Run 'make venv' to activate or set SKIP_CHECK_VENV=1 to bypass."; exit 1 )

nvm-check: ## Check if NVM is activated or skipped
	@test -n "$$SKIP_CHECK_NVM" || test -n "$$NVM_BIN" || \
		( echo "ERROR: No NVM Node version active. Run 'nvm use' or set SKIP_CHECK_NVM=1."; exit 1 )


######################################################################
## Backend targets
######################################################################


didsvc-install: venv-check ## Install base runtime dependencies
	pip install -r requirements.txt

didsvc-install-dev: venv-check ## Install additional dev dependencies
	pip install -r requirements-dev.txt

didsvc-dev: venv-check ## Run the backend app in local machine
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --no-access-log

didsvc-lint: venv-check ## Lint code
	ruff check .

didsvc-test-unit: venv-check ## Run basic unit tests
	pytest

didsvc-test-integration: venv-check ## Run tests with testcontainers services
	pytest --db-mode=container --vault-mode=container

didsvc-test-coverage: venv-check ## Run all tests and generate coverage report
	pytest tests/unit/ --cov=app --cov-report=
	pytest tests/containerdb/ --db-mode=container --cov=app --cov-append --cov-report=
	pytest tests/integration/ --db-mode=container --vault-mode=container --cov=app --cov-append --cov-report=
	coverage report
	coverage html

didsvc-loadtest-up: ## Rebuild/restart loadtest containers
	docker compose -f deployment/docker-compose.loadtest.yml down
	docker compose -f deployment/docker-compose.loadtest.yml build
	docker compose -f deployment/docker-compose.loadtest.yml up -d
	sleep 1s
	docker compose -f deployment/docker-compose.loadtest.yml ps

didsvc-loadtest-down: ## Stop loadtest containers
	docker compose -f deployment/docker-compose.loadtest.yml down

didsvc-loadtest-sanity: venv-check didsvc-loadtest-up ## Run a quick sanity loadtest execution
	python benchmarks/scripts/run_benchmark.py --users 50 --duration 30s --spawn-rate 5

didsvc-loadtest-std: venv-check didsvc-loadtest-up ## Run a standard loadtest execution
	python benchmarks/scripts/run_benchmark.py

didsvc-loadtest-stress: venv-check didsvc-loadtest-up ## Run a stress loadtest execution
	python benchmarks/scripts/run_benchmark.py --users 1000  --duration 5m --spawn-rate 5

didsvc-audit: venv-check ## Perform a pip-audit in backend dependencies
	pip-audit -r requirements.txt --strict

######################################################################
## Frontend targets
######################################################################

didcheck-install: nvm-check ## Install dependencies for DIDCheck development
	(cd didcheck && npm install)

didcheck-dev: nvm-check ## Run DIDCheck local development server
	(cd didcheck && npm run dev)

didcheck-audit: nvm-check ## Perform an npm audit in didcheck dependencies
	(cd didcheck && npm audit)
	(cd didcheck/tests/backend-compat && npm audit)


######################################################################
## Backend+Frontend targets
######################################################################
test-vccompat: venv-check nvm-check ## Run vc_compat backend+frontend integration tests
	pytest -m vc_compat
	(cd didcheck && npm run test:vc-compat)

example-excelreport-install: venv-check ## Install dependencies for excel_report example
	(cd examples/excel_report && pip install -r requirements.txt)

example-excelreport-dev: venv-check ## Run excel_report example dev environment
	(cd examples/excel_report && uvicorn main:app --reload --port 3001)

owasp-depcheck: ## Run OWASP depedency-check tool in both front and back end code
	@dependency-check.sh \
		--project "DIDService" \
		--scan ./requirements.txt \
		--scan ./didcheck \
		--enableExperimental \
		--format ./scripts/depcheck-txt-summary.vsl \
		-o ./dependency-check-report.txt \
		--junitFailOnCVSS 0

trivy-check: ## Run trivy check in both front and back end code
	@docker run --rm \
		-v $(PWD):/project \
		-v ~/.cache/trivy:/root/.cache/trivy \
		aquasec/trivy:0.69.3 \
		fs /project

audit-report-inner: venv-check nvm-check
	@echo "Full DIDservice Audit Report"
	@date
	@echo "-------------------- DIDSvc audit task --------------------"
	@$(MAKE) didsvc-audit
	@echo "-------------------- DIDCheck audit task --------------------"
	@$(MAKE) didcheck-audit
	@echo "-------------------- trivy audit task --------------------"
	@$(MAKE) trivy-check
	@echo "-------------------- OWASP depcheck task --------------------"
	@$(MAKE) owasp-depcheck

audit-report: venv-check nvm-check ## Run all audit/check tasks and write a text report file
	@rm -f $(AUDIT_REPORT_FILE)
	@$(MAKE) audit-report-inner | tee $(AUDIT_REPORT_FILE)
	@cat dependency-check-report.txt >> $(AUDIT_REPORT_FILE)


full-test-inner: venv-check nvm-check
	@echo "Full DIDservice Test Report"
	@date
	@echo "-------------------- DIDSvc lint --------------------"
	@$(MAKE) didsvc-lint
	@echo "-------------------- DIDSvc coverage report --------------------"
	@$(MAKE) didsvc-test-coverage
	@echo "-------------------- VC Compat testing --------------------"
	@$(MAKE) test-vccompat
	@echo "-------------------- Load test (sanity) --------------------"
	@$(MAKE) didsvc-loadtest-sanity
	@$(MAKE) didsvc-loadtest-down
	@echo "-------------------- Finished --------------------"
	@echo "Full-test finished"
	@date

full-test: venv-check nvm-check ## Run all relevant tests
	@rm -f $(FULLTEST_REPORT_FILE)
	@$(MAKE) full-test-inner | tee $(FULLTEST_REPORT_FILE)


######################################################################
## Docker targets
######################################################################

docker-compose:
	docker compose -f deployment/docker-compose.$(strip $(DOCKERENV)).yml $(DOCKERCMD)

docker-dev-build: ## Build DEV docker env
	@$(MAKE) docker-compose DOCKERENV=dev DOCKERCMD=build

docker-dev-up: ## Bring up DEV docker env
	@$(MAKE) docker-compose DOCKERENV=dev DOCKERCMD="up -d"

docker-dev-down: ## Bring down DEV docker env
	@$(MAKE) docker-compose DOCKERENV=dev DOCKERCMD="down"

docker-dev-logs: ## Show last 100 logs on DEV docker env
	@$(MAKE) docker-compose DOCKERENV=dev DOCKERCMD="logs -n 100"


# The localdev environment uses local mongodb and vault installs. Only the "up"
# command is necessary, the other commands can use the -dev- targets.
docker-localdev-up: ## Bring up the LOCALDEV docker env
	docker compose -f deployment/docker-compose.dev.yml -f deployment/docker-compose.dev.local-override.yml up