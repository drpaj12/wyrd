# Build the Wyrd III tutorial PDF with latexmk (TeX Live).
#
#   make          wyrd-tutorial.pdf
#   make shots    regenerate images/ and transcripts/ from real runs (needs the environment that
#                 shots/make_shots.py documents); slow, run it only when the program changed
#   make clean    remove build/
#
# The PDF is committed: a reader needs no LaTeX.

LATEXMK  ?= latexmk -pdf -interaction=nonstopmode -halt-on-error
PYTHON   ?= python3
WORK     ?= $(CURDIR)/build/shots-work

IMAGES := $(wildcard images/*.png)
TRANSCRIPTS := $(wildcard transcripts/*.txt)

.PHONY: all shots clean

all: wyrd-tutorial.pdf

wyrd-tutorial.pdf: wyrd-tutorial.tex $(IMAGES) $(TRANSCRIPTS) $(wildcard project/src/*.v) project/wyrd.toml project/variants/top_registered.v
	mkdir -p build
	$(LATEXMK) -outdir=build wyrd-tutorial.tex
	cp build/wyrd-tutorial.pdf wyrd-tutorial.pdf

shots:
	$(PYTHON) shots/make_shots.py $(WORK)

clean:
	rm -rf build
