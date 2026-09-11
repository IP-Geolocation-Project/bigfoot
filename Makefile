.PHONY: all build install clean

all: clean build install

build:
	@pip install --upgrade build
	@python -m build

install:
	@pip install .

clean:
	@rm -rf build/ dist/ *.egg-info

docs:
	@$(MAKE) -C docs html