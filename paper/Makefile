# Paper Makefile

# Paths
MAIN_TEX := OptoFlood.tex
OUTPUT_PDF := OptoFlood.pdf
FIGURES_DIR := figures
BIN_DIR := bin

# LaTeX Compiler
LATEXMK := latexmk
LATEXMK_FLAGS := -pdf -interaction=nonstopmode -output-directory=$(BIN_DIR)

# Generated Figures
DYNAMIC_FIGURES := $(FIGURES_DIR)/baseline_throughput.pdf \
                   $(FIGURES_DIR)/solution_throughput.pdf

# Static Figures
STATIC_FIGURES := $(FIGURES_DIR)/NLSR_Work_Flow.png \
                  $(FIGURES_DIR)/Producer_Mobility_Problems.png \
                  $(FIGURES_DIR)/Topology.png

# All Figures
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

# Cleanup all generated files, but keep static figures
deep-clean: clean
	@echo "Removing all generated dynamic files..."
	rm -f $(DYNAMIC_FIGURES) $(BIN_DIR)/* $(OUTPUT_PDF)

.PHONY: all clean deep-clean
.DELETE_ON_ERROR:
