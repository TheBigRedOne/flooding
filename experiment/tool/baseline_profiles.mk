# Baseline parameter-set configuration.
#
# Purpose:
#   Declare the ordered baseline profile set and the per-profile NLSR interval
#   parameters used by the top-level Makefile.
#
# Interface:
#   - BASELINE_PROFILE_IDS: ordered profile identifiers
#   - BASELINE_DEFAULT_PROFILE: identifier of the default baseline profile
#   - BASELINE_PROFILE_DIR_<id>: result directory for one profile
#   - BASELINE_PROFILE_HELLO_<id>: hello interval in seconds
#   - BASELINE_PROFILE_ADJ_<id>: adjacency-LSA build interval in seconds
#   - BASELINE_PROFILE_ROUTE_<id>: routing calculation interval in seconds

BASELINE_PROFILE_IDS := default moderate aggressive
BASELINE_DEFAULT_PROFILE := default

BASELINE_PROFILE_DIR_default := $(BASELINE_ROOT_DIR)/h60-a10-r15(default)
BASELINE_PROFILE_DIR_moderate := $(BASELINE_ROOT_DIR)/h48-a8-r12
BASELINE_PROFILE_DIR_aggressive := $(BASELINE_ROOT_DIR)/h36-a6-r9

BASELINE_PROFILE_HELLO_default := 60
BASELINE_PROFILE_HELLO_moderate := 48
BASELINE_PROFILE_HELLO_aggressive := 36

BASELINE_PROFILE_ADJ_default := 10
BASELINE_PROFILE_ADJ_moderate := 8
BASELINE_PROFILE_ADJ_aggressive := 6

BASELINE_PROFILE_ROUTE_default := 15
BASELINE_PROFILE_ROUTE_moderate := 12
BASELINE_PROFILE_ROUTE_aggressive := 9
