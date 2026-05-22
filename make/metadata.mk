# metadata.mk - Metadata and validation commands (app-repo compatible)

ifndef _METADATA_MK_
_METADATA_MK_ := 1

STAGE ?= dev
REPO_VERSION ?= 3

.PHONY: validate
validate: ## Validate metadata + compose - usage: make validate
	$(call print_section,Validating kamiwaza.json)
	@$(PYTHON) -c "import json; json.load(open('kamiwaza.json')); print('kamiwaza.json: OK')"
	$(call print_section,Validating docker compose files)
	@docker compose -f docker-compose.yml config >/dev/null
	@docker compose -f docker-compose.appgarden.yml config >/dev/null
	@$(call print_success,"Compose: OK")

.PHONY: sync-compose
sync-compose: ## Sync compose files (not applicable in app repo)
	@$(call print_warning,"Compose syncing is handled in kamiwaza-extensions-template; this repo maintains its own compose files")

.PHONY: generate-appgarden-compose
generate-appgarden-compose: ## Generate App Garden compose (not applicable; file is maintained)
	@$(call print_section,App Garden compose)
	@echo "This repo maintains docker-compose.appgarden.yml directly."
	@echo "If syncing into the template repo, run:"
	@echo "  uv run python scripts/sync_to_kamiwaza_extensions_template.py --template-repo /path/to/kamiwaza-extensions-template --force"

.PHONY: build-registry export-images package-registry serve-registry verify-images verify-images-registry verify-images-all show-registry check-compose
build-registry: ## Build registry (not supported in app repo)
	@$(call print_warning,"Registry build/export is handled in kamiwaza-extensions-template")
export-images: ## Export images (not supported in app repo)
	@$(call print_warning,"Image export is handled in kamiwaza-extensions-template")
package-registry: ## Package registry (not supported in app repo)
	@$(call print_warning,"Registry packaging is handled in kamiwaza-extensions-template")
serve-registry: ## Serve registry (not supported in app repo)
	@$(call print_warning,"Registry serving is handled in kamiwaza-extensions-template")
verify-images: ## Verify images (basic local check)
	@$(call print_section,Verifying local Docker image exists)
	@VERSION=$$($(PYTHON) scripts/get-version.py); \
	TAG="$$VERSION"; \
	if [ "$(STAGE)" = "dev" ]; then TAG="$$TAG-dev"; fi; \
	if [ "$(STAGE)" = "stage" ]; then TAG="$$TAG-stage"; fi; \
	IMAGE="$(IMAGE_PREFIX)/stress-tester:$$TAG"; \
	docker image inspect "$$IMAGE" >/dev/null && echo "OK: $$IMAGE"
verify-images-registry: ## Verify images in registry (not supported)
	@$(call print_warning,"Remote registry verification is handled in kamiwaza-extensions-template")
verify-images-all: verify-images ## Verify images locally
	@true
show-registry: ## Show registry entry (not supported)
	@$(call print_warning,"Registry entries exist in the template repo, not this standalone app repo")
check-compose: ## Check compose sync (not applicable)
	@$(call print_warning,"Not applicable in standalone app repo")

endif # _METADATA_MK_

