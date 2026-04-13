# Run the built-in default level
# make run-default
run-default:
	python main.py

# Generate a v1 level (pipeline/missing only, no battery or target)
# Params: rows, cols
# make generate-level-v1
# make generate-level-v1 rows=4 cols=6
generate-level-v1:
	python generate.py $(if $(rows),$(rows),) $(if $(cols),$(cols),)

# Generate a v2 level: saves yaml + png to levels/, shuffled version in levels/shuffled/ by default
# Params: rows, cols, batteries=3, shuffled=0 (1 за замовчуванням), run=1 (0 за замовчуванням)
# make generate-level-v2
# make generate-level-v2 rows=4 cols=6
# make generate-level-v2 rows=5 cols=5 batteries=3 shuffled=0
# make generate-level-v2 run=1
generate-level-v2:
	python generate.py v2 $(if $(rows),$(rows),) $(if $(cols),$(cols),) $(if $(batteries),batteries=$(batteries),) $(if $(shuffled),shuffled=$(shuffled),) $(if $(run),run,)

# Generate a v3 level: like v2 but with controlled targets_percent (лампочки)
# Params: rows, cols, batteries=3, targets_percent=15, shuffled=0 (1 за замовчуванням), run=1 (0 за замовчуванням)
# make generate-level-v3
# make generate-level-v3 rows=4 cols=6
# make generate-level-v3 rows=5 cols=5 batteries=3 targets_percent=10
# make generate-level-v3 targets_percent=5 run=1
generate-level-v3:
	python generate.py v3 $(if $(rows),$(rows),) $(if $(cols),$(cols),) $(if $(batteries),batteries=$(batteries),) $(if $(targets_percent),targets-percent=$(targets_percent),) $(if $(shuffled),shuffled=$(shuffled),) $(if $(run),run,)

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

help:
	@awk '/^$$/{desc=""} /^#/ && !desc{desc=substr($$0,3)} /^[a-zA-Z0-9_-]+:/{if(desc) printf "  %-25s %s\n", $$1, desc; desc=""}' Makefile

%:
	@:
