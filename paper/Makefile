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
STATIC_FIGURES := $(FIGURES_DIR)/NLSR_Work_Flow.png \
                  $(FIGURES_DIR)/Producer_Mobility_Problems.png \
                  $(FIGURES_DIR)/Topology.png
EXPERIMENT_FIGURES := $(FIGURES_DIR)/baseline_throughput.pdf \
                      $(FIGURES_DIR)/solution_throughput.pdf
FIGURES := $(STATIC_FIGURES) $(EXPERIMENT_FIGURES)

# Main target
all: $(OUTPUT_PDF)

# Ensure bin directory exists
$(BIN_DIR):
	mkdir -p $@

# Ensure figures directory exists
$(FIGURES_DIR):
	mkdir -p $@

# Generate the PDF using latexmk
$(OUTPUT_PDF): $(MAIN_TEX) $(FIGURES) | $(BIN_DIR)
	@echo "Compiling LaTeX with latexmk..."
	$(LATEXMK) $(LATEXMK_FLAGS) $(MAIN_TEX)
	cp $(BIN_DIR)/$(OUTPUT_PDF) .

# Experiment figures
$(FIGURES_DIR)/baseline_throughput.pdf: ../experiments/baseline/results/consumer_capture_throughput.pdf | $(FIGURES_DIR)
	cp $< $@

$(FIGURES_DIR)/solution_throughput.pdf: ../experiments/solution/results/consumer_capture_throughput.pdf | $(FIGURES_DIR)
	cp $< $@

# Cleanup intermediate files
clean:
	@echo "Cleaning up intermediate files..."
	$(LATEXMK) -c -output-directory=$(BIN_DIR)

# Cleanup all generated files, including figures
deep-clean: clean
	@echo "Removing all generated files..."
	rm -f $(BIN_DIR)/* $(OUTPUT_PDF) $(FIGURES)

.PHONY: all clean deep-clean
.DELETE_ON_ERROR:
.NOTINTERMEDIATE:
