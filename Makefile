ROWS ?= 5
COLS ?= 5

run:
	python main.py

generate:
	python generate.py $(ROWS) $(COLS)
