# Targets: "solver" is the workspace a model edits; "grader" (default) validates and grades.
FROM python@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-deps --root-user-action=ignore -r /tmp/requirements.txt

FROM base AS solver
WORKDIR /workspace
COPY task.md requirements.txt ./
COPY app ./app
COPY tests/visible ./tests/visible
CMD ["python", "-m", "pytest", "-q", "tests/visible"]

FROM base AS grader
RUN apt-get update \
    && apt-get install -y --no-install-recommends patch \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /grader
COPY . .
CMD ["./validate.sh"]
