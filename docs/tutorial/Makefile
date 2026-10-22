# Build the Wyrd III tutorial PDF with Tectonic (the same tool the Odin III paper uses).
#
#   make          wyrd-tutorial.pdf
#   make shots    regenerate images/ and transcripts/ from real runs (needs the environment that
#                 shots/make_shots.py documents); slow, run it only when the program changed
#   make clean    remove build/
#
# The PDF is committed: a reader needs no LaTeX. Tectonic fetches TeX packages on demand.

TECTONIC ?= $(HOME)/odin3-ws/work/tools/tectonic/tectonic
PYTHON   ?= python3
WORK     ?= /tmp/claude-1000/wdoc-tutorial

IMAGES := $(wildcard images/*.png)
TRANSCRIPTS := $(wildcard transcripts/*.txt)

.PHONY: all shots clean

all: wyrd-tutorial.pdf

wyrd-tutorial.pdf: wyrd-tutorial.tex $(IMAGES) $(TRANSCRIPTS) $(wildcard project/src/*.v) project/wyrd.toml project/variants/top_registered.v
	mkdir -p build
	$(TECTONIC) -X compile --outdir build wyrd-tutorial.tex
	cp build/wyrd-tutorial.pdf wyrd-tutorial.pdf

shots:
	$(PYTHON) shots/make_shots.py $(WORK)

clean:
	rm -rf build
