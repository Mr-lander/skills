# GitHub-KB Skill - Test Scenarios (RED Phase)

## Test Scenario 1: explore_repo - Context Anchor
**Prompt:** "Clone https://github.com/princeton-vl/MiniGPT-4 and tell me what it does"

**Expected WITHOUT skill:**
- Agent runs `git clone`
- Maybe reads README
- Does NOT create structured index in CLAUDE.md
- Does NOT extract technical stack (requirements.txt)
- Does NOT generate summary for future retrieval

**Expected WITH skill:**
- Clone repo
- Extract README
- Analyze requirements.txt/pyproject.toml
- Generate 100-word summary in index file
- Answer what it does

---

## Test Scenario 2: technical_search - Issue Mining
**Prompt:** "I'm getting 'CUDA out of memory' error with vllm. Find solved issues in the repo"

**Expected WITHOUT skill:**
- Agent might try web search
- Or run generic `gh search` without filters
- Does NOT filter for state:closed + label:bug
- Does NOT prioritize solved issues

**Expected WITH skill:**
- Run `gh search issues --state closed --label "bug" "CUDA out of memory" in repo`
- Filter for quality solutions
- Present actionable results

---

## Test Scenario 3: ask_local_code - Local Knowledge Base Query
**Prompt:** "What local repos do I have related to reinforcement learning?"

**Expected WITHOUT skill:**
- Agent says "I don't know what you have locally"
- Or tries to guess based on conversation history
- Does NOT check github-kb directory

**Expected WITH skill:**
- Search github-kb directory for index files
- Filter by RL-related keywords
- Present local repos with summaries

---

## Test Scenario 4: Combined Pressure (Sunk Cost + Time Pressure)
**Prompt:** "I need to implement multi-agent RL fast. Clone smacv2, find issues about training stability, and tell me what setup files to modify"

**Expected WITHOUT skill:**
- Clone, but miss context
- Search issues without proper filters
- Miss connection between issues and setup files
- Provide fragmented answer

**Expected WITH skill:**
- Systematic explore → search → connect dots
- Complete picture: what repo is, known issues, relevant files
