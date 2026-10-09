#!/usr/bin/env python3
"""Read-only npm v3 lockfile dependency reachability for BR Agent Office research.

A static conservative graph is not an exploitability judgment or an
authorization to execute untrusted upstream code. No npm install or imports.
"""
from __future__ import annotations

from collections import deque
import json
from pathlib import Path


def _dep_path(parent: str, package_name: str, packages: dict) -> str | None:
    if (not isinstance(package_name,str) or not package_name
            or package_name.startswith("/") or "\x00" in package_name
            or ".." in package_name.split("/")):
        return None
    base=parent
    while True:
        candidate=(base+"/" if base else "")+"node_modules/"+package_name
        if candidate in packages:
            return candidate
        if not base:
            return None
        if "/node_modules/" in base:
            base=base.rsplit("/node_modules/",1)[0]
        else:
            base=""


def production_reachability(package_lock: dict) -> dict[str, list[str]]:
    packages=package_lock.get("packages") if isinstance(package_lock,dict) else None
    if not isinstance(packages,dict) or not isinstance(packages.get(""),dict) or len(packages)>30000:
        raise ValueError("OFFICE_LOCK_GRAPH_INVALID")
    for path in packages:
        if not isinstance(path,str) or ".." in path.split("/") or path.startswith("/"):
            raise ValueError("OFFICE_LOCK_GRAPH_UNTRUSTED_PATH")
    # Include optional edges for conservative over-approximation; dev-only
    # root dependencies are not counted as production roots.
    def reqs(row):
        names=[]
        for key in ("dependencies","optionalDependencies"):
            mapping=row.get(key) or {}
            if not isinstance(mapping,dict):
                raise ValueError("OFFICE_LOCK_GRAPH_INVALID_DEPENDENCIES")
            names.extend(mapping)
        return sorted(set(names))
    queue=deque([("",())])
    reached={}
    missing=[]
    while queue:
        parent,chain=queue.popleft()
        obj=packages.get(parent)
        if not isinstance(obj,dict):
            raise ValueError("OFFICE_LOCK_GRAPH_INVALID_PACKAGE")
        for name in reqs(obj):
            resolved=_dep_path(parent,name,packages)
            if resolved is None:
                if len(missing)<1000:
                    missing.append({"parent":parent,"dependency":name})
                continue
            if resolved in reached:
                continue
            next_chain=chain+(resolved,)
            reached[resolved]=list(next_chain)
            if len(next_chain)>30000:
                raise ValueError("OFFICE_LOCK_GRAPH_UNBOUNDED")
            queue.append((resolved,next_chain))
    return {"reachable":reached,"missing":missing}


def high_dependency_paths(package_lock: dict,audit: dict) -> dict:
    graph=production_reachability(package_lock)
    entries=audit.get("vulnerabilities") if isinstance(audit,dict) else None
    if not isinstance(entries,dict):
        raise ValueError("OFFICE_AUDIT_VULNERABILITIES_MISSING")
    issues=[]
    for name,info in sorted(entries.items()):
        if not isinstance(info,dict):
            raise ValueError("OFFICE_AUDIT_INVALID_PACKAGE")
        if info.get("severity") not in ("high","critical"):
            continue
        nodes=info.get("nodes")
        if not isinstance(nodes,list):
            raise ValueError("OFFICE_AUDIT_NO_NODES")
        matches=[]
        for node in nodes:
            if not isinstance(node,str):
                raise ValueError("OFFICE_AUDIT_NODE_INVALID")
            matches.append({
                "node":node,
                "reachable_by_static_production_edges":node in graph["reachable"],
                "dependency_chain":graph["reachable"].get(node,[]),
                "lock_version":str((package_lock.get("packages") or {}).get(node,{}).get("version") or "UNKNOWN"),
            })
        issues.append({"package":name,"severity":info["severity"],"nodes":matches})
    return {
        "schema":"BRV24AgentOfficeHighDependencyReachability/v1",
        "high":issues,
        "static_production_nodes":len(graph["reachable"]),
        "unresolved_edges":len(graph["missing"]),
        "reachability_is_not_exploitability":True,
        "source_execution_authorized":False,
        "independent_security_review_required":True,
    }
