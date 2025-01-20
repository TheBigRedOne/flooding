# Paper Makefile

# Paths
MAIN_TEX := OptoFlood.tex
OUTPUT_PDF := OptoFlood.pdf
FIGURES_DIR := figures
BIN_DIR := bin

# LaTeX Compiler
LATEX := pdflatex
LATEX_FLAGS := -interaction=nonstopmode -halt-on-error

# Figures
FIGURES := $(wildcard $(FIGURES_DIR)/*.pdf) $(wildcard $(FIGURES_DIR)/*.png)

# Targets
all: $(OUTPUT_PDF)

$(OUTPUT_PDF): $(MAIN_TEX) $(FIGURES)
	@echo "Compiling LaTeX to PDF..."
	mkdir -p $(BIN_DIR)
	$(LATEX) $(LATEX_FLAGS) -output-directory=$(BIN_DIR) $(MAIN_TEX)
	$(LATEX) $(LATEX_FLAGS) -output-directory=$(BIN_DIR) $(MAIN_TEX) # Run twice for references
	cp $(BIN_DIR)/$(OUTPUT_PDF) .

clean:
	@echo "Cleaning up..."
	rm -rf $(BIN_DIR) *.aux *.log *.out *.toc

.PHONY: all clean
