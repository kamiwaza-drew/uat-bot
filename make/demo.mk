# demo.mk - Demo workflows (not applicable in standalone app repo)

ifndef _DEMO_MK_
_DEMO_MK_ := 1

.PHONY: demo
demo: ## Run end-to-end demo (supported in template repo only)
	@$(call print_warning,"Demo workflows live in kamiwaza-extensions-template")

endif # _DEMO_MK_

