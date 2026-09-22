#!/usr/bin/env python3
"""
Hoover & Bake Antigravity CLI Allowlist

Sweeps commands from:
- Claude Code (~/.claude/projects/*/*.jsonl, ~/.claude.json)
- Antigravity CLI (~/.gemini/antigravity-cli/brain/*, settings.json)
- OpenCode (~/.config/opencode, AppData)
- SSH Config (~/.ssh/config)

Generates:
- docs/allowlist-ingestion.json (can be overwritten at will)
Can bake generalized rules directly into ~/.gemini/antigravity-cli/settings.json.
"""

import argparse
import glob
import json
import os
import re
import sys

SETTINGS_FILE = os.path.expanduser(r"~/.gemini/antigravity-cli/settings.json")
DEFAULT_INGESTION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "allowlist-ingestion.json")

def clean_cmd(cmd_str):
    if not cmd_str:
        return None
    cmd_str = cmd_str.strip()
    if cmd_str.startswith('"') and cmd_str.endswith('"'):
        try:
            cmd_str = json.loads(cmd_str)
        except Exception:
            cmd_str = cmd_str[1:-1]
    cmd_str = cmd_str.strip()
    return cmd_str if cmd_str else None

def get_ssh_hosts():
    hosts = set(["nuc01", "nuc02"])
    ssh_config = os.path.expanduser(r"~/.ssh/config")
    if os.path.exists(ssh_config):
        with open(ssh_config, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.lower().startswith("host "):
                    parts = line.split()[1:]
                    for p in parts:
                        if not any(ch in p for ch in ["*", "?", "%"]):
                            hosts.add(p)
                elif line.lower().startswith("hostname "):
                    ip = line.split()[1]
                    hosts.add(ip)
    return sorted(hosts)

def harvest_all():
    raw_commands = {} # cmd -> set(sources)

    def record(cmd, source):
        c = clean_cmd(cmd)
        if c:
            if c not in raw_commands:
                raw_commands[c] = set()
            raw_commands[c].add(source)

    # 1. Existing Antigravity settings
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for r in data.get("permissions", {}).get("allow", []):
                    record(r, "antigravity_settings")
        except Exception as e:
            print(f"[!] Warning reading settings.json: {e}", file=sys.stderr)

    # 2. Antigravity transcripts
    transcripts = glob.glob(os.path.expanduser(r"~/.gemini/antigravity-cli/brain/*/.system_generated/logs/transcript*.jsonl"))
    for t in transcripts:
        try:
            with open(t, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "run_command" in line:
                        try:
                            d = json.loads(line)
                            for call in d.get("tool_calls", []):
                                if call.get("name") == "run_command":
                                    args = call.get("args", {})
                                    cmd = clean_cmd(args.get("CommandLine"))
                                    if cmd:
                                        record(cmd, "antigravity_cli")
                        except Exception:
                            pass
        except Exception:
            pass

    # 3. Claude Code
    claude_files = glob.glob(os.path.expanduser(r"~/.claude/projects/*/*.jsonl"))
    for fpath in claude_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"Bash"' in line or '"command"' in line:
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", [])
                            if isinstance(content, list):
                                for item in content:
                                    if item.get("type") == "tool_use" and item.get("name") in ("Bash", "command"):
                                        cmd = clean_cmd(item.get("input", {}).get("command"))
                                        if cmd:
                                            record(cmd, "claude_code")
                        except Exception:
                            pass
        except Exception:
            pass

    # 4. OpenCode
    opencode_dirs = [
        os.path.expanduser(r"~/.config/opencode"),
        os.path.expanduser(r"~/.local/share/opencode"),
        os.path.expanduser(r"~/AppData/Roaming/opencode")
    ]
    for d in opencode_dirs:
        if os.path.exists(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith((".json", ".jsonl", ".db", ".txt", ".log")):
                        fpath = os.path.join(root, f)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as file_obj:
                                for line in file_obj:
                                    matches = re.findall(r"(?:ssh|git|cargo|go|npm|pnpm|python|uv|docker)\s+[^\r\n\"']+", line)
                                    for m in matches:
                                        cmd = clean_cmd(m)
                                        if cmd and len(cmd) < 300:
                                            record(cmd, "opencode")
                        except Exception:
                            pass

    # Categorize
    ssh_hosts = get_ssh_hosts()
    categorized = {
        "ssh_target_machines": [],
        "git_operations": [],
        "build_and_toolchains": [],
        "system_inspection": [],
        "project_specific": [],
        "miscellaneous": []
    }

    for cmd, sources in sorted(raw_commands.items()):
        lower = cmd.lower()
        entry = {
            "command": cmd,
            "sources": sorted(sources)
        }
        if "ssh " in lower or lower.startswith("ssh"):
            categorized["ssh_target_machines"].append(entry)
        elif "git " in lower or lower.startswith("git"):
            categorized["git_operations"].append(entry)
        elif any(t in lower for t in ["go ", "cargo ", "python ", "python3 ", "uv ", "npm ", "pnpm ", "cmake ", "rustc "]):
            categorized["build_and_toolchains"].append(entry)
        elif any(t in lower for t in ["get-childitem", "get-item", "select-string", "test-path", "cat ", "ls ", "head ", "tail ", "grep ", "tasklist"]):
            categorized["system_inspection"].append(entry)
        elif any(t in lower for t in ["sharex", "ahk", "windows-tts", "yazi", "ffmpeg"]):
            categorized["project_specific"].append(entry)
        else:
            categorized["miscellaneous"].append(entry)

    # Synthesize & Bake generalized rules
    # Host regex for SSH
    ssh_hosts_pattern = "|".join(re.escape(h) for h in ssh_hosts)
    baked_rules = [
        {
            "category": "SSH Target Machines (nuc01, nuc02, etc.)",
            "description": "Allows executing any remote command against reproducible SSH machines (including via WSL, flags, usernames, or IPs)",
            "rule": f"regex:(?s)command\\((wsl(\\.exe)?\\s+.*)?ssh\\s+.*({ssh_hosts_pattern})\\b.*\\)"
        },
        {
            "category": "SSH Remote Commands Fallback",
            "description": "Fallback broad match for ssh targeting reproducible nodes",
            "rule": f"regex:(?s).*ssh\\s+.*({ssh_hosts_pattern}).*"
        },
        {
            "category": "Git Safe & Read-Only Operations + Add",
            "description": "Allows git add, git status, and all read-only inspection commands (diff, log, show, branch, annex, etc.)",
            "rule": "regex:(?s)command\\((wsl(\\.exe)?\\s+.*)?git(\\s+--no-pager)?(\\s+-C\\s+\\S+)?\\s+(add|status|diff|log|show|branch|tag|remote|rev-parse|ls-files|ls-remote|blame|describe|shortlog|cat-file|merge-base|annex).*\\)"
        },
        {
            "category": "System & Inspection Cmdlets",
            "description": "Allows PowerShell and shell inspection commands (Get-ChildItem, Get-Item, cat, grep, tail, etc.)",
            "rule": "regex:(?s)command\\((Get-ChildItem|Get-Item|Select-String|Test-Path|cat|head|tail|grep|tasklist|ls)\\b.*\\)"
        },
        {
            "category": "Development Toolchains",
            "description": "Allows build/run operations for Go, Cargo, UV, and Python",
            "rule": "regex:(?s)command\\((go\\s+(build|test|run|version)|cargo\\s+(check|test|build)|uv\\s+(run|tool|sync)|python3?\\s+).*\\)"
        },
        {
            "category": "Local Project Binaries",
            "description": "Allows executing repository test scripts and helper binaries",
            "rule": "regex:(?s)command\\((\\.\\\\windows-tts\\.exe|sharex|ahk)\\b.*\\)"
        }
    ]

    result = {
        "metadata": {
            "description": "Ingestion file containing harvested agent commands from Claude Code, Antigravity CLI, OpenCode, and SSH configs. Can be regenerated/overwritten at will.",
            "discovered_ssh_hosts": ssh_hosts,
            "total_raw_commands_harvested": len(raw_commands),
            "counts_by_category": {k: len(v) for k, v in categorized.items()}
        },
        "baked_rules": baked_rules,
        "harvested_commands": categorized
    }

    return result

def apply_to_settings(baked_rules):
    if not os.path.exists(SETTINGS_FILE):
        print(f"Error: {SETTINGS_FILE} not found", file=sys.stderr)
        return False

    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing_allow = data.get("permissions", {}).get("allow", [])
    new_rules = [r["rule"] for r in baked_rules]

    # Combine while deduplicating
    combined = []
    # keep existing literal simple commands if desired
    for r in existing_allow:
        if not r.startswith("regex:(?s)command\\(ssh\\s+nuc02"): # replace older narrower nuc02 rule
            if r not in combined:
                combined.append(r)

    for r in new_rules:
        if r not in combined:
            combined.append(r)

    data.setdefault("permissions", {})["allow"] = combined

    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[+] Successfully applied {len(combined)} rules to {SETTINGS_FILE}")
    return True

def main():
    parser = argparse.ArgumentParser(description="Hoover and bake agent commands into Antigravity global allowlist")
    parser.add_argument("--output", "-o", default=DEFAULT_INGESTION_FILE, help="Path for ingestion file output")
    parser.add_argument("--apply", "-a", action="store_true", help="Apply baked rules to ~/.gemini/antigravity-cli/settings.json")
    args = parser.parse_args()

    print("[*] Harvesting commands across Claude, Antigravity, OpenCode, and SSH config...")
    data = harvest_all()

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[+] Wrote {data['metadata']['total_raw_commands_harvested']} harvested commands to {args.output}")
    print("[*] Summary by category:")
    for cat, count in data["metadata"]["counts_by_category"].items():
        print(f"    - {cat}: {count}")

    print(f"[*] Generated {len(data['baked_rules'])} generalized baked rules.")

    if args.apply:
        print("[*] Applying baked rules to Antigravity CLI global settings.json...")
        apply_to_settings(data["baked_rules"])

if __name__ == "__main__":
    main()
