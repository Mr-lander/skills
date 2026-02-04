#!/usr/bin/env python3
"""
GitHub Knowledge Base - Transform repos from bookmarks to indexed knowledge.

Core actions:
1. explore_repo - Clone + index with CLAUDE.md
2. technical_search - Precision issue/code search
3. ask_local_code - Query indexed repos

Environment Variables:
- GITHUB_KB_PATH: Custom knowledge base directory (default: ~/github-kb)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


# Default knowledge base directory - supports environment variable
DEFAULT_KB_DIR = Path(os.environ.get("GITHUB_KB_PATH", Path.home() / "github-kb"))


def run_command(cmd: List[str], cwd: Optional[Path] = None) -> tuple[bool, str]:
    """Run shell command, return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr or e.stdout


def extract_github_info(url: str) -> Dict[str, str]:
    """Extract org/name from GitHub URL."""
    patterns = [
        r"github\.com/([^/]+)/([^/]+?)(\.git)?$",  # https://github.com/org/repo
        r"github\.com:([^/]+)/([^/]+?)(\.git)?$",  # git@github.com:org/repo
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return {"org": match.group(1), "name": match.group(2).replace(".git", "")}

    raise ValueError(f"Cannot parse GitHub URL: {url}")


def read_file_safe(path: Path) -> Optional[str]:
    """Read file, return None if not exists."""
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return None


def extract_use_cases_from_readme(readme_content: str) -> List[str]:
    """Extract 'Use when' cases from README by analyzing sections."""
    use_cases = []

    # Common patterns for use cases
    patterns = [
        r"(?:Use cases?|When to use|What|Why)[^\n]*:\s*([^\n]+)",
        r"(?:For|Used for|Best for|Designed for)\s+([^\n]+)",
        r"(?:Features|Capabilities|Key)[^\n]*:\s*((?:[^\n]+\n){1,3})",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, readme_content, re.IGNORECASE)
        for match in matches:
            cleaned = match.strip()[:100]
            if cleaned and len(cleaned) > 10:
                use_cases.append(cleaned)

    return use_cases[:3]  # Top 3 use cases


def extract_summary_from_readme(readme_path: Path) -> Dict[str, str]:
    """
    Extract comprehensive summary from README.

    Returns:
        Dict with 'summary', 'use_cases', 'description'
    """
    content = read_file_safe(readme_path)
    if not content:
        return {
            "summary": "No README found",
            "use_cases": ["Add your use case here"],
            "description": ""
        }

    # Remove HTML tags and clean content
    import html
    content = re.sub(r'<[^>]+>', ' ', content)  # Remove HTML tags
    content = html.unescape(content)  # Decode HTML entities
    content = re.sub(r'\s+', ' ', content)  # Normalize whitespace

    # Remove markdown badges and images
    lines = content.split("\n")
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        # Skip badges
        if "[![" in line or "![" in line:
            continue
        # Skip image links
        if line.startswith("<img") or line.startswith("<p"):
            continue
        # Skip empty lines at start
        if not line and not cleaned_lines:
            continue
        cleaned_lines.append(line)

    # Extract first paragraph for summary (skip headers)
    summary_lines = []
    in_first_paragraph = False
    for line in cleaned_lines[:100]:  # Read first 100 lines
        line = line.strip()
        # Skip headers
        if line.startswith("#"):
            continue
        # Skip empty lines
        if not line:
            if in_first_paragraph:  # End of first paragraph
                break
            continue
        # Skip badges (already filtered, but double-check)
        if "[![" in line or "![" in line or "<img" in line:
            continue
        # Skip single word lines
        if len(line.split()) < 3:
            continue
        summary_lines.append(line)
        in_first_paragraph = True
        if len(" ".join(summary_lines)) > 400:  # Max 400 chars for summary
            break

    summary = " ".join(summary_lines)[:400]

    # Extract use cases
    use_cases = extract_use_cases_from_readme(content)
    if not use_cases:
        # Fallback: extract from summary
        use_cases = [summary[:150]] if summary else ["Add your use case here"]

    return {
        "summary": summary,
        "use_cases": use_cases,
        "description": "\n".join(cleaned_lines[:30])  # First 30 lines for context
    }


def extract_tech_stack(repo_path: Path) -> Dict[str, List[str]]:
    """Extract dependencies from requirements.txt, environment.yml, or pyproject.toml."""
    deps = {"python": [], "other": []}

    # Check requirements.txt
    req_file = repo_path / "requirements.txt"
    if req_file.exists():
        content = read_file_safe(req_file)
        if content:
            deps["python"] = [line.strip().split("==")[0].split(">=")[0].split("<=")[0]
                             for line in content.split("\n")
                             if line.strip() and not line.startswith("#")]

    # Check environment.yml (conda)
    env_file = repo_path / "environment.yml"
    if env_file.exists():
        content = read_file_safe(env_file)
        if content:
            # Parse conda dependencies
            match = re.search(r"dependencies:\s*\n((?:[\s\S]*?))\n\s*- name:", content)
            if match:
                for line in match.group(1).split("\n"):
                    dep_match = re.match(r"^\s*-\s*([^=<>]+)", line)
                    if dep_match:
                        dep = dep_match.group(1).strip()
                        if dep and dep != "python":
                            deps["python"].append(dep)

    # Check pyproject.toml
    pyproject_file = repo_path / "pyproject.toml"
    if pyproject_file.exists():
        content = read_file_safe(pyproject_file)
        if content:
            # Extract dependencies from [tool.poetry.dependencies] or [project.dependencies]
            match = re.search(r"(?:tool\.poetry\.dependencies|project\.dependencies)\s*=\s*\[((?:[\s\S]*?))\]", content)
            if match:
                for line in match.group(1).split("\n"):
                    dep_match = re.match(r'^\s*"([^=<>]+)"', line) or re.match(r"^'([^=<>]+)'", line)
                    if dep_match:
                        dep = dep_match.group(1).strip()
                        if dep and dep.lower() != "python":
                            deps["python"].append(dep)

    return deps


def extract_tags_from_readme(readme_path: Path) -> List[str]:
    """Extract tags/keywords from README."""
    content = read_file_safe(readme_path)
    if not content:
        return []

    # Extract from topics badges
    tags = []

    # Common topic patterns
    patterns = [
        r"topic-([a-z0-9-]+)",
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",  # Capitalized terms
        r"(machine learning|deep learning|reinforcement learning|computer vision|nlp|llm|transformer|pytorch|tensorflow)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        tags.extend([m.lower() for m in matches if len(m) > 2])

    # Deduplicate and limit
    unique_tags = list(set(tags))[:10]
    return unique_tags


def identify_key_files(repo_path: Path) -> List[str]:
    """Identify important files for documentation."""
    key_patterns = [
        "**/*.py",  # Python entry points
        "train.*",  # Training scripts
        "demo.*",   # Demo scripts
        "main.*",   # Main entry
        "setup.*",  # Setup files
        "config.*", # Config files
    ]

    key_files = []
    for pattern in key_patterns[:3]:  # Limit to first few patterns
        try:
            matches = list(repo_path.glob(pattern))
            key_files.extend([str(f.relative_to(repo_path)) for f in matches if f.is_file()])
        except Exception:
            pass

    return key_files[:10]  # Top 10 files


def generate_claude_md(repo_path: Path, info: Dict[str, str], force: bool = False) -> Path:
    """
    Generate CLAUDE.md index file with automatic README analysis.

    NO MANUAL EDITING REQUIRED - automatically extracts:
    - Summary from README
    - Use cases from README
    - Technical stack
    - Tags from README content
    """
    claude_md_path = repo_path / "CLAUDE.md"

    if claude_md_path.exists() and not force:
        print(f"ℹ️  CLAUDE.md already exists, skipping. Use --force to regenerate.")
        return claude_md_path

    print(f"📝 Analyzing README and generating CLAUDE.md...")

    # Extract information
    readme_path = repo_path / "README.md"
    summary_data = extract_summary_from_readme(readme_path)
    tech_stack = extract_tech_stack(repo_path)
    tags = extract_tags_from_readme(readme_path)
    key_files = identify_key_files(repo_path)

    # Auto-generate use cases
    use_cases_text = "\n".join(f"  - {uc}" for uc in summary_data["use_cases"][:3])

    # Generate content
    content = f"""# {info['name']} - Auto-Generated Index

## Summary (Auto-generated from README)
{summary_data['summary']}

## Use Cases (Auto-extracted)
{use_cases_text}

## Technical Stack (Auto-extracted)
"""

    # Add dependencies
    if tech_stack["python"]:
        top_deps = tech_stack["python"][:10]  # Top 10
        content += f"### Python Dependencies\n"
        for dep in top_deps:
            content += f"- {dep}\n"

    # Add key files
    if key_files:
        content += f"\n## Key Files\n"
        for f in key_files[:5]:
            content += f"- `{f}`\n"

    # Add tags (auto-extracted or default)
    if tags:
        tags_text = ", ".join(tags[:10])
    else:
        tags_text = "python, github, [TODO: add more tags]"

    content += f"""
## Tags (Auto-extracted)
{tags_text}

---
*Generated by github-kb explore_repo*
*README automatically analyzed - no manual editing required*
"""

    # Write file
    claude_md_path.write_text(content)
    print(f"✅ Created {claude_md_path}")
    print(f"✨ Auto-extracted {len(summary_data['use_cases'])} use cases and {len(tags)} tags")

    return claude_md_path


def explore_repo(url: str, target_dir: Optional[Path] = None, force: bool = False) -> Path:
    """
    Clone repo and generate CLAUDE.md index.

    Args:
        url: GitHub URL
        target_dir: Optional custom target directory
        force: Regenerate CLAUDE.md even if exists

    Returns:
        Path to cloned repo
    """
    # Parse GitHub URL
    info = extract_github_info(url)

    # Determine target directory
    if target_dir is None:
        target_dir = DEFAULT_KB_DIR / info["org"] / info["name"]
    else:
        target_dir = target_dir / info["name"]

    # Create parent directory
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    print(f"🔍 Exploring {info['org']}/{info['name']}...")
    print(f"📁 Target: {target_dir}")

    # Clone if not exists
    if not (target_dir / ".git").exists():
        print(f"📥 Cloning {url}...")
        success, output = run_command(["git", "clone", url, str(target_dir)])
        if not success:
            raise RuntimeError(f"Clone failed: {output}")
        print(f"✅ Cloned successfully")
    else:
        print(f"ℹ️  Repo already exists, skipping clone")

    # Generate CLAUDE.md
    claude_md = generate_claude_md(target_dir, info, force=force)

    print(f"\n✨ Explore complete!")
    print(f"📝 Index: {claude_md}")
    print(f"🎉 README automatically analyzed - ready to use!")

    return target_dir


def technical_search(
    repo: str,
    query: str,
    search_type: str = "issues",
    state_filter: Optional[str] = None,
    label: Optional[str] = None,
    language: Optional[str] = None,
    min_stars: Optional[int] = None,
    topic: Optional[str] = None,
):
    """
    Search GitHub with precision filters.

    Args:
        repo: Repo identifier (org/name or just name for code search)
        query: Search query
        search_type: issues, prs, code, or repos
        state_filter: open, closed, merged (for issues/prs)
        label: Label filter (e.g., "bug")
        language: Language filter (for code/repos)
        min_stars: Minimum stars (for repos)
        topic: Topic filter (for repos)
    """
    print(f"🔍 Technical search: {query}")

    # Build gh search command
    if search_type in ["issues", "prs"]:
        cmd = ["gh", "search", search_type, "--repo", repo, query]
        if state_filter:
            cmd.extend(["--state", state_filter])
        if label:
            cmd.extend(["--label", label])

    elif search_type == "code":
        cmd = ["gh", "search", "code", "--repo", repo, query]
        if language:
            cmd.extend(["--language", language])

    elif search_type == "repos":
        cmd = ["gh", "search", "repos", query]
        if language:
            cmd.extend(["--language", language])
        if min_stars:
            cmd.extend([f"stars:>={min_stars}"])
        if topic:
            cmd.extend(["--topic", topic])

    else:
        raise ValueError(f"Unknown search type: {search_type}")

    # Limit results
    cmd.extend(["--limit", "20"])

    print(f"🔧 Running: {' '.join(cmd)}")

    # Run search
    success, output = run_command(cmd)
    if not success:
        print(f"❌ Search failed: {output}")
        return

    print(f"\n📊 Results:\n")
    print(output)

    print(f"\n💡 Tips:")
    if search_type == "issues":
        print(f"   - Add '--state closed --label bug' for solved bugs")
        print(f"   - Add '--state open' for ongoing discussions")
    elif search_type == "code":
        print(f"   - Add '--language python' for specific language")
        print(f"   - Use exact function/class names for precision")


def ask_local_code(query: str, kb_dir: Optional[Path] = None):
    """
    Query indexed repos in local knowledge base.

    Args:
        query: Natural language query
        kb_dir: Knowledge base directory (defaults to $GITHUB_KB_PATH or ~/github-kb)
    """
    if kb_dir is None:
        kb_dir = DEFAULT_KB_DIR

    if not kb_dir.exists():
        print(f"❌ Knowledge base not found: {kb_dir}")
        print(f"💡 Set $GITHUB_KB_PATH environment variable or run 'explore_repo <url>' to build your knowledge base")
        return

    print(f"🔍 Searching local knowledge base: {query}")
    print(f"📁 KB Directory: {kb_dir}")

    # Search for CLAUDE.md files
    claude_files = list(kb_dir.glob("**/CLAUDE.md"))

    if not claude_files:
        print(f"❌ No indexed repos found")
        print(f"💡 Run 'explore_repo <url>' to index repos")
        return

    print(f"📚 Found {len(claude_files)} indexed repos")

    # Extract keywords from query
    keywords = re.findall(r"\w+", query.lower())

    # Search each CLAUDE.md
    results = []
    for claude_file in claude_files:
        content = read_file_safe(claude_file)
        if not content:
            continue

        # Score by keyword matches
        score = sum(1 for kw in keywords if kw in content.lower())
        if score > 0:
            results.append((score, claude_file, content))

    # Sort by score
    results.sort(key=lambda x: x[0], reverse=True)

    if not results:
        print(f"❌ No matches found for: {query}")
        print(f"💡 Try broader terms or index more repos")
        return

    print(f"\n🎯 Top matches:\n")

    for score, claude_file, content in results[:5]:
        repo_name = claude_file.relative_to(kb_dir).parent
        print(f"📁 {repo_name} (relevance: {score})")
        print("-" * 60)

        # Extract summary section
        summary_match = re.search(r"## Summary.*?(?=##|\Z)", content, re.DOTALL)
        if summary_match:
            summary = summary_match.group(0).strip()
            # Clean up markdown
            summary = re.sub(r"## Summary.*?\n", "", summary)
            summary = summary[:300]  # Truncate
            print(f"{summary}...")

        print(f"\n📄 Full index: {claude_file}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="GitHub Knowledge Base - Transform repos from bookmarks to indexed knowledge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  GITHUB_KB_PATH    Custom knowledge base directory (default: ~/github-kb)

Examples:
  # Explore and index a new repo
  %(prog)s explore https://github.com/Vision-CAIR/MiniGPT-4

  # Use custom KB directory via environment variable
  GITHUB_KB_PATH=/Volumes/P7000Z/Work/github %(prog)s explore <url>

  # Search for solved issues
  %(prog)s search Vision-CAIR/MiniGPT-4 "CUDA memory" --type issues --filter closed --label bug

  # Search code patterns
  %(prog)s search transformers "class MultiHeadAttention" --type code --language python

  # Query local knowledge base
  %(prog)s ask "What repos about reinforcement learning?"
        """
    )

    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    # explore_repo
    explore_parser = subparsers.add_parser("explore", help="Clone and index a repo")
    explore_parser.add_argument("url", help="GitHub URL")
    explore_parser.add_argument("--target-dir", type=Path, help="Custom target directory")
    explore_parser.add_argument("--force", action="store_true", help="Regenerate CLAUDE.md")

    # technical_search
    search_parser = subparsers.add_parser("search", help="Search GitHub with precision filters")
    search_parser.add_argument("repo", help="Repo (org/name) or search query")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--type", choices=["issues", "prs", "code", "repos"],
                              default="issues", help="Search type")
    search_parser.add_argument("--filter", choices=["open", "closed", "merged"],
                              help="State filter (for issues/prs)")
    search_parser.add_argument("--label", help="Label filter (e.g., 'bug')")
    search_parser.add_argument("--language", help="Language filter (for code/repos)")
    search_parser.add_argument("--min-stars", type=int, help="Minimum stars (for repos)")
    search_parser.add_argument("--topic", help="Topic filter (for repos)")

    # ask_local_code
    ask_parser = subparsers.add_parser("ask", help="Query local knowledge base")
    ask_parser.add_argument("query", help="Natural language query")
    ask_parser.add_argument("--kb-dir", type=Path, help="Knowledge base directory (overrides $GITHUB_KB_PATH)")

    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        sys.exit(1)

    try:
        if args.action == "explore":
            explore_repo(args.url, args.target_dir, args.force)

        elif args.action == "search":
            technical_search(
                repo=args.repo,
                query=args.query,
                search_type=args.type,
                state_filter=args.filter,
                label=args.label,
                language=args.language,
                min_stars=args.min_stars,
                topic=args.topic,
            )

        elif args.action == "ask":
            ask_local_code(args.query, args.kb_dir)

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
