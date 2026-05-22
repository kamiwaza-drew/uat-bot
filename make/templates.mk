# templates.mk - Template management commands (not supported in standalone app repo)

ifndef _TEMPLATES_MK_
_TEMPLATES_MK_ := 1

.PHONY: templates-list templates-list-apps templates-list-tools templates-list-services templates-list-deployments
templates-list: ## List all templates from Kamiwaza (supported in template repo only)
	@$(call print_warning,"Template management targets run from kamiwaza-extensions-template, not this app repo")
templates-list-apps: templates-list ## Alias
	@true
templates-list-tools: templates-list ## Alias
	@true
templates-list-services: templates-list ## Alias
	@true
templates-list-deployments: templates-list ## Alias
	@true

.PHONY: kamiwaza-push kamiwaza-list templates-inspect kind-load-images kind-load-images-dry-run
kamiwaza-push: ## Push template to Kamiwaza (supported in template repo only)
	@$(call print_warning,"Use kamiwaza-extensions-template for garden push (make kamiwaza-push TYPE=app NAME=stress-tester)")
kamiwaza-list: ## List templates on Kamiwaza (supported in template repo only)
	@$(call print_warning,"Use kamiwaza-extensions-template for garden list")
templates-inspect: ## Inspect template details (supported in template repo only)
	@$(call print_warning,"Use kamiwaza-extensions-template for template inspect")
kind-load-images: ## Load images into kind (supported in template repo only)
	@$(call print_warning,"Use kamiwaza-extensions-template for kind image loading")
kind-load-images-dry-run: ## Dry run kind load (supported in template repo only)
	@$(call print_warning,"Use kamiwaza-extensions-template for kind image loading")

endif # _TEMPLATES_MK_

