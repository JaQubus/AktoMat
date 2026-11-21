.PHONY: run test eval synth demo
run:
	docker compose up --build
test:
	cd backend && uv run --python 3.11 --extra dev python -m pytest -q
synth:
	cd backend && uv run python ../scripts/make_synthetic_cases.py
eval:
	cd backend && uv run python ../scripts/evaluate_accuracy.py
demo:
	@echo "M9: tryb demo (offline) - do zrobienia"
