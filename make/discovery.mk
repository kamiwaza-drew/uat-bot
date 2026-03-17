# discovery.mk - Extension discovery commands (single app repo)

ifndef _DISCOVERY_MK_
_DISCOVERY_MK_ := 1

.PHONY: list
list: ## List all extensions
	@echo "apps/$(NAME_DEFAULT)"

.PHONY: list-apps
list-apps: ## List all apps
	@echo "$(NAME_DEFAULT)"

.PHONY: list-tools
list-tools: ## List all tools
	@true

.PHONY: list-services
list-services: ## List all services
	@true

.PHONY: list-published
list-published: ## List extensions published to remote registry (not supported in app repo)
	@$(call print_warning,"list-published is supported in kamiwaza-extensions-template, not in this standalone app repo")

endif # _DISCOVERY_MK_

