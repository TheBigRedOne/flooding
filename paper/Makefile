# Paper Makefile

# Paths
MAIN_TEX := OptoFlood.tex
OUTPUT_PDF := OptoFlood.pdf
FIGURES_DIR := figures
BIN_DIR := bin

# LaTeX Compiler
LATEXMK := latexmk
LATEXMK_FLAGS := -pdf -interaction=nonstopmode -output-directory=$(BIN_DIR)

# Figures
FIGURES := $(wildcard $(FIGURES_DIR)/*.pdf) $(wildcard $(FIGURES_DIR)/*.png)

# Main target
all: $(OUTPUT_PDF)

# Ensure bin directory exists
$(BIN_DIR):
	mkdir -p $@

# Generate the PDF using latexmk
$(OUTPUT_PDF): $(MAIN_TEX) $(FIGURES) $(BIN_DIR)
	@echo "Compiling LaTeX with latexmk..."
	$(LATEXMK) $(LATEXMK_FLAGS) $(MAIN_TEX)
	cp $(BIN_DIR)/$(OUTPUT_PDF) .

# Cleanup intermediate files
clean:
	@echo "Cleaning up intermediate files..."
	$(LATEXMK) -c -output-directory=$(BIN_DIR)

# Cleanup all generated files, including figures
deep-clean: clean
	@echo "Removing all generated files..."
	rm -f $(BIN_DIR)/* $(OUTPUT_PDF) $(FIGURES_DIR)/*.pdf

.PHONY: all clean deep-clean
.DELETE_ON_ERROR:
.NOTINTERMEDIATE:
