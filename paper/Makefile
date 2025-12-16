# Paper Makefile

# Paths
MAIN_TEX := OptoFlood.tex
OUTPUT_PDF := OptoFlood.pdf
FIGURES_DIR := figures
BIN_DIR := bin

# LaTeX Compiler
LATEXMK := latexmk
LATEXMK_FLAGS := -pdf -interaction=nonstopmode -output-directory=$(BIN_DIR)

# Static figures are explicitly listed, regardless of type.
STATIC_FIGURES := \
	$(FIGURES_DIR)/NDN_Packets_Processing_Flow.pdf \
	$(FIGURES_DIR)/NDN_Producer_Mobility_Problem.pdf \
	$(FIGURES_DIR)/NDN_Producer_Mobility_Problem_Solution.pdf \
	$(FIGURES_DIR)/Topology.pdf

# Dynamic figures are all other PDFs in the directory.
ALL_PDFS := $(wildcard $(FIGURES_DIR)/*.pdf)
STATIC_PDFS := $(filter %.pdf,$(STATIC_FIGURES))
DYNAMIC_FIGURES := $(filter-out $(STATIC_PDFS),$(ALL_PDFS))

ALL_FIGURES := $(STATIC_FIGURES) $(DYNAMIC_FIGURES)

# Main Target
all: $(OUTPUT_PDF)

# Ensure bin directory exists
$(BIN_DIR):
	mkdir -p $@

# Generate the PDF using latexmk
$(OUTPUT_PDF): $(MAIN_TEX) $(ALL_FIGURES) | $(BIN_DIR)
	@echo "Compiling LaTeX with latexmk..."
	$(LATEXMK) $(LATEXMK_FLAGS) $(MAIN_TEX)
	cp $(BIN_DIR)/$(OUTPUT_PDF) .

# Cleanup intermediate files
clean:
	@echo "Cleaning up intermediate files..."
	$(LATEXMK) -c -output-directory=$(BIN_DIR)
	rm -f $(OUTPUT_PDF)

# Cleanup all generated files, but keep static figures
deep-clean: clean
	@echo "Removing all generated dynamic figures..."
	rm -f $(DYNAMIC_FIGURES)

.PHONY: all clean deep-clean
.DELETE_ON_ERROR:
