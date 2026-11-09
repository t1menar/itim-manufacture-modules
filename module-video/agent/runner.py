"""Entrypoint of the agent container: `python /opt/agent/runner.py /job/run.json`."""

from mvideo.agents.runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
