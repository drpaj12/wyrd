# Build the Wyrd III GUI tutorial PDF with latexmk (TeX Live; the same tool the CLI tutorial uses).
#
#   make          wyrd-gui-tutorial.pdf
#   make shots    regenerate images/gt-*.png from the real GUI (needs the environment that
#                 shots/make_gui_shots.py documents); slow, run it only when the program changed
#   make clean    remove build/
#
# The PDF is committed: a reader needs no LaTeX. The project sources are those of the CLI tutorial.

LATEXMK  ?= latexmk -pdf -interaction=nonstopmode -halt-on-error
PYTHON   ?= python3
WORK     ?= $(CURDIR)/build/shots-work

IMAGES := $(wildcard images/*.png)

.PHONY: all shots clean

all: wyrd-gui-tutorial.pdf

wyrd-gui-tutorial.pdf: wyrd-gui-tutorial.tex $(IMAGES)
	mkdir -p build
	$(LATEXMK) -outdir=build wyrd-gui-tutorial.tex
	cp build/wyrd-gui-tutorial.pdf wyrd-gui-tutorial.pdf

shots:
	QT_QPA_PLATFORM=offscreen $(PYTHON) shots/make_gui_shots.py $(WORK)

clean:
	rm -rf build
