# Paper Makefile

# Paths
MAIN_TEX := OptoFlood.tex
OUTPUT_PDF := consumer_capture_throughput.pdf

# LaTeX Compiler
LATEX := pdflatex
LATEX_FLAGS := -interaction=nonstopmode -halt-on-error

# Targets
all: $(OUTPUT_PDF)

$(OUTPUT_PDF): $(MAIN_TEX)
	$(LATEX) $(LATEX_FLAGS) $(MAIN_TEX)

clean:
	rm -f *.aux *.log *.pdf

.PHONY: all clean
