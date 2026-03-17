# Kamiwaza Extensions Makefile (app-repo compatible)
# Mirrors target names from kamiwaza-extensions-template, adapted for a single app repo.

-include .env

include make/common.mk
include make/discovery.mk
include make/build.mk
include make/quality.mk
include make/metadata.mk
include make/templates.mk
include make/dev.mk
include make/demo.mk
include make/help.mk

.DEFAULT_GOAL := help
.PHONY: all
all: help

