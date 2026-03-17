# build.mk - Build and publish commands (app-repo compatible)

ifndef _BUILD_MK_
_BUILD_MK_ := 1

STAGE ?= dev
PLATFORMS ?= linux/amd64,linux/arm64

.PHONY: build
build: ## Build extension image (uat-bot) - usage: make build [IMAGE_PREFIX=org]
	$(call print_section,Building Docker image)
	@VERSION=$$($(PYTHON) scripts/get-version.py); \
	TAG="$$VERSION"; \
	if [ "$(STAGE)" = "dev" ]; then TAG="$$TAG-dev"; fi; \
	if [ "$(STAGE)" = "stage" ]; then TAG="$$TAG-stage"; fi; \
	IMAGE="$(IMAGE_PREFIX)/uat-bot:$$TAG"; \
	echo "Building $$IMAGE"; \
	docker build -t "$$IMAGE" .

.PHONY: build-no-cache
build-no-cache: ## Build extension without cache
	$(call print_section,Building Docker image (no cache))
	@VERSION=$$($(PYTHON) scripts/get-version.py); \
	TAG="$$VERSION"; \
	if [ "$(STAGE)" = "dev" ]; then TAG="$$TAG-dev"; fi; \
	if [ "$(STAGE)" = "stage" ]; then TAG="$$TAG-stage"; fi; \
	IMAGE="$(IMAGE_PREFIX)/uat-bot:$$TAG"; \
	echo "Building $$IMAGE"; \
	docker build --no-cache -t "$$IMAGE" .

.PHONY: test
test: ## Run pytest
	$(call print_section,Running tests)
	@uv run pytest -q

.PHONY: test-all
test-all: test ## Alias for test
	@true

.PHONY: push
push: ## Push image - usage: make push [STAGE=dev|stage|prod] [BUILD=1]
	@VERSION=$$($(PYTHON) scripts/get-version.py); \
	TAG="$$VERSION"; \
	if [ "$(STAGE)" = "dev" ]; then TAG="$$TAG-dev"; fi; \
	if [ "$(STAGE)" = "stage" ]; then TAG="$$TAG-stage"; fi; \
	IMAGE="$(IMAGE_PREFIX)/uat-bot:$$TAG"; \
	if [ "$(BUILD)" = "1" ]; then $(MAKE) build STAGE=$(STAGE); fi; \
	echo "Pushing $$IMAGE"; \
	docker push "$$IMAGE"

.PHONY: publish publish-images publish-registry build-all build-all-no-cache publish-dry-run
publish: publish-images publish-registry ## Publish (stub for app repo)
	@true

publish-images: ## Publish images (alias of push)
	@$(MAKE) push

publish-registry: ## Publish registry (not applicable in app repo)
	@$(call print_warning,"Registry publishing is handled in kamiwaza-extensions-template (this repo is a single app)")

build-all: build ## Alias in app repo
	@true

build-all-no-cache: build-no-cache ## Alias in app repo
	@true

publish-dry-run: ## Show what would be published
	@VERSION=$$($(PYTHON) scripts/get-version.py); \
	TAG="$$VERSION"; \
	if [ "$(STAGE)" = "dev" ]; then TAG="$$TAG-dev"; fi; \
	if [ "$(STAGE)" = "stage" ]; then TAG="$$TAG-stage"; fi; \
	IMAGE="$(IMAGE_PREFIX)/uat-bot:$$TAG"; \
	echo "Would build and push $$IMAGE"

endif # _BUILD_MK_

