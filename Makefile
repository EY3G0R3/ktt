.DEFAULT_GOAL := help

PYTHON ?= python3

.PHONY: help autoupdate autoupdate-install

help:
	@printf '%s\n' 'make autoupdate          run the validation required before a live update' \
		'make autoupdate-install  activate the validated checkout (no copy required)'

autoupdate:
	$(PYTHON) -m unittest discover -s tests -v

# Kitty loads the watcher and navigation kitten from this checkout, and the
# running TUI reloads changed Python sources. Fast-forwarding the validated
# checkout is therefore the installation step.
autoupdate-install:
	@:
