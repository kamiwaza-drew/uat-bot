# help.mk - Help system mirroring kamiwaza-extensions-template

ifndef _HELP_MK_
_HELP_MK_ := 1

.PHONY: help
help: ## Show this help message
	@$(call print_header,Kamiwaza Extensions Management (stress-tester))
	@echo ""
	@echo "Usage:"
	@echo "  make [target] [VARIABLE=value ...]"
	@echo ""
	@echo "$(BOLD)Quick Start:$(RESET)"
	@echo "  make stress-serve                                              $(COMMENT)# Start the Stress Tester API$(RESET)"
	@echo "  make stress-run SCENARIO=login                                 $(COMMENT)# Launch 20 bots on a fixed path$(RESET)"
	@echo "  make stress-list                                               $(COMMENT)# List available scenario paths$(RESET)"
	@echo "  make install                                                $(COMMENT)# Create .venv via uv$(RESET)"
	@echo "  make dev                                                    $(COMMENT)# Run local docker compose$(RESET)"
	@echo "  make test                                                   $(COMMENT)# Run pytest$(RESET)"
	@echo "  make build                                                  $(COMMENT)# docker build image$(RESET)"
	@echo "  make validate                                               $(COMMENT)# Validate metadata + compose$(RESET)"
	@echo ""
	@$(call print_section,Discovery)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/discovery.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Build and Publish)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/build.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Quality)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/quality.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Metadata)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/metadata.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Templates)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/templates.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Dev Workflow)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/dev.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Stress Tester)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/uat.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Examples)
	@echo "  make build IMAGE_PREFIX=kamiwazaai                          $(COMMENT)# Build image$(RESET)"
	@echo "  make push STAGE=dev                                         $(COMMENT)# Push image with stage tag$(RESET)"
	@echo "  make validate                                               $(COMMENT)# Validate kamiwaza.json + compose$(RESET)"

.PHONY: help-discovery help-build help-metadata help-templates help-dev help-quality

help-discovery: ## Show discovery commands
	@$(call print_header,Discovery Commands)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/discovery.mk | sed 's/:.*##/##/' | sort | $(PYTHON) scripts/format-help.py

help-build: ## Show build/publish commands
	@$(call print_header,Build and Publish Commands)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/build.mk | sed 's/:.*##/##/' | sort | $(PYTHON) scripts/format-help.py

help-quality: ## Show quality commands
	@$(call print_header,Quality Commands)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/quality.mk | sed 's/:.*##/##/' | sort | $(PYTHON) scripts/format-help.py

help-metadata: ## Show metadata commands
	@$(call print_header,Metadata Commands)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/metadata.mk | sed 's/:.*##/##/' | sort | $(PYTHON) scripts/format-help.py

help-templates: ## Show template commands
	@$(call print_header,Template Commands)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/templates.mk | sed 's/:.*##/##/' | sort | $(PYTHON) scripts/format-help.py

help-dev: ## Show development commands
	@$(call print_header,Development Commands)
	@grep -h -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' make/dev.mk | sed 's/:.*##/##/' | sort | $(PYTHON) scripts/format-help.py

endif # _HELP_MK_

