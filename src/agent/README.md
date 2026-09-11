# Agents

Every deep agent in this project lives in its own separate folder here:

```
src/agent/
  <agent-name>/     one folder per agent — its graph, prompts, tools, config
```

Nothing is shared implicitly between agents; shared helpers belong in `src/app`.
