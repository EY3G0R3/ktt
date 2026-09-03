.DEFAULT_GOAL := help

PYTHON ?= python3
UV ?= uv

.PHONY: help install autoupdate autoupdate-install

help:
	@printf '%s\n' 'make install             install ktt commands into PATH with uv' \
		'make autoupdate          run the validation required before a live update' \
		'make autoupdate-install  activate the validated checkout (no copy required)'

install:
	@command -v $(UV) >/dev/null 2>&1 || { \
		printf '%s\n' 'error: uv is required; install it with: omarchy pkg add uv' >&2; \
		exit 1; \
	}
	$(UV) tool install --editable $(CURDIR)

autoupdate:
	$(PYTHON) -m unittest discover -s tests -v

# Kitty loads the watcher, renderer helpers, and navigation kitten from this
# checkout. Fast-forwarding the validated checkout is therefore the
# installation step.
autoupdate-install:
	@:
