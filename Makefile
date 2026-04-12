ROWS ?= 5
COLS ?= 5

# Run the built-in default level
# make run-default
run-default:
	python main.py

# [deprecated] Generate a v1 level (pipeline/missing only, no battery or target)
# make generate-deprecated ROWS=4 COLS=6
generate-deprecated:
	python generate.py $(ROWS) $(COLS)

# Generate a new level: saves yaml + png to levels/, also creates shuffled version in levels/shuffled/ by default
# Params: ROWS, COLS, BATTERIES, SHUFFLED=0 to skip shuffled
# make generate-level
# make generate-level ROWS=4 COLS=6
# make generate-level ROWS=5 COLS=5 BATTERIES=3 SHUFFLED=0
generate-level:
	python generate.py --v2 $(ROWS) $(COLS) $(if $(BATTERIES),--batteries $(BATTERIES),) $(if $(SHUFFLED),--shuffled $(SHUFFLED),)

# Run a specific level from levels/. If no name given — runs the latest
# make level-run
# make level-run 1
# make level-run 001
level-run:
	python main.py $(filter-out $@,$(MAKECMDGOALS))

# Run a shuffled level from levels/shuffled/. If no name given — runs the latest
# Error if level not found
# make level-run-shuffled
# make level-run-shuffled 1
# make level-run-shuffled 001
level-run-shuffled:
	python main.py --shuffled $(filter-out $@,$(MAKECMDGOALS))

%:
	@:
