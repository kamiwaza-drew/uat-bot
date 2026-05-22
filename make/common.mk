# common.mk - Shared variables and utilities (app-repo compatible)

ifndef _COMMON_MK_
_COMMON_MK_ := 1

# Load .env if present and export vars
ifneq (,$(wildcard .env))
    include .env
    export
endif

# Unexport include guard variables
unexport _COMMON_MK_ _BUILD_MK_ _QUALITY_MK_ _DISCOVERY_MK_ _METADATA_MK_ _TEMPLATES_MK_ _DEV_MK_ _DEMO_MK_ _HELP_MK_

# Docker image prefix (override in .env or env)
IMAGE_PREFIX ?= kamiwazaai
export IMAGE_PREFIX

# App identity (this repo is a single app)
TYPE_DEFAULT := app
NAME_DEFAULT := stress-tester

TYPE ?= $(TYPE_DEFAULT)
NAME ?= $(NAME_DEFAULT)

# Python environment
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

# Terminal colors
ifeq ($(OS),Windows_NT)
    RED :=
    GREEN :=
    YELLOW :=
    BLUE :=
    MAGENTA :=
    CYAN :=
    WHITE :=
    NC :=
    BOLD :=
    DIM :=
    RESET :=
    HEADER :=
    COMMAND :=
    ARGS :=
    COMMENT :=
else
    RED := \033[0;31m
    GREEN := \033[0;32m
    YELLOW := \033[0;33m
    BLUE := \033[0;34m
    MAGENTA := \033[0;35m
    CYAN := \033[0;36m
    WHITE := \033[0;37m
    NC := \033[0m

    BOLD := \033[1m
    DIM := \033[2m
    RESET := \033[0m

    HEADER := \033[1;35m
    COMMAND := \033[0m
    ARGS := \033[0;36m
    COMMENT := \033[2m
endif

define print_header
	@echo ""
	@echo "$(HEADER)==============================================================================$(RESET)"
	@echo "$(HEADER)$(1)$(RESET)"
	@echo "$(HEADER)==============================================================================$(RESET)"
	@echo ""
endef

define print_section
	@echo ""
	@echo "$(HEADER)$(1):$(RESET)"
endef

define print_success
	@echo "$(GREEN)✓ $(1)$(NC)"
endef

define print_error
	@echo "$(RED)✗ $(1)$(NC)"
endef

define print_warning
	@echo "$(YELLOW)⚠ $(1)$(NC)"
endef

endif # _COMMON_MK_

