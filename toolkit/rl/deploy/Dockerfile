# Build from the repo root:
#   docker build -f toolkit/rl/deploy/Dockerfile -t agent .
#   docker run -p 8080:8080 agent
# Use the organizers' Dockerfile if they give you one. The 2025 limits were
# CPU-only PyTorch and a 5 GB image.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir numpy flask
COPY toolkit/rl/game_api.py toolkit/rl/search.py toolkit/rl/agents.py ./
COPY toolkit/rl/games ./games
COPY toolkit/rl/deploy/serve.py ./deploy/serve.py
# Uncomment after export: COPY runs/x/policy.pt ./policy.pt
ENV GAME=duel MODEL=heuristic FALLBACK=heuristic BUDGET_MS=150 PORT=8080
EXPOSE 8080
CMD ["python", "deploy/serve.py"]
