#!/usr/bin/env python3
"""
MCP Apps Compliance Validation Script

This script validates that your MCP server follows MCP Apps best practices
and Claude's security requirements to avoid account bans.

Run: python scripts/validate_mcp_compliance.py
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def check_file(filepath: Path) -> List[Dict]:
    """Check a single file for compliance issues."""
    issues = []
    content = filepath.read_text()
    
    # Check for CSP on tools (should be on resources only)
    if filepath.name == "studio.py":
        # Look for @mcp.tool decorators with meta.ui.csp
        if re.search(r'@mcp\.tool.*meta.*csp', content, re.DOTALL):
            issues.append({
                "severity": "CRITICAL",
                "file": str(filepath),
                "issue": "CSP declared on tool decorator",
                "fix": "Move CSP to resource metadata using @mcp.resource(meta={'csp': {...}})",
            })
    
    # Check for meta.ui.resourceUri on tools that return UI content
    if filepath.name == "studio.py":
        if "studio_storyboard_frames" in content:
            if 'meta={"ui": {"resourceUri": "ui://wmstudio/storyboard-viewer"}}' not in content:
                issues.append({
                    "severity": "CRITICAL",
                    "file": str(filepath),
                    "issue": "Missing meta.ui.resourceUri on studio_storyboard_frames",
                    "fix": "Add meta={'ui': {'resourceUri': 'ui://wmstudio/storyboard-viewer'}} to @mcp.tool decorator",
                })
        if "studio_generate_video" in content:
            if 'meta={"ui": {"resourceUri": "ui://wmstudio/video-player"}}' not in content:
                issues.append({
                    "severity": "CRITICAL",
                    "file": str(filepath),
                    "issue": "Missing meta.ui.resourceUri on studio_generate_video",
                    "fix": "Add meta={'ui': {'resourceUri': 'ui://wmstudio/video-player'}} to @mcp.tool decorator",
                })
    
    # Check HTML templates for security issues
    if filepath.name == "templates.py":
        # Check for debug logging
        if "debug" in content.lower() and "log(" in content:
            issues.append({
                "severity": "HIGH",
                "file": str(filepath),
                "issue": "Debug logging code found in HTML templates",
                "fix": "Remove debug logging (console.log, debug divs, log() functions) from production HTML",
            })
        
        # Check for innerHTML usage (XSS risk)
        if "innerHTML" in content:
            issues.append({
                "severity": "HIGH",
                "file": str(filepath),
                "issue": "innerHTML usage detected (XSS vulnerability)",
                "fix": "Replace innerHTML with safe DOM manipulation (createElement, appendChild, textContent)",
            })
        
        # Check for external script dependencies
        if re.search(r'<script[^>]*src=["\']http', content):
            issues.append({
                "severity": "CRITICAL",
                "file": str(filepath),
                "issue": "External script dependency detected",
                "fix": "Inline all JavaScript in HTML templates to avoid CSP blocking",
            })
        
        # Check for correct MIME type
        if 'mime_type="text/html;profile=mcp-app"' not in content:
            issues.append({
                "severity": "CRITICAL",
                "file": str(filepath),
                "issue": "Missing or incorrect MIME type for MCP App resources",
                "fix": "Add mime_type='text/html;profile=mcp-app' to @mcp.resource decorator",
            })
        
        # Check for CSP on resources
        if '@mcp.resource' in content and 'meta={"csp"' not in content:
            issues.append({
                "severity": "HIGH",
                "file": str(filepath),
                "issue": "CSP not declared on resource metadata",
                "fix": "Add meta={'csp': {...}} to @mcp.resource decorator with appropriate CSP directives",
            })
        
        # Check for ui:// URI scheme
        if '@mcp.resource' in content and 'ui://' not in content:
            issues.append({
                "severity": "CRITICAL",
                "file": str(filepath),
                "issue": "Resources not using ui:// URI scheme",
                "fix": "Use ui://your-domain/resource-name format for resource URIs",
            })
    
    return issues


def main():
    """Run compliance validation."""
    project_root = Path(__file__).parent.parent
    src_dir = project_root / "src"
    
    print("🔍 MCP Apps Compliance Validation")
    print("=" * 50)
    print()
    
    all_issues = []
    
    # Check key files
    files_to_check = [
        src_dir / "tools" / "studio.py",
        src_dir / "resources" / "templates.py",
        src_dir / "server.py",
    ]
    
    for filepath in files_to_check:
        if filepath.exists():
            print(f"Checking {filepath.relative_to(project_root)}...")
            issues = check_file(filepath)
            all_issues.extend(issues)
            if not issues:
                print("  ✅ No issues found")
            print()
        else:
            print(f"⚠️  File not found: {filepath}")
            print()
    
    # Summary
    print("=" * 50)
    critical = [i for i in all_issues if i["severity"] == "CRITICAL"]
    high = [i for i in all_issues if i["severity"] == "HIGH"]
    
    if not all_issues:
        print("✅ All checks passed! Your MCP server appears compliant.")
        return 0
    
    print(f"Found {len(all_issues)} issue(s):")
    print(f"  - {len(critical)} CRITICAL")
    print(f"  - {len(high)} HIGH")
    print()
    
    print("Issues:")
    for issue in all_issues:
        print(f"  [{issue['severity']}] {issue['issue']}")
        print(f"    File: {issue['file']}")
        print(f"    Fix: {issue['fix']}")
        print()
    
    if critical:
        print("❌ CRITICAL issues must be fixed before deployment.")
        return 1
    elif high:
        print("⚠️  HIGH priority issues should be fixed soon.")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
