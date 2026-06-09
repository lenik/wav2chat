# wav2chat install/uninstall
#
# Examples:
#   make install
#   make install PREFIX=$$HOME/.local
#   make install-gui
#   make uninstall PREFIX=$$HOME/.local

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PREFIX ?= /usr/local
DESTDIR ?=
MANDIR = $(PREFIX)/share/man
COMPDIR = $(PREFIX)/share/bash-completion/completions
DOCDIR = $(PREFIX)/share/doc/wav2chat

MANPAGE = doc/wav2chat.1
COMPLETION = completions/wav2chat
LICENSE_FILE = LICENSE
PACKAGE = wav2chat

PIP_INSTALL_FLAGS = --prefix="$(PREFIX)"
ifeq ($(DESTDIR),)
PIP_ROOT =
else
PIP_ROOT = --root="$(DESTDIR)"
endif

.PHONY: all install install-gui install-gui-deps install-man install-completion install-doc uninstall help

all: help

help:
	@echo "Targets:"
	@echo "  install              Install wav2chat, man page, and bash completion"
	@echo "  install-gui          Install wav2chat + system wx GUI dependency"
	@echo "  install-gui-deps     Install python3-wxgtk4.0 (Debian/Ubuntu)"
	@echo "  install-man          Install man page only"
	@echo "  install-completion   Install bash completion only"
	@echo "  install-doc          Install LICENSE only"
	@echo "  uninstall            Remove wav2chat, man page, and bash completion"
	@echo ""
	@echo "Variables:"
	@echo "  PREFIX=$(PREFIX)"
	@echo "  DESTDIR=$(DESTDIR)"
	@echo "  PYTHON=$(PYTHON)"

install: install-man install-completion install-doc
	$(PIP) install $(PIP_ROOT) $(PIP_INSTALL_FLAGS) .

install-gui: install-gui-deps install

install-gui-deps:
	@if command -v apt-get >/dev/null 2>&1; then \
		sudo apt-get install -y python3-wxgtk4.0; \
	else \
		echo "Install wx for your distro (Debian/Ubuntu: python3-wxgtk4.0)"; \
	fi
	@echo "If using a venv, create it with: python3 -m venv --system-site-packages .venv"

install-man:
	install -D -m 644 $(MANPAGE) $(DESTDIR)$(MANDIR)/man1/wav2chat.1

install-completion:
	install -D -m 644 $(COMPLETION) $(DESTDIR)$(COMPDIR)/wav2chat

install-doc:
	install -D -m 644 $(LICENSE_FILE) $(DESTDIR)$(DOCDIR)/LICENSE

uninstall:
	-$(PIP) uninstall -y $(PACKAGE) >/dev/null 2>&1 || true
	rm -f $(DESTDIR)$(MANDIR)/man1/wav2chat.1
	rm -f $(DESTDIR)$(COMPDIR)/wav2chat
	rm -f $(DESTDIR)$(DOCDIR)/LICENSE
