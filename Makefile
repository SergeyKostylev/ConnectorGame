ROWS ?= 5
COLS ?= 5

run:
	python main.py

generate:
	python generate.py $(ROWS) $(COLS)

level-run:
	python main.py $(filter-out $@,$(MAKECMDGOALS))

%:
	@:
