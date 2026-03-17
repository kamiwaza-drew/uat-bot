# dev.mk - Development workflow commands (app-repo compatible)

ifndef _DEV_MK_
_DEV_MK_ := 1

.PHONY: new new-internal new-external new-hybrid
new: new-internal ## Create new extension (not applicable in app repo)
	@true
new-internal: ## Create new extension with source (not applicable in app repo)
	@$(call print_warning,"This repo is already a single app; create new extensions in kamiwaza-extensions-template")
new-external: ## Create external extension (not applicable in app repo)
	@$(call print_warning,"This repo is already a single app; create external extensions in kamiwaza-extensions-template")
new-hybrid: ## Create hybrid extension (not applicable in app repo)
	@$(call print_warning,"This repo is already a single app; create hybrid extensions in kamiwaza-extensions-template")

.PHONY: dev
dev: ## Run docker compose locally
	$(call print_section,Running uat-bot via docker compose)
	@docker compose up --build

.PHONY: dev-rebuild
dev-rebuild: ## Rebuild and run docker compose
	$(call print_section,Rebuilding uat-bot)
	@docker compose build --no-cache
	@docker compose up

.PHONY: logs
logs: ## Show docker compose logs
	@docker compose logs -f

.PHONY: shell
shell: ## Open shell in running container (SERVICE=uat-bot)
	@SERVICE="$(or $(SERVICE),uat-bot)"; \
	docker compose exec "$$SERVICE" /bin/sh

endif # _DEV_MK_

