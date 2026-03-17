# quality.mk - Quality and development setup (app-repo compatible)

ifndef _QUALITY_MK_
_QUALITY_MK_ := 1

.PHONY: install
install: ## Install dependencies (uv sync)
	$(call print_section,Installing dependencies with uv)
	@uv sync

.PHONY: check
check: ## Run basic quality checks (lock + tests)
	$(call print_section,Checking uv lock consistency)
	@uv lock --check
	@$(MAKE) test

.PHONY: clean
clean: ## Clean build artifacts and caches (keeps dependencies)
	$(call print_section,Cleaning build artifacts)
	@rm -rf build/ dist/ *.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@find . -type f -name "coverage.xml" -delete 2>/dev/null || true
	@$(call print_success,"Clean complete")

.PHONY: clean-deps
clean-deps: ## Remove virtualenv (.venv)
	$(call print_section,Removing dependencies)
	@rm -rf .venv/
	@$(call print_success,"Dependency cleanup complete")

.PHONY: clean-all
clean-all: clean clean-deps ## Clean everything (artifacts + dependencies)
	@true

.PHONY: distclean
distclean: clean-all ## Alias for clean-all
	@true

endif # _QUALITY_MK_

