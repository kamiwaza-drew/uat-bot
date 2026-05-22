# stress.mk - One-line Stress Tester launchers for humans
#
# Quick start:
#   Terminal 1:  make stress-serve
#   Terminal 2:  make stress-run SCENARIO=kaizen-conversation-1
#
# Why SCENARIO and not PATH: assigning PATH= on the Make command line
# overrides $PATH in every sub-shell, so curl/python/uv stop being found.

ifndef _STRESS_MK_
_STRESS_MK_ := 1

STRESS_TESTER_HOST  ?= http://localhost:18090
USERS     ?= 20
SCENARIO  ?= login
DURATION  ?= 300
RAMP_UP   ?= 30

.PHONY: stress-serve
stress-serve: ## Start the Stress Tester API locally (leave this running in its own terminal)
	$(call print_section,Starting Stress Tester API)
	@echo "  URL: $(STRESS_TESTER_HOST)"
	@echo "  UI:  $(STRESS_TESTER_HOST)/"
	@echo ""
	@uv sync
	@uv run stress-tester

.PHONY: stress-run
stress-run: ## Launch 20 bots through a fixed scenario, no LLM cost. Override with SCENARIO=name USERS=N
	@if ! curl -sf $(STRESS_TESTER_HOST)/meta > /dev/null 2>&1; then \
	    echo "$(RED)✗ Stress Tester API not reachable at $(STRESS_TESTER_HOST)$(NC)"; \
	    echo "  In another terminal run: $(CYAN)make stress-serve$(NC)"; \
	    exit 1; \
	fi
	$(call print_section,Launching $(USERS) bots on SCENARIO=$(SCENARIO))
	@response=$$(curl -sS -X POST $(STRESS_TESTER_HOST)/runs \
	    -H 'Content-Type: application/json' \
	    -d '{"concurrent_users": $(USERS), "role_distribution": {"viewer": $(USERS)}, "browser_distribution": {"chromium": $(USERS)}, "scenarios": ["$(SCENARIO)"], "duration_seconds": $(DURATION), "ramp_up_seconds": $(RAMP_UP), "vision_enabled": false, "exploratory_pct": 0.0, "single_iteration": true}'); \
	rid=$$(printf '%s' "$$response" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("run_id",""))' 2>/dev/null); \
	if [ -z "$$rid" ]; then \
	    echo "$(RED)✗ Request failed:$(NC)"; \
	    echo "$$response"; \
	    exit 1; \
	fi; \
	echo ""; \
	echo "  Run ID:    $$rid"; \
	echo "  Dashboard: $(STRESS_TESTER_HOST)/"; \
	echo "  Detail:    $(STRESS_TESTER_HOST)/runs/$$rid"

.PHONY: stress-list
stress-list: ## List built-in scenario paths you can pass as SCENARIO=
	$(call print_section,Available scenario paths)
	@ls stress_tester/scenarios/builtin/*.yaml 2>/dev/null | sed 's|.*/||; s|\.yaml$$||' | sort | sed 's/^/  /'
	@echo ""
	@echo "  To add a new path, drop a YAML file into stress_tester/scenarios/builtin/"

endif # _STRESS_MK_
